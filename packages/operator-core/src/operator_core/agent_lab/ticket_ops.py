"""Ticket database operations for agent loop."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from warnings import warn

from operator_core.monitor.types import Ticket, TicketStatus


class TicketOpsDB:
    """
    Synchronous context manager for ticket database operations.

    Example:
        with TicketOpsDB(Path("tickets.db")) as db:
            ticket = db.poll_for_open_ticket()
            if ticket:
                db.update_ticket_resolved(ticket.id, "Fixed by restarting service")
    """

    def __init__(self, db_path: Path) -> None:
        """
        Initialize the database connection manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "TicketOpsDB":
        """Open database connection and ensure schema exists."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        from operator_core.db.schema import SCHEMA_SQL, ACTIONS_SCHEMA_SQL
        self._conn.executescript(SCHEMA_SQL)
        self._conn.executescript(ACTIONS_SCHEMA_SQL)
        self._conn.commit()

    def poll_for_open_ticket(self) -> Ticket | None:
        """Poll for first open ticket.

        Returns:
            First open ticket, or None if no open tickets
        """
        cursor = self._conn.execute(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC LIMIT 1"
        )
        row = cursor.fetchone()

        if not row:
            return None

        return Ticket(
            id=row["id"],
            violation_key=row["violation_key"],
            invariant_name=row["invariant_name"],
            message=row["message"],
            severity=row["severity"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            status=TicketStatus(row["status"]),
            store_id=row["store_id"],
            held=bool(row["held"]),
            batch_key=row["batch_key"],
            occurrence_count=row["occurrence_count"],
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
            diagnosis=row["diagnosis"],
            metric_snapshot=json.loads(row["metric_snapshot"]) if row["metric_snapshot"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_ticket_resolved(self, ticket_id: int, summary: str) -> None:
        """Mark ticket as resolved.

        Args:
            ticket_id: ID of ticket to update
            summary: Resolution summary
        """
        self._conn.execute(
            "UPDATE tickets SET status = 'resolved', resolved_at = ?, diagnosis = ? WHERE id = ?",
            (datetime.now().isoformat(), summary, ticket_id),
        )
        self._conn.commit()

    def update_ticket_escalated(self, ticket_id: int, reason: str) -> None:
        """Mark ticket as escalated.

        Args:
            ticket_id: ID of ticket to update
            reason: Escalation reason
        """
        self._conn.execute(
            "UPDATE tickets SET status = 'diagnosed', diagnosis = ? WHERE id = ?",
            (f"ESCALATED: {reason}", ticket_id),
        )
        self._conn.commit()

    def hold_ticket(self, ticket_id: int) -> None:
        """Hold ticket to prevent auto-resolution while agent is working.

        Args:
            ticket_id: ID of ticket to hold
        """
        self._conn.execute(
            "UPDATE tickets SET held = 1, status = 'acknowledged' WHERE id = ?",
            (ticket_id,),
        )
        self._conn.commit()

    def unhold_ticket(self, ticket_id: int) -> None:
        """Release hold on ticket (typically after resolution/escalation).

        Args:
            ticket_id: ID of ticket to unhold
        """
        self._conn.execute(
            "UPDATE tickets SET held = 0 WHERE id = ?",
            (ticket_id,),
        )
        self._conn.commit()


# Deprecated module-level functions for backward compatibility
def poll_for_open_ticket(db_path: Path) -> Ticket | None:
    """Poll for first open ticket.

    .. deprecated::
        Use TicketOpsDB context manager instead.

    Args:
        db_path: Path to SQLite database

    Returns:
        First open ticket, or None if no open tickets
    """
    warn("poll_for_open_ticket() is deprecated, use TicketOpsDB context manager", DeprecationWarning, stacklevel=2)
    with TicketOpsDB(db_path) as db:
        return db.poll_for_open_ticket()


def update_ticket_resolved(db_path: Path, ticket_id: int, summary: str) -> None:
    """Mark ticket as resolved.

    .. deprecated::
        Use TicketOpsDB context manager instead.

    Args:
        db_path: Path to SQLite database
        ticket_id: ID of ticket to update
        summary: Resolution summary
    """
    warn("update_ticket_resolved() is deprecated, use TicketOpsDB context manager", DeprecationWarning, stacklevel=2)
    with TicketOpsDB(db_path) as db:
        db.update_ticket_resolved(ticket_id, summary)


def update_ticket_escalated(db_path: Path, ticket_id: int, reason: str) -> None:
    """Mark ticket as escalated.

    .. deprecated::
        Use TicketOpsDB context manager instead.

    Args:
        db_path: Path to SQLite database
        ticket_id: ID of ticket to update
        reason: Escalation reason
    """
    warn("update_ticket_escalated() is deprecated, use TicketOpsDB context manager", DeprecationWarning, stacklevel=2)
    with TicketOpsDB(db_path) as db:
        db.update_ticket_escalated(ticket_id, reason)
