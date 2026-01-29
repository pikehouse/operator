"""
SQLite-based ticket persistence.

This module provides async database operations for ticket management:
- Create or update tickets (with deduplication)
- Query tickets by status
- Resolve/hold/unhold tickets
- Auto-resolve cleared violations

Per RESEARCH.md patterns:
- Use async context manager for connection lifecycle
- Use transactions for atomicity in create_or_update
- Respect held flag in auto-resolve
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from operator_core.db.schema import SCHEMA_SQL
from operator_core.monitor.types import Ticket, TicketStatus, make_violation_key
from operator_protocols import InvariantViolation


class TicketDB:
    """
    Async context manager for ticket database operations.

    Example:
        async with TicketDB(Path("tickets.db")) as db:
            ticket = await db.create_or_update_ticket(violation)
            tickets = await db.list_tickets(status=TicketStatus.OPEN)
    """

    def __init__(self, db_path: Path) -> None:
        """
        Initialize the database connection manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "TicketDB":
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
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

    def _row_to_ticket(self, row: aiosqlite.Row) -> Ticket:
        """
        Convert a database row to a Ticket dataclass.

        Args:
            row: Database row with ticket fields

        Returns:
            Ticket instance
        """
        # Parse datetime strings
        first_seen_at = datetime.fromisoformat(row["first_seen_at"])
        last_seen_at = datetime.fromisoformat(row["last_seen_at"])
        resolved_at = (
            datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"]
            else None
        )
        created_at = (
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None
        )
        updated_at = (
            datetime.fromisoformat(row["updated_at"])
            if row["updated_at"]
            else None
        )

        # Parse metric_snapshot JSON
        metric_snapshot = (
            json.loads(row["metric_snapshot"])
            if row["metric_snapshot"]
            else None
        )

        return Ticket(
            id=row["id"],
            violation_key=row["violation_key"],
            invariant_name=row["invariant_name"],
            message=row["message"],
            severity=row["severity"],
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            status=TicketStatus(row["status"]),
            store_id=row["store_id"],
            held=bool(row["held"]),
            batch_key=row["batch_key"],
            occurrence_count=row["occurrence_count"],
            resolved_at=resolved_at,
            diagnosis=row["diagnosis"],
            metric_snapshot=metric_snapshot,
            subject_context=row["subject_context"],
            created_at=created_at,
            updated_at=updated_at,
        )

    async def create_or_update_ticket(
        self,
        violation: InvariantViolation,
        metric_snapshot: dict[str, Any] | None = None,
        batch_key: str | None = None,
        subject_context: str | None = None,
    ) -> Ticket:
        """
        Create a new ticket or update an existing open ticket.

        Implements deduplication: if an open ticket exists for the same
        violation_key, it will be updated instead of creating a duplicate.

        Args:
            violation: The invariant violation
            metric_snapshot: Optional metrics captured at violation time
            batch_key: Optional key to group related violations
            subject_context: Optional subject-specific agent prompt context

        Returns:
            The created or updated Ticket
        """
        violation_key = make_violation_key(violation)
        now = datetime.now()

        # Check for existing open ticket (atomic with subsequent operation)
        async with self._conn.execute(
            """
            SELECT * FROM tickets
            WHERE violation_key = ? AND status != 'resolved'
            """,
            (violation_key,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            # Update existing ticket
            # If ticket was diagnosed/escalated, re-open it for agent retry
            current_status = row["status"]
            if current_status == "diagnosed":
                # Re-open for agent to retry
                await self._conn.execute(
                    """
                    UPDATE tickets SET
                        last_seen_at = ?,
                        occurrence_count = occurrence_count + 1,
                        message = ?,
                        status = 'open',
                        held = 0,
                        diagnosis = NULL
                    WHERE id = ?
                    """,
                    (now.isoformat(), violation.message, row["id"]),
                )
            else:
                # Just update occurrence count
                await self._conn.execute(
                    """
                    UPDATE tickets SET
                        last_seen_at = ?,
                        occurrence_count = occurrence_count + 1,
                        message = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), violation.message, row["id"]),
                )
            await self._conn.commit()
            return await self.get_ticket(row["id"])

        # Create new ticket
        snapshot_json = json.dumps(metric_snapshot) if metric_snapshot else None
        cursor = await self._conn.execute(
            """
            INSERT INTO tickets (
                violation_key, invariant_name, store_id, message, severity,
                first_seen_at, last_seen_at, batch_key, metric_snapshot, subject_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                violation_key,
                violation.invariant_name,
                violation.store_id,
                violation.message,
                violation.severity,
                violation.first_seen.isoformat(),
                now.isoformat(),
                batch_key,
                snapshot_json,
                subject_context,
            ),
        )
        await self._conn.commit()

        # Fetch and return the created ticket
        ticket_id = cursor.lastrowid
        return await self.get_ticket(ticket_id)

    async def get_ticket(self, ticket_id: int) -> Ticket | None:
        """
        Fetch a ticket by ID.

        Args:
            ticket_id: The ticket ID

        Returns:
            The Ticket if found, None otherwise
        """
        async with self._conn.execute(
            "SELECT * FROM tickets WHERE id = ?",
            (ticket_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            return self._row_to_ticket(row)
        return None

    async def list_tickets(
        self,
        status: TicketStatus | None = None,
    ) -> list[Ticket]:
        """
        List tickets, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of tickets ordered by created_at DESC
        """
        if status:
            query = "SELECT * FROM tickets WHERE status = ? ORDER BY created_at DESC"
            params = (status.value,)
        else:
            query = "SELECT * FROM tickets ORDER BY created_at DESC"
            params = ()

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_ticket(row) for row in rows]

    async def resolve_ticket(self, ticket_id: int) -> None:
        """
        Resolve a ticket.

        Only resolves if the ticket is not held.

        Args:
            ticket_id: The ticket ID to resolve
        """
        now = datetime.now()
        await self._conn.execute(
            """
            UPDATE tickets SET
                status = 'resolved',
                resolved_at = ?
            WHERE id = ? AND held = 0
            """,
            (now.isoformat(), ticket_id),
        )
        await self._conn.commit()

    async def hold_ticket(self, ticket_id: int) -> None:
        """
        Set the hold flag on a ticket.

        Held tickets will not be auto-resolved.

        Args:
            ticket_id: The ticket ID to hold
        """
        await self._conn.execute(
            "UPDATE tickets SET held = 1 WHERE id = ?",
            (ticket_id,),
        )
        await self._conn.commit()

    async def unhold_ticket(self, ticket_id: int) -> None:
        """
        Clear the hold flag on a ticket.

        Args:
            ticket_id: The ticket ID to unhold
        """
        await self._conn.execute(
            "UPDATE tickets SET held = 0 WHERE id = ?",
            (ticket_id,),
        )
        await self._conn.commit()

    async def auto_resolve_cleared(
        self,
        current_violation_keys: set[str],
    ) -> int:
        """
        Auto-resolve open tickets whose violations have cleared.

        Resolves tickets whose violation_key is NOT in the current set
        of active violations. Respects the held flag.

        Args:
            current_violation_keys: Set of currently active violation keys

        Returns:
            Number of tickets that were resolved
        """
        now = datetime.now()

        # Get all open, non-held tickets
        async with self._conn.execute(
            """
            SELECT id, violation_key FROM tickets
            WHERE status != 'resolved' AND held = 0
            """,
        ) as cursor:
            rows = await cursor.fetchall()

        # Resolve tickets whose violations have cleared
        resolved_count = 0
        for row in rows:
            if row["violation_key"] not in current_violation_keys:
                await self._conn.execute(
                    """
                    UPDATE tickets SET
                        status = 'resolved',
                        resolved_at = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), row["id"]),
                )
                resolved_count += 1

        await self._conn.commit()
        return resolved_count

    async def update_diagnosis(
        self,
        ticket_id: int,
        diagnosis: str,
    ) -> None:
        """
        Update ticket with AI diagnosis and transition status to diagnosed.

        Per CONTEXT.md: Diagnosis is stored as markdown (human-readable first).
        Status transitions from 'open' or 'acknowledged' to 'diagnosed'.

        Args:
            ticket_id: The ticket ID to update
            diagnosis: Markdown-formatted diagnosis text
        """
        await self._conn.execute(
            """
            UPDATE tickets SET
                diagnosis = ?,
                status = 'diagnosed'
            WHERE id = ?
            """,
            (diagnosis, ticket_id),
        )
        await self._conn.commit()
