"""Ticket database operations for agent loop."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from operator_core.monitor.types import Ticket, TicketStatus, row_to_ticket


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
        from operator_core.db.schema import SCHEMA_SQL, AGENT_SCHEMA_SQL
        self._conn.executescript(SCHEMA_SQL)
        self._conn.executescript(AGENT_SCHEMA_SQL)
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

        return row_to_ticket(row)

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
