"""Tests for code_snapshots schema and AuditLogDB.record_code_snapshot()."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from operator_core.db.audit_log import AuditLogDB


class TestCodeSnapshotsSchema:
    def test_schema_creates_code_snapshots_table(self):
        """Verify code_snapshots table is created on init."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='code_snapshots'"
                )
                assert cursor.fetchone() is not None
                conn.close()
        finally:
            db_path.unlink(missing_ok=True)

    def test_schema_creates_index(self):
        """Verify the session index on code_snapshots is created."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path):
                conn = sqlite3.connect(db_path)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_code_snapshots_session'"
                )
                assert cursor.fetchone() is not None
                conn.close()
        finally:
            db_path.unlink(missing_ok=True)

    def test_schema_is_idempotent(self):
        """Creating the schema twice should not error."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path):
                pass
            with AuditLogDB(db_path):
                pass
        finally:
            db_path.unlink(missing_ok=True)


class TestRecordCodeSnapshot:
    def test_records_before_snapshot(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path) as audit:
                session_id = audit.create_session(ticket_id=1)

                snapshot_data = {
                    "commit_hash": "abc123def456",
                    "tree_hash": "789xyz",
                    "dirty": False,
                    "diff_stat": "",
                    "log": "abc123d initial",
                }

                snap_id = audit.record_code_snapshot(session_id, "before", snapshot_data)
                assert snap_id is not None
                assert snap_id > 0

            # Verify the data was written
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM code_snapshots WHERE id = ?", (snap_id,)
            )
            row = cursor.fetchone()
            conn.close()

            assert row["session_id"] == session_id
            assert row["phase"] == "before"
            assert row["commit_hash"] == "abc123def456"
            assert row["tree_hash"] == "789xyz"
            assert row["git_log"] == "abc123d initial"

        finally:
            db_path.unlink(missing_ok=True)

    def test_records_after_snapshot_with_diff(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path) as audit:
                session_id = audit.create_session(ticket_id=1)

                snapshot_data = {
                    "commit_hash": "newcommit123",
                    "tree_hash": "newtree456",
                    "dirty": False,
                    "diff_stat": " app/pool.py | 3 ++-\n 1 file changed, 2 insertions(+), 1 deletion(-)",
                    "diff_from_initial": "--- a/app/pool.py\n+++ b/app/pool.py\n@@ max_size=20",
                    "log": "newcommi fix pool\nabc123d initial",
                }

                snap_id = audit.record_code_snapshot(session_id, "after", snapshot_data)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM code_snapshots WHERE id = ?", (snap_id,)
            )
            row = cursor.fetchone()
            conn.close()

            assert row["phase"] == "after"
            assert row["commit_hash"] == "newcommit123"
            assert row["diff_from_initial"] == "--- a/app/pool.py\n+++ b/app/pool.py\n@@ max_size=20"
            assert row["files_changed"] == 1  # Parsed from diff_stat

        finally:
            db_path.unlink(missing_ok=True)

    def test_files_changed_from_explicit_field(self):
        """files_changed should prefer explicit value over parsing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path) as audit:
                session_id = audit.create_session(ticket_id=1)

                snapshot_data = {
                    "commit_hash": "abc",
                    "tree_hash": "def",
                    "files_changed": 5,
                    "diff_stat": " a.py | 1 +\n b.py | 1 +\n 2 files changed",
                }

                snap_id = audit.record_code_snapshot(session_id, "after", snapshot_data)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT files_changed FROM code_snapshots WHERE id = ?", (snap_id,)
            ).fetchone()
            conn.close()

            assert row["files_changed"] == 5

        finally:
            db_path.unlink(missing_ok=True)

    def test_multiple_snapshots_per_session(self):
        """A session can have both before and after snapshots."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

        try:
            with AuditLogDB(db_path) as audit:
                session_id = audit.create_session(ticket_id=1)

                id1 = audit.record_code_snapshot(
                    session_id, "before", {"commit_hash": "aaa", "tree_hash": "bbb"}
                )
                id2 = audit.record_code_snapshot(
                    session_id, "after", {"commit_hash": "ccc", "tree_hash": "ddd"}
                )

            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM code_snapshots WHERE session_id = ?",
                (session_id,),
            )
            count = cursor.fetchone()[0]
            conn.close()

            assert count == 2
            assert id1 != id2

        finally:
            db_path.unlink(missing_ok=True)
