"""
Audit logging for action lifecycle events (ACT-07).

This module provides comprehensive audit logging for all action lifecycle events:
- Action proposal creation and validation
- Execution start, completion, failure
- Kill switch activation and mode changes

Per project patterns:
- Pydantic BaseModel for event data structures
- Async methods for database operations
- JSON serialization for event_data blob
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from pydantic import BaseModel, Field

from operator_core.actions.secrets import SecretRedactor
from operator_core.actions.types import ActionProposal
from operator_core.db.schema import ACTIONS_SCHEMA_SQL, SCHEMA_SQL


class AuditEvent(BaseModel):
    """
    Audit event for action lifecycle tracking.

    Captures all action lifecycle events including system events
    like kill switch activation and mode changes.

    Attributes:
        id: Database ID (None before insert)
        proposal_id: Associated proposal (None for system events)
        event_type: Type of event (proposed, validated, executing, etc.)
        event_data: Event-specific details as JSON
        actor: Who triggered the event (agent, user, system)
        timestamp: When the event occurred
    """

    id: int | None = Field(default=None, description="Database ID (None before insert)")
    proposal_id: int | None = Field(
        default=None, description="Associated proposal ID (None for system events)"
    )
    event_type: str = Field(
        ..., description="Event type: proposed, validated, executing, completed, failed, cancelled, kill_switch, mode_change"
    )
    event_data: dict[str, Any] | None = Field(
        default=None, description="Event-specific details"
    )
    actor: str = Field(
        ..., description="Who triggered: 'agent', 'user', or 'system'"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When the event occurred"
    )


class ActionAuditor:
    """
    Audit logger for action lifecycle events.

    Provides methods to log all action lifecycle events to the database
    for transparency, debugging, and compliance.

    Example:
        auditor = ActionAuditor(Path("operator.db"))
        await auditor.log_proposal_created(proposal)
        await auditor.log_execution_started(proposal.id)
        await auditor.log_execution_completed(proposal.id, success=True)
    """

    def __init__(self, db_path: Path) -> None:
        """
        Initialize the action auditor.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._redactor = SecretRedactor()

    async def _ensure_schema(self, conn: aiosqlite.Connection) -> None:
        """Create tables and indexes if they don't exist."""
        await conn.executescript(SCHEMA_SQL)
        await conn.executescript(ACTIONS_SCHEMA_SQL)
        await conn.commit()

    async def log_event(self, event: AuditEvent) -> None:
        """
        Write an audit event to the database.

        Args:
            event: The audit event to log
        """
        # Redact secrets BEFORE serialization and database write (SAFE-06)
        redacted_data = (
            self._redactor.redact_dict(event.event_data)
            if event.event_data
            else None
        )
        event_data_json = json.dumps(redacted_data) if redacted_data else None

        async with aiosqlite.connect(self.db_path) as conn:
            await self._ensure_schema(conn)
            await conn.execute(
                """
                INSERT INTO action_audit_log (
                    proposal_id, event_type, event_data, actor, timestamp
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.proposal_id,
                    event.event_type,
                    event_data_json,
                    event.actor,
                    event.timestamp.isoformat(),
                ),
            )
            await conn.commit()

    async def log_proposal_created(self, proposal: ActionProposal) -> None:
        """
        Log a proposal creation event.

        Args:
            proposal: The created action proposal
        """
        await self.log_event(AuditEvent(
            proposal_id=proposal.id,
            event_type="proposed",
            event_data={
                "action_name": proposal.action_name,
                "action_type": proposal.action_type.value,
                "parameters": proposal.parameters,
                "reason": proposal.reason,
            },
            actor=proposal.proposed_by,
            timestamp=proposal.proposed_at,
        ))

    async def log_validation_passed(self, proposal_id: int) -> None:
        """
        Log that a proposal passed validation.

        Args:
            proposal_id: The proposal that was validated
        """
        await self.log_event(AuditEvent(
            proposal_id=proposal_id,
            event_type="validated",
            event_data=None,
            actor="system",
            timestamp=datetime.now(),
        ))

    async def log_execution_started(
        self,
        proposal_id: int,
        requester_id: str = "unknown",
        agent_id: str | None = None,
    ) -> None:
        """
        Log that execution has started for a proposal with dual identity (SAFE-04, SAFE-05).

        Args:
            proposal_id: The proposal being executed
            requester_id: Identity of the requester (resource owner)
            agent_id: Identity of the agent executing (client)
        """
        event_data = {
            "requester_id": requester_id,
        }
        if agent_id is not None:
            event_data["agent_id"] = agent_id

        await self.log_event(AuditEvent(
            proposal_id=proposal_id,
            event_type="executing",
            event_data=event_data,
            actor="system",
            timestamp=datetime.now(),
        ))

    async def log_execution_completed(
        self,
        proposal_id: int,
        success: bool,
        error: str | None = None,
        duration_ms: int | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """
        Log that execution completed for a proposal.

        Args:
            proposal_id: The proposal that completed
            success: Whether execution succeeded
            error: Error message if failed
            duration_ms: Execution duration in milliseconds
            result: Execution result data
        """
        if success:
            event_type = "completed"
            event_data: dict[str, Any] = {}
            if duration_ms is not None:
                event_data["duration_ms"] = duration_ms
            if result:
                event_data["result"] = result
        else:
            event_type = "failed"
            event_data = {}
            if duration_ms is not None:
                event_data["duration_ms"] = duration_ms
            if error:
                event_data["error"] = error

        await self.log_event(AuditEvent(
            proposal_id=proposal_id,
            event_type=event_type,
            event_data=event_data if event_data else None,
            actor="system",
            timestamp=datetime.now(),
        ))

    async def log_cancelled(self, proposal_id: int, reason: str) -> None:
        """
        Log that a proposal was cancelled.

        Args:
            proposal_id: The proposal that was cancelled
            reason: Why it was cancelled
        """
        await self.log_event(AuditEvent(
            proposal_id=proposal_id,
            event_type="cancelled",
            event_data={"reason": reason},
            actor="system",
            timestamp=datetime.now(),
        ))

    async def log_kill_switch(
        self,
        cancelled_count: int,
        docker_killed: int = 0,
        tasks_cancelled: int = 0,
    ) -> None:
        """
        Log a kill switch activation (system event).

        Args:
            cancelled_count: Number of proposals that were cancelled
            docker_killed: Number of Docker containers force-terminated
            tasks_cancelled: Number of asyncio tasks cancelled
        """
        await self.log_event(AuditEvent(
            proposal_id=None,  # System event
            event_type="kill_switch",
            event_data={
                "cancelled_count": cancelled_count,
                "docker_killed": docker_killed,
                "tasks_cancelled": tasks_cancelled,
            },
            actor="system",
            timestamp=datetime.now(),
        ))

    async def log_mode_change(self, old_mode: str, new_mode: str) -> None:
        """
        Log a safety mode change (system event).

        Args:
            old_mode: Previous safety mode
            new_mode: New safety mode
        """
        await self.log_event(AuditEvent(
            proposal_id=None,  # System event
            event_type="mode_change",
            event_data={"old_mode": old_mode, "new_mode": new_mode},
            actor="system",
            timestamp=datetime.now(),
        ))

    async def get_events(
        self,
        proposal_id: int | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """
        Query audit events with optional filters.

        Args:
            proposal_id: Filter by proposal ID
            event_type: Filter by event type
            limit: Maximum number of events to return

        Returns:
            List of matching audit events, ordered by timestamp DESC
        """
        conditions = []
        params: list[Any] = []

        if proposal_id is not None:
            conditions.append("proposal_id = ?")
            params.append(proposal_id)

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT id, proposal_id, event_type, event_data, actor, timestamp
            FROM action_audit_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as conn:
            await self._ensure_schema(conn)
            conn.row_factory = aiosqlite.Row
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        events = []
        for row in rows:
            event_data = json.loads(row["event_data"]) if row["event_data"] else None
            timestamp = datetime.fromisoformat(row["timestamp"])
            events.append(AuditEvent(
                id=row["id"],
                proposal_id=row["proposal_id"],
                event_type=row["event_type"],
                event_data=event_data,
                actor=row["actor"],
                timestamp=timestamp,
            ))

        return events
