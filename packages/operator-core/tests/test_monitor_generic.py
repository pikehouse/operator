"""
Generic monitor tests with mock subject.

Verifies that MonitorLoop works with any subject implementing SubjectProtocol,
not just TiKVSubject. This proves the abstraction is correct.
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


class MockSubject:
    """Mock subject implementing SubjectProtocol."""

    def __init__(self):
        self.observe_call_count = 0
        self.observation_data = {
            "nodes": [{"id": "1", "status": "healthy"}],
            "metrics": {"qps": 100},
        }

    async def observe(self) -> dict[str, Any]:
        self.observe_call_count += 1
        return self.observation_data

    def get_action_definitions(self):
        return []


class MockChecker:
    """Mock checker implementing InvariantCheckerProtocol."""

    def __init__(self, violations: list[InvariantViolation] | None = None):
        self.violations = violations or []
        self.check_call_count = 0
        self.last_observation = None

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        self.check_call_count += 1
        self.last_observation = observation
        return self.violations


class TestMockSubjectProtocolCompliance:
    """Tests that mock subject implements SubjectProtocol."""

    def test_mock_subject_is_subject_protocol(self):
        """MockSubject should pass isinstance check for SubjectProtocol."""
        subject = MockSubject()
        assert isinstance(subject, SubjectProtocol)

    def test_mock_checker_is_invariant_checker_protocol(self):
        """MockChecker should pass isinstance check for InvariantCheckerProtocol."""
        checker = MockChecker()
        assert isinstance(checker, InvariantCheckerProtocol)


class TestMonitorLoopWithMockSubject:
    """Tests that MonitorLoop works with mock subject."""

    def test_monitor_loop_accepts_mock_subject(self, tmp_path):
        """MonitorLoop should accept any SubjectProtocol implementation."""
        subject = MockSubject()
        checker = MockChecker()
        db_path = tmp_path / "test.db"

        # Should not raise
        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        assert loop.subject is subject
        assert loop.checker is checker

    @pytest.mark.asyncio
    async def test_monitor_loop_calls_observe(self, tmp_path):
        """MonitorLoop should call subject.observe() during check cycle."""
        subject = MockSubject()
        checker = MockChecker()
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        # Run one check cycle manually
        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        assert subject.observe_call_count == 1

    @pytest.mark.asyncio
    async def test_monitor_loop_passes_observation_to_checker(self, tmp_path):
        """MonitorLoop should pass observation to checker.check()."""
        subject = MockSubject()
        checker = MockChecker()
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)

        assert checker.check_call_count == 1
        assert checker.last_observation == subject.observation_data

    @pytest.mark.asyncio
    async def test_monitor_loop_multiple_cycles(self, tmp_path):
        """MonitorLoop should call observe/check on each cycle."""
        subject = MockSubject()
        checker = MockChecker()
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            # Run multiple cycles
            await loop._check_cycle(db)
            await loop._check_cycle(db)
            await loop._check_cycle(db)

        assert subject.observe_call_count == 3
        assert checker.check_call_count == 3


class TestMonitorLoopWithViolations:
    """Tests MonitorLoop handling of violations from generic checker."""

    @pytest.mark.asyncio
    async def test_creates_ticket_for_violation(self, tmp_path):
        """MonitorLoop should create ticket when checker returns violation."""
        subject = MockSubject()
        violation = InvariantViolation(
            invariant_name="test_invariant",
            message="Test violation",
            first_seen=datetime.now(),
            last_seen=datetime.now(),
            store_id="node-1",
            severity="warning",
        )
        checker = MockChecker(violations=[violation])
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)
            # Check that ticket was created
            tickets = await db.list_tickets()
            assert len(tickets) >= 1
            assert tickets[0].invariant_name == "test_invariant"
            assert tickets[0].store_id == "node-1"

    @pytest.mark.asyncio
    async def test_creates_multiple_tickets_for_multiple_violations(self, tmp_path):
        """MonitorLoop should create tickets for all violations."""
        subject = MockSubject()
        now = datetime.now()
        violations = [
            InvariantViolation(
                invariant_name="invariant_a",
                message="Violation A",
                first_seen=now,
                last_seen=now,
                store_id="node-1",
                severity="warning",
            ),
            InvariantViolation(
                invariant_name="invariant_b",
                message="Violation B",
                first_seen=now,
                last_seen=now,
                store_id="node-2",
                severity="critical",
            ),
        ]
        checker = MockChecker(violations=violations)
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert len(tickets) == 2
            invariant_names = {t.invariant_name for t in tickets}
            assert invariant_names == {"invariant_a", "invariant_b"}

    @pytest.mark.asyncio
    async def test_no_tickets_when_no_violations(self, tmp_path):
        """MonitorLoop should not create tickets when no violations."""
        subject = MockSubject()
        checker = MockChecker(violations=[])  # No violations
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert len(tickets) == 0


class TestMonitorLoopAutoResolve:
    """Tests MonitorLoop auto-resolve functionality with generic checker."""

    @pytest.mark.asyncio
    async def test_auto_resolves_cleared_violations(self, tmp_path):
        """MonitorLoop should auto-resolve tickets when violations clear."""
        subject = MockSubject()
        now = datetime.now()
        violation = InvariantViolation(
            invariant_name="test_invariant",
            message="Test violation",
            first_seen=now,
            last_seen=now,
            store_id="node-1",
            severity="warning",
        )
        checker = MockChecker(violations=[violation])
        db_path = tmp_path / "test.db"

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB
        from operator_core.monitor.types import TicketStatus

        async with TicketDB(db_path) as db:
            # First cycle: violation present - creates ticket
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert len(tickets) == 1
            assert tickets[0].status == TicketStatus.OPEN

            # Clear the violation
            checker.violations = []

            # Second cycle: violation cleared - should auto-resolve
            await loop._check_cycle(db)
            tickets = await db.list_tickets()
            assert len(tickets) == 1
            assert tickets[0].status == TicketStatus.RESOLVED


class TestMonitorLoopSubjectAgnostic:
    """Tests proving MonitorLoop is truly subject-agnostic."""

    @pytest.mark.asyncio
    async def test_works_with_different_observation_structures(self, tmp_path):
        """MonitorLoop should work regardless of observation structure."""

        # Create a subject with completely different observation structure
        class DifferentSubject:
            async def observe(self) -> dict[str, Any]:
                return {
                    "services": [{"name": "api", "healthy": True}],
                    "latency_ms": 50,
                    "custom_field": "some_value",
                }

            def get_action_definitions(self):
                return []

        # Create a checker that understands this structure
        class DifferentChecker:
            def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
                violations = []
                for svc in observation.get("services", []):
                    if not svc.get("healthy", True):
                        violations.append(
                            InvariantViolation(
                                invariant_name="service_unhealthy",
                                message=f"Service {svc['name']} is unhealthy",
                                first_seen=datetime.now(),
                                last_seen=datetime.now(),
                                store_id=svc["name"],
                                severity="critical",
                            )
                        )
                return violations

        subject = DifferentSubject()
        checker = DifferentChecker()
        db_path = tmp_path / "test.db"

        # Both should be protocol compliant
        assert isinstance(subject, SubjectProtocol)
        assert isinstance(checker, InvariantCheckerProtocol)

        loop = MonitorLoop(
            subject=subject,
            checker=checker,
            db_path=db_path,
            interval_seconds=1.0,
        )

        from operator_core.db.tickets import TicketDB

        async with TicketDB(db_path) as db:
            # Should not raise - proves MonitorLoop is subject-agnostic
            await loop._check_cycle(db)

        # No tickets since all services are healthy
        async with TicketDB(db_path) as db:
            tickets = await db.list_tickets()
            assert len(tickets) == 0
