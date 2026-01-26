"""
SQLite-based action persistence.

This module provides async database operations for action management:
- Create and manage action proposals
- Track execution records
- Support kill switch via cancel_all_pending

Per project patterns:
- Use async context manager for connection lifecycle
- Use transactions for atomicity
- Follow TicketDB patterns for consistency
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)
from operator_core.db.schema import ACTIONS_SCHEMA_SQL, SCHEMA_SQL


class ActionDB:
    """
    Async context manager for action database operations.

    Example:
        async with ActionDB(Path("actions.db")) as db:
            proposal = await db.create_proposal(action_proposal)
            proposals = await db.list_proposals(status=ActionStatus.PROPOSED)
    """

    def __init__(self, db_path: Path) -> None:
        """
        Initialize the database connection manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "ActionDB":
        """Open database connection and ensure schema exists."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._ensure_schema()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        # Execute both schemas - tickets first (for foreign key), then actions
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.executescript(ACTIONS_SCHEMA_SQL)

        # Migration: Add approval columns if they don't exist
        # Use individual try/except blocks per column (Pattern 4 from 14-RESEARCH.md)
        try:
            await self._conn.execute(
                "ALTER TABLE action_proposals ADD COLUMN approved_at TEXT"
            )
        except Exception:
            pass  # Column already exists

        try:
            await self._conn.execute(
                "ALTER TABLE action_proposals ADD COLUMN approved_by TEXT"
            )
        except Exception:
            pass  # Column already exists

        try:
            await self._conn.execute(
                "ALTER TABLE action_proposals ADD COLUMN rejected_at TEXT"
            )
        except Exception:
            pass  # Column already exists

        try:
            await self._conn.execute(
                "ALTER TABLE action_proposals ADD COLUMN rejected_by TEXT"
            )
        except Exception:
            pass  # Column already exists

        try:
            await self._conn.execute(
                "ALTER TABLE action_proposals ADD COLUMN rejection_reason TEXT"
            )
        except Exception:
            pass  # Column already exists

        await self._conn.commit()

    def _row_to_proposal(self, row: aiosqlite.Row) -> ActionProposal:
        """
        Convert a database row to an ActionProposal.

        Args:
            row: Database row with proposal fields

        Returns:
            ActionProposal instance
        """
        # Parse datetime strings
        proposed_at = datetime.fromisoformat(row["proposed_at"])

        # Parse approval datetime fields (may be None)
        approved_at = (
            datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None
        )
        rejected_at = (
            datetime.fromisoformat(row["rejected_at"]) if row["rejected_at"] else None
        )

        # Parse parameters JSON
        parameters = json.loads(row["parameters"]) if row["parameters"] else {}

        return ActionProposal(
            id=row["id"],
            ticket_id=row["ticket_id"],
            action_name=row["action_name"],
            action_type=ActionType(row["action_type"]),
            parameters=parameters,
            reason=row["reason"],
            status=ActionStatus(row["status"]),
            proposed_at=proposed_at,
            proposed_by=row["proposed_by"],
            approved_at=approved_at,
            approved_by=row["approved_by"],
            rejected_at=rejected_at,
            rejected_by=row["rejected_by"],
            rejection_reason=row["rejection_reason"],
        )

    def _row_to_record(self, row: aiosqlite.Row) -> ActionRecord:
        """
        Convert a database row to an ActionRecord.

        Args:
            row: Database row with record fields

        Returns:
            ActionRecord instance
        """
        # Parse optional datetime strings
        started_at = (
            datetime.fromisoformat(row["started_at"]) if row["started_at"] else None
        )
        completed_at = (
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
        )

        # Parse success (SQLite stores as 0/1/NULL)
        success = None
        if row["success"] is not None:
            success = bool(row["success"])

        # Parse result_data JSON
        result_data = (
            json.loads(row["result_data"]) if row["result_data"] else None
        )

        return ActionRecord(
            id=row["id"],
            proposal_id=row["proposal_id"],
            started_at=started_at,
            completed_at=completed_at,
            success=success,
            error_message=row["error_message"],
            result_data=result_data,
        )

    # =========================================================================
    # Proposal operations
    # =========================================================================

    async def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        """
        Create a new action proposal.

        Args:
            proposal: The action proposal to create

        Returns:
            The created ActionProposal with ID populated
        """
        parameters_json = json.dumps(proposal.parameters)

        cursor = await self._conn.execute(
            """
            INSERT INTO action_proposals (
                ticket_id, action_name, action_type, parameters, reason,
                status, proposed_at, proposed_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.ticket_id,
                proposal.action_name,
                proposal.action_type.value,
                parameters_json,
                proposal.reason,
                proposal.status.value,
                proposal.proposed_at.isoformat(),
                proposal.proposed_by,
            ),
        )
        await self._conn.commit()

        # Return proposal with ID
        proposal_id = cursor.lastrowid
        return await self.get_proposal(proposal_id)

    async def get_proposal(self, proposal_id: int) -> ActionProposal | None:
        """
        Fetch an action proposal by ID.

        Args:
            proposal_id: The proposal ID

        Returns:
            The ActionProposal if found, None otherwise
        """
        async with self._conn.execute(
            "SELECT * FROM action_proposals WHERE id = ?",
            (proposal_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            return self._row_to_proposal(row)
        return None

    async def list_proposals(
        self,
        status: ActionStatus | None = None,
    ) -> list[ActionProposal]:
        """
        List action proposals, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of proposals ordered by created_at DESC
        """
        if status:
            query = (
                "SELECT * FROM action_proposals WHERE status = ? "
                "ORDER BY created_at DESC"
            )
            params = (status.value,)
        else:
            query = "SELECT * FROM action_proposals ORDER BY created_at DESC"
            params = ()

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_proposal(row) for row in rows]

    async def update_proposal_status(
        self,
        proposal_id: int,
        status: ActionStatus,
    ) -> None:
        """
        Update the status of an action proposal.

        Args:
            proposal_id: The proposal ID to update
            status: The new status
        """
        # Update timestamp fields based on status transition
        extra_updates = ""
        if status == ActionStatus.VALIDATED:
            extra_updates = ", validated_at = ?"
        elif status == ActionStatus.CANCELLED:
            extra_updates = ", cancelled_at = ?"

        now = datetime.now().isoformat()

        if extra_updates:
            await self._conn.execute(
                f"""
                UPDATE action_proposals SET
                    status = ?
                    {extra_updates}
                WHERE id = ?
                """,
                (status.value, now, proposal_id),
            )
        else:
            await self._conn.execute(
                """
                UPDATE action_proposals SET status = ? WHERE id = ?
                """,
                (status.value, proposal_id),
            )
        await self._conn.commit()

    async def cancel_all_pending(self) -> int:
        """
        Cancel all pending (proposed or validated) proposals.

        Used by kill switch to halt all pending actions.

        Returns:
            Number of proposals that were cancelled
        """
        now = datetime.now().isoformat()

        # Count pending proposals
        async with self._conn.execute(
            """
            SELECT COUNT(*) as count FROM action_proposals
            WHERE status IN ('proposed', 'validated')
            """,
        ) as cursor:
            row = await cursor.fetchone()
            count = row["count"]

        # Cancel all pending
        await self._conn.execute(
            """
            UPDATE action_proposals SET
                status = 'cancelled',
                cancelled_at = ?
            WHERE status IN ('proposed', 'validated')
            """,
            (now,),
        )
        await self._conn.commit()

        return count

    # =========================================================================
    # Approval operations
    # =========================================================================

    async def is_approved(self, proposal_id: int) -> bool:
        """
        Check if a proposal has been approved.

        Args:
            proposal_id: The proposal ID to check

        Returns:
            True if the proposal has been approved, False otherwise
        """
        async with self._conn.execute(
            "SELECT approved_at FROM action_proposals WHERE id = ?",
            (proposal_id,),
        ) as cursor:
            row = await cursor.fetchone()

        return row is not None and row["approved_at"] is not None

    async def approve_proposal(
        self,
        proposal_id: int,
        approved_by: str = "user",
    ) -> None:
        """
        Mark a validated proposal as approved.

        Args:
            proposal_id: The proposal ID to approve
            approved_by: Who approved (default: "user")

        Raises:
            ValueError: If proposal not found or not in VALIDATED status
        """
        # First check proposal exists and is in VALIDATED status
        proposal = await self.get_proposal(proposal_id)

        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        if proposal.status != ActionStatus.VALIDATED:
            raise ValueError(
                f"Proposal {proposal_id} is {proposal.status.value}, "
                "expected 'validated'"
            )

        now = datetime.now().isoformat()

        await self._conn.execute(
            """
            UPDATE action_proposals SET
                approved_at = ?,
                approved_by = ?
            WHERE id = ?
            """,
            (now, approved_by, proposal_id),
        )
        await self._conn.commit()

    async def reject_proposal(
        self,
        proposal_id: int,
        rejected_by: str = "user",
        reason: str = "",
    ) -> None:
        """
        Mark a validated proposal as rejected and cancel it.

        Args:
            proposal_id: The proposal ID to reject
            rejected_by: Who rejected (default: "user")
            reason: Why the proposal was rejected

        Raises:
            ValueError: If proposal not found or not in VALIDATED status
        """
        # First check proposal exists and is in VALIDATED status
        proposal = await self.get_proposal(proposal_id)

        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        if proposal.status != ActionStatus.VALIDATED:
            raise ValueError(
                f"Proposal {proposal_id} is {proposal.status.value}, "
                "expected 'validated'"
            )

        now = datetime.now().isoformat()

        await self._conn.execute(
            """
            UPDATE action_proposals SET
                rejected_at = ?,
                rejected_by = ?,
                rejection_reason = ?,
                status = ?,
                cancelled_at = ?
            WHERE id = ?
            """,
            (now, rejected_by, reason, ActionStatus.CANCELLED.value, now, proposal_id),
        )
        await self._conn.commit()

    # =========================================================================
    # Record operations
    # =========================================================================

    async def create_record(self, record: ActionRecord) -> ActionRecord:
        """
        Create a new execution record.

        Args:
            record: The execution record to create

        Returns:
            The created ActionRecord with ID populated
        """
        result_data_json = (
            json.dumps(record.result_data) if record.result_data else None
        )
        started_at = record.started_at.isoformat() if record.started_at else None
        completed_at = record.completed_at.isoformat() if record.completed_at else None

        # Convert bool to int for SQLite
        success = None
        if record.success is not None:
            success = 1 if record.success else 0

        cursor = await self._conn.execute(
            """
            INSERT INTO action_records (
                proposal_id, started_at, completed_at, success,
                error_message, result_data
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.proposal_id,
                started_at,
                completed_at,
                success,
                record.error_message,
                result_data_json,
            ),
        )
        await self._conn.commit()

        # Return record with ID
        record_id = cursor.lastrowid
        return await self.get_record(record_id)

    async def get_record(self, record_id: int) -> ActionRecord | None:
        """
        Fetch an execution record by ID.

        Args:
            record_id: The record ID

        Returns:
            The ActionRecord if found, None otherwise
        """
        async with self._conn.execute(
            "SELECT * FROM action_records WHERE id = ?",
            (record_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            return self._row_to_record(row)
        return None

    async def update_record(
        self,
        record_id: int,
        success: bool,
        error_message: str | None = None,
        result_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Update an execution record with completion data.

        Args:
            record_id: The record ID to update
            success: Whether execution succeeded
            error_message: Error details if failed
            result_data: Execution output data
        """
        completed_at = datetime.now().isoformat()
        result_data_json = json.dumps(result_data) if result_data else None
        success_int = 1 if success else 0

        await self._conn.execute(
            """
            UPDATE action_records SET
                completed_at = ?,
                success = ?,
                error_message = ?,
                result_data = ?
            WHERE id = ?
            """,
            (completed_at, success_int, error_message, result_data_json, record_id),
        )
        await self._conn.commit()

    async def get_records_for_proposal(
        self,
        proposal_id: int,
    ) -> list[ActionRecord]:
        """
        Get all execution records for a proposal.

        Args:
            proposal_id: The proposal ID

        Returns:
            List of execution records ordered by created_at DESC
        """
        async with self._conn.execute(
            """
            SELECT * FROM action_records
            WHERE proposal_id = ?
            ORDER BY created_at DESC
            """,
            (proposal_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_record(row) for row in rows]
