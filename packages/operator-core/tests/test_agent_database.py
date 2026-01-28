"""Unit tests for agent database initialization.

Tests verify that TicketOpsDB properly initializes schema on empty
databases and handles empty state gracefully (TEST-03).
"""

import tempfile
from pathlib import Path

import pytest

from operator_core.agent_lab.ticket_ops import TicketOpsDB


class TestTicketOpsSchemaInit:
    """Tests for TicketOpsDB schema initialization."""

    def test_initializes_schema_on_empty_database(self):
        """Verify TicketOpsDB creates schema on first connection (DEMO-01)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            # Delete to ensure truly empty database
            db_path.unlink()

            # Open connection - should initialize schema automatically
            with TicketOpsDB(db_path) as db:
                # Query should succeed without "no such table" error
                ticket = db.poll_for_open_ticket()
                assert ticket is None  # Empty database, no tickets

        finally:
            db_path.unlink(missing_ok=True)

    def test_schema_init_is_idempotent(self):
        """Verify TicketOpsDB is safe to call on existing database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            # First connection creates schema
            with TicketOpsDB(db_path) as db:
                pass

            # Second connection should not error (CREATE IF NOT EXISTS)
            with TicketOpsDB(db_path) as db:
                ticket = db.poll_for_open_ticket()
                assert ticket is None

            # Third connection just to be sure
            with TicketOpsDB(db_path) as db:
                ticket = db.poll_for_open_ticket()
                assert ticket is None

        finally:
            db_path.unlink(missing_ok=True)

    def test_poll_returns_none_on_empty_database(self):
        """Verify poll_for_open_ticket returns None when no tickets exist (DEMO-02)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with TicketOpsDB(db_path) as db:
                # Should return None, not raise exception
                result = db.poll_for_open_ticket()
                assert result is None

        finally:
            db_path.unlink(missing_ok=True)


class TestTicketOpsOperations:
    """Tests for TicketOpsDB ticket operations."""

    def test_update_methods_exist(self):
        """Verify update methods are available on TicketOpsDB."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with TicketOpsDB(db_path) as db:
                # Verify methods exist (don't call - no tickets to update)
                assert hasattr(db, "update_ticket_resolved")
                assert hasattr(db, "update_ticket_escalated")
                assert callable(db.update_ticket_resolved)
                assert callable(db.update_ticket_escalated)

        finally:
            db_path.unlink(missing_ok=True)

    def test_context_manager_closes_connection(self):
        """Verify TicketOpsDB properly closes connection on exit."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            db = TicketOpsDB(db_path)

            # Before entering context, connection should be None
            assert db._conn is None

            with db:
                # Inside context, connection should exist
                assert db._conn is not None

            # After exiting context, connection should be closed
            assert db._conn is None

        finally:
            db_path.unlink(missing_ok=True)
