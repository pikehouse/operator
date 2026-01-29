"""
SQLite-based audit log for agent sessions.

This module provides synchronous database operations for agent session logging:
- Create session records
- Log conversation entries (reasoning, tool calls, results)
- Complete sessions with status and summary
- Query session history for review/replay

Per Phase 31 design:
- Synchronous context manager (not async) for use with tool_runner
- Logs both raw and summarized content
- Supports time-ordered replay of sessions
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class AuditLogDB:
    """
    Synchronous context manager for agent audit logging.

    Example:
        with AuditLogDB(Path("tickets.db")) as audit:
            session_id = audit.create_session(ticket_id=123)
            audit.log_entry(session_id, "reasoning", "Checking logs...", raw_text, None, None, None)
            audit.complete_session(session_id, "resolved", "Fixed by restarting service")
    """

    def __init__(self, db_path: Path) -> None:
        """
        Initialize the database connection manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "AuditLogDB":
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

    def create_session(self, ticket_id: int | None = None) -> str:
        """
        Create a new agent session record.

        Args:
            ticket_id: Optional ticket ID this session is addressing

        Returns:
            session_id in format {timestamp}-{uuid[:8]}
        """
        # Generate session ID: {timestamp}-{uuid4[:8]}
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        uuid_component = str(uuid.uuid4())[:8]
        session_id = f"{timestamp}-{uuid_component}"

        now = datetime.now().isoformat()

        cursor = self._conn.execute(
            """
            INSERT INTO agent_sessions (session_id, ticket_id, status, started_at)
            VALUES (?, ?, 'running', ?)
            """,
            (session_id, ticket_id, now),
        )
        self._conn.commit()

        return session_id

    def log_entry(
        self,
        session_id: str,
        entry_type: str,
        content: str,
        raw_content: str | None = None,
        tool_name: str | None = None,
        tool_params: dict | None = None,
        exit_code: int | None = None,
    ) -> int:
        """
        Log a session entry (reasoning, tool_call, or tool_result).

        Args:
            session_id: Session identifier
            entry_type: Type of entry (reasoning, tool_call, tool_result)
            content: Summarized content (Haiku-summarized)
            raw_content: Optional full content before summarization
            tool_name: Optional tool name (for tool_call/tool_result)
            tool_params: Optional tool parameters as dict (for tool_call)
            exit_code: Optional exit code (for tool_result)

        Returns:
            entry_id: The created log entry ID
        """
        now = datetime.now().isoformat()
        tool_params_json = json.dumps(tool_params) if tool_params else None

        cursor = self._conn.execute(
            """
            INSERT INTO agent_log_entries (
                session_id, entry_type, content, raw_content, tool_name,
                tool_params, exit_code, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                entry_type,
                content,
                raw_content,
                tool_name,
                tool_params_json,
                exit_code,
                now,
            ),
        )
        self._conn.commit()

        return cursor.lastrowid

    def complete_session(
        self,
        session_id: str,
        status: str,
        outcome_summary: str,
    ) -> None:
        """
        Mark session as complete with final status and summary.

        Args:
            session_id: Session identifier
            status: Final status (completed, failed, escalated)
            outcome_summary: Summary of session outcome (Haiku-summarized)
        """
        now = datetime.now().isoformat()

        self._conn.execute(
            """
            UPDATE agent_sessions
            SET status = ?, ended_at = ?, outcome_summary = ?
            WHERE session_id = ?
            """,
            (status, now, outcome_summary, session_id),
        )
        self._conn.commit()

    def get_session_entries(self, session_id: str) -> list[dict]:
        """
        Retrieve all log entries for a session in chronological order.

        Args:
            session_id: Session identifier

        Returns:
            List of log entries as dictionaries
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM agent_log_entries
            WHERE session_id = ?
            ORDER BY timestamp ASC
            """,
            (session_id,),
        )

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_entries_by_timerange(self, start_time: datetime, end_time: datetime) -> list[dict]:
        """
        Retrieve all log entries within a time range.

        Args:
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive)

        Returns:
            List of log entries as dictionaries
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM agent_log_entries
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (start_time.isoformat(), end_time.isoformat()),
        )

        rows = cursor.fetchall()
        return [dict(row) for row in rows]
