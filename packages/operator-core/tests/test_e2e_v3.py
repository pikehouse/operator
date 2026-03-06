"""
End-to-end tests for v3 architecture.

Tests the full flow:
  Monitor detects violation → creates ticket → agent picks up ticket →
  agent processes with SDK → agent resolves ticket → audit trail recorded

This test suite validates the core v3 components work together:
- MonitorLoop (observe → invariant check → ticket creation)
- TicketOpsDB (poll, hold, resolve)
- AuditLogDB (session, entries, completion)

No real Claude API calls - we mock the Agent SDK.
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from operator_protocols import (
    SubjectProtocol,
    InvariantCheckerProtocol,
    InvariantViolation,
)
from operator_core.monitor.loop import MonitorLoop
from operator_core.monitor.types import TicketStatus, TicketType
from operator_core.db.tickets import TicketDB
from operator_core.agent_lab.ticket_ops import TicketOpsDB
from operator_core.db.audit_log import AuditLogDB


# =============================================================================
# Mock Subject and Checker
# =============================================================================


class MockSubject:
    """Mock subject that can toggle between healthy and unhealthy states."""

    def __init__(self, healthy: bool = True):
        self.healthy = healthy
        self.observe_count = 0

    async def observe(self) -> dict[str, Any]:
        self.observe_count += 1
        return {
            "nodes": [
                {"id": "node-1", "status": "up" if self.healthy else "down"},
            ],
            "timestamp": datetime.now().isoformat(),
        }

    def get_action_definitions(self):
        return []


class MockChecker:
    """Mock checker that returns violations when subject is unhealthy."""

    def __init__(self, subject: MockSubject):
        self.subject = subject
        self.check_count = 0

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        self.check_count += 1
        violations = []
        for node in observation.get("nodes", []):
            if node.get("status") == "down":
                violations.append(
                    InvariantViolation(
                        invariant_name="node_down",
                        message=f"Node {node['id']} is down",
                        first_seen=datetime.now(),
                        last_seen=datetime.now(),
                        store_id=node["id"],
                        severity="critical",
                    )
                )
        return violations


# =============================================================================
# Protocol Compliance
# =============================================================================


class TestProtocolCompliance:
    """Verify mock objects implement the protocols correctly."""

    def test_mock_subject_is_subject_protocol(self):
        subject = MockSubject()
        assert isinstance(subject, SubjectProtocol)

    def test_mock_checker_is_invariant_checker_protocol(self):
        subject = MockSubject()
        checker = MockChecker(subject)
        assert isinstance(checker, InvariantCheckerProtocol)


# =============================================================================
# Monitor → Ticket Flow
# =============================================================================


class TestMonitorTicketFlow:
    """Test monitor creates tickets when violations detected."""

    @pytest.mark.asyncio
    async def test_monitor_creates_ticket_on_violation(self, tmp_path: Path):
        """Monitor should create a ticket when invariant is violated."""
        db_path = tmp_path / "test.db"
        subject = MockSubject(healthy=False)  # Node is down
        checker = MockChecker(subject)

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)
            tickets = await db.list_tickets()

            assert len(tickets) == 1
            assert tickets[0].invariant_name == "node_down"
            assert tickets[0].store_id == "node-1"
            assert tickets[0].status == TicketStatus.OPEN

    @pytest.mark.asyncio
    async def test_monitor_no_ticket_when_healthy(self, tmp_path: Path):
        """Monitor should not create tickets when all invariants pass."""
        db_path = tmp_path / "test.db"
        subject = MockSubject(healthy=True)
        checker = MockChecker(subject)

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)
            tickets = await db.list_tickets()

            assert len(tickets) == 0


# =============================================================================
# TicketOpsDB Operations
# =============================================================================


class TestTicketOpsDB:
    """Test agent's ticket operations."""

    @pytest.mark.asyncio
    async def test_poll_returns_open_ticket(self, tmp_path: Path):
        """TicketOpsDB should find tickets created by monitor."""
        db_path = tmp_path / "test.db"

        # Create ticket via monitor
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )
        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        # Agent polls for ticket
        with TicketOpsDB(db_path) as ops:
            ticket = ops.poll_for_open_ticket()

            assert ticket is not None
            assert ticket.invariant_name == "node_down"
            assert ticket.status == TicketStatus.OPEN

    @pytest.mark.asyncio
    async def test_hold_ticket_changes_status(self, tmp_path: Path):
        """Holding a ticket should change its status to acknowledged."""
        db_path = tmp_path / "test.db"

        # Create ticket
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )
        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        # Hold ticket
        with TicketOpsDB(db_path) as ops:
            ticket = ops.poll_for_open_ticket()
            ops.hold_ticket(ticket.id)

        # Verify hold
        with TicketOpsDB(db_path) as ops:
            # Open ticket poll should now return None (ticket is acknowledged)
            open_ticket = ops.poll_for_open_ticket()
            assert open_ticket is None

    @pytest.mark.asyncio
    async def test_resolve_ticket(self, tmp_path: Path):
        """Resolving a ticket should update status and add summary."""
        db_path = tmp_path / "test.db"

        # Create ticket
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )
        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        # Resolve ticket
        with TicketOpsDB(db_path) as ops:
            ticket = ops.poll_for_open_ticket()
            ops.update_ticket_resolved(ticket.id, "Fixed by restarting node")

        # Verify resolution
        async with TicketDB(db_path) as db:
            tickets = await db.list_tickets()
            assert len(tickets) == 1
            assert tickets[0].status == TicketStatus.RESOLVED
            assert tickets[0].diagnosis == "Fixed by restarting node"


# =============================================================================
# AuditLogDB Operations
# =============================================================================


class TestAuditLogDB:
    """Test audit logging for agent sessions."""

    def test_create_session(self, tmp_path: Path):
        """Should create a session record."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=123)

            assert session_id is not None
            assert "-" in session_id  # Format: timestamp-uuid

    def test_log_reasoning_entry(self, tmp_path: Path):
        """Should log reasoning entries."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=123)
            entry_id = audit.log_entry(
                session_id=session_id,
                entry_type="reasoning",
                content="Checking node status",
                raw_content="I will check the node status by running docker ps...",
            )

            assert entry_id is not None
            entries = audit.get_session_entries(session_id)
            assert len(entries) == 1
            assert entries[0]["entry_type"] == "reasoning"
            assert entries[0]["content"] == "Checking node status"

    def test_log_tool_call_entry(self, tmp_path: Path):
        """Should log tool call entries with parameters."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=123)
            audit.log_entry(
                session_id=session_id,
                entry_type="tool_call",
                content="Bash: docker ps",
                tool_name="Bash",
                tool_params={"command": "docker ps"},
            )

            entries = audit.get_session_entries(session_id)
            assert len(entries) == 1
            assert entries[0]["tool_name"] == "Bash"
            assert "docker ps" in entries[0]["tool_params"]

    def test_log_tool_result_entry(self, tmp_path: Path):
        """Should log tool result entries with exit code."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=123)
            audit.log_entry(
                session_id=session_id,
                entry_type="tool_result",
                content="Container list retrieved",
                raw_content="CONTAINER ID   IMAGE   ...",
                exit_code=0,
            )

            entries = audit.get_session_entries(session_id)
            assert len(entries) == 1
            assert entries[0]["exit_code"] == 0

    def test_complete_session(self, tmp_path: Path):
        """Should complete session with status and summary."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=123)
            audit.log_entry(session_id, "reasoning", "Working...")
            audit.complete_session(session_id, "resolved", "Node restarted successfully")

        # Verify via raw SQL (since get_session doesn't exist)
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
        )
        row = cursor.fetchone()
        conn.close()

        assert row["status"] == "resolved"
        assert row["outcome_summary"] == "Node restarted successfully"
        assert row["ended_at"] is not None


# =============================================================================
# Full E2E Flow
# =============================================================================


class TestE2EFlow:
    """Test complete end-to-end flow without Claude API."""

    @pytest.mark.asyncio
    async def test_full_flow_monitor_to_resolution(self, tmp_path: Path):
        """
        Complete flow:
        1. Monitor detects violation → creates ticket
        2. Agent polls for ticket → holds it
        3. Agent creates audit session
        4. Agent logs reasoning and tool usage
        5. Agent resolves ticket
        6. Audit trail is complete
        """
        db_path = tmp_path / "test.db"

        # Step 1: Monitor detects violation
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        # Step 2: Agent polls for ticket
        with TicketOpsDB(db_path) as ops:
            ticket = ops.poll_for_open_ticket()
            assert ticket is not None
            assert ticket.invariant_name == "node_down"

            # Hold ticket
            ops.hold_ticket(ticket.id)

        # Step 3-5: Agent processes ticket (simulated, no Claude)
        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session(ticket_id=ticket.id)

            # Log reasoning
            audit.log_entry(
                session_id,
                "reasoning",
                "Node is down, will check docker status",
                raw_content="The ticket indicates node-1 is down. I will check...",
            )

            # Log tool call (Bash instead of shell)
            audit.log_entry(
                session_id,
                "tool_call",
                "Bash: docker restart node-1",
                tool_name="Bash",
                tool_params={"command": "docker restart node-1"},
            )

            # Log tool result
            audit.log_entry(
                session_id,
                "tool_result",
                "Node restarted",
                raw_content="node-1\n",
                exit_code=0,
            )

            # Complete session
            audit.complete_session(session_id, "resolved", "Restarted node-1")

            # Resolve ticket
            with TicketOpsDB(db_path) as ops:
                ops.update_ticket_resolved(ticket.id, "Restarted node-1")

        # Step 6: Verify audit trail
        with AuditLogDB(db_path) as audit:
            entries = audit.get_session_entries(session_id)
            assert len(entries) == 3
            assert entries[0]["entry_type"] == "reasoning"
            assert entries[1]["entry_type"] == "tool_call"
            assert entries[2]["entry_type"] == "tool_result"

        # Verify ticket resolved
        async with TicketDB(db_path) as db:
            tickets = await db.list_tickets()
            assert len(tickets) == 1
            assert tickets[0].status == TicketStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_auto_resolve_when_violation_clears(self, tmp_path: Path):
        """Monitor should auto-resolve ticket when violation clears."""
        db_path = tmp_path / "test.db"

        # Create violation
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0,
            stability_window_sec=0,
        )

        async with TicketDB(db_path) as db:
            # First cycle: violation present
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert tickets[0].status == TicketStatus.OPEN

            # Fix the problem
            subject.healthy = True

            # Second cycle: violation cleared
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert tickets[0].status == TicketStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_operator_override_ticket_not_auto_resolved(self, tmp_path: Path):
        """Operator-override tickets should survive auto-resolve (no matching violation)."""
        db_path = tmp_path / "test.db"

        subject = MockSubject(healthy=True)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )

        async with TicketDB(db_path) as db:
            # Manually insert an operator-override ticket
            violation = InvariantViolation(
                invariant_name="operator_override",
                message="Add a comment to main.py",
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                severity="warning",
            )
            ticket = await db.create_or_update_ticket(
                violation, type=TicketType.OPERATOR_OVERRIDE
            )
            assert ticket.type == TicketType.OPERATOR_OVERRIDE

            # Run a check cycle — no violations exist, but the override ticket
            # should NOT be auto-resolved
            await loop._check_cycle(db)

            tickets = await db.list_tickets(status=TicketStatus.OPEN)
            assert len(tickets) == 1
            assert tickets[0].type == TicketType.OPERATOR_OVERRIDE


# =============================================================================
# Database Schema Compatibility
# =============================================================================


class TestSchemaCompatibility:
    """Test that TicketDB and agent DBs share same schema."""

    @pytest.mark.asyncio
    async def test_ticket_db_and_ticket_ops_share_schema(self, tmp_path: Path):
        """TicketDB (async) and TicketOpsDB (sync) should work on same database."""
        db_path = tmp_path / "test.db"

        # Create ticket via async TicketDB
        subject = MockSubject(healthy=False)
        checker = MockChecker(subject)
        loop = MonitorLoop(
            subject=subject, checker=checker, db_path=db_path, interval_seconds=1.0
        )

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        # Read via sync TicketOpsDB
        with TicketOpsDB(db_path) as ops:
            ticket = ops.poll_for_open_ticket()
            assert ticket is not None

        # Modify via sync
        with TicketOpsDB(db_path) as ops:
            ops.update_ticket_resolved(ticket.id, "Fixed")

        # Verify via async
        async with TicketDB(db_path) as db:
            tickets = await db.list_tickets()
            assert tickets[0].status == TicketStatus.RESOLVED

    def test_audit_db_creates_required_tables(self, tmp_path: Path):
        """AuditLogDB should create agent_sessions and agent_log_entries tables."""
        db_path = tmp_path / "test.db"

        with AuditLogDB(db_path) as audit:
            session_id = audit.create_session()

        # Verify tables exist
        import sqlite3

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "agent_sessions" in tables
        assert "agent_log_entries" in tables
