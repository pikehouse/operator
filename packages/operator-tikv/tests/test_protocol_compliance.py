"""
Protocol compliance tests for TiKV subject.

Verifies that TiKVSubject and TiKVInvariantChecker correctly implement
the generic protocols from operator-protocols package.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from operator_protocols import (
    SubjectProtocol,
    InvariantCheckerProtocol,
    InvariantViolation,
)
from operator_tikv.subject import TiKVSubject
from operator_tikv.invariants import TiKVInvariantChecker


class TestTiKVSubjectProtocolCompliance:
    """Tests that TiKVSubject implements SubjectProtocol."""

    def test_tikv_subject_is_subject_protocol(self):
        """TiKVSubject should pass isinstance check for SubjectProtocol."""
        # Create with mocked dependencies
        mock_pd = MagicMock()
        mock_prom = MagicMock()
        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)

        assert isinstance(subject, SubjectProtocol)

    def test_tikv_subject_has_observe_method(self):
        """TiKVSubject should have async observe() method."""
        mock_pd = MagicMock()
        mock_prom = MagicMock()
        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)

        assert hasattr(subject, "observe")
        assert callable(subject.observe)

    def test_tikv_subject_has_get_action_definitions_method(self):
        """TiKVSubject should have get_action_definitions() method."""
        mock_pd = MagicMock()
        mock_prom = MagicMock()
        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)

        assert hasattr(subject, "get_action_definitions")
        assert callable(subject.get_action_definitions)

    @pytest.mark.asyncio
    async def test_observe_returns_dict(self):
        """observe() should return dict[str, Any]."""
        mock_pd = AsyncMock()
        mock_pd.get_stores.return_value = []
        mock_prom = AsyncMock()

        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)
        result = await subject.observe()

        assert isinstance(result, dict)
        assert "stores" in result

    @pytest.mark.asyncio
    async def test_observe_returns_expected_structure(self):
        """observe() should return dict with stores, cluster_metrics, store_metrics."""
        mock_pd = AsyncMock()
        mock_pd.get_stores.return_value = []
        mock_pd.get_regions.return_value = []
        mock_prom = AsyncMock()

        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)
        result = await subject.observe()

        assert isinstance(result, dict)
        assert "stores" in result
        assert "cluster_metrics" in result
        assert "store_metrics" in result

    def test_get_action_definitions_returns_list(self):
        """get_action_definitions() should return list."""
        mock_pd = MagicMock()
        mock_prom = MagicMock()
        subject = TiKVSubject(pd=mock_pd, prom=mock_prom)

        result = subject.get_action_definitions()

        assert isinstance(result, list)
        assert len(result) > 0  # TiKV has several actions


class TestTiKVInvariantCheckerProtocolCompliance:
    """Tests that TiKVInvariantChecker implements InvariantCheckerProtocol."""

    def test_tikv_checker_is_invariant_checker_protocol(self):
        """TiKVInvariantChecker should pass isinstance check."""
        checker = TiKVInvariantChecker()

        assert isinstance(checker, InvariantCheckerProtocol)

    def test_tikv_checker_has_check_method(self):
        """TiKVInvariantChecker should have check() method."""
        checker = TiKVInvariantChecker()

        assert hasattr(checker, "check")
        assert callable(checker.check)

    def test_check_returns_list_of_violations(self):
        """check() should return list[InvariantViolation]."""
        checker = TiKVInvariantChecker()
        observation = {"stores": [], "store_metrics": {}}

        result = checker.check(observation)

        assert isinstance(result, list)
        # All items should be InvariantViolation (if any)
        for item in result:
            assert isinstance(item, InvariantViolation)

    def test_check_detects_violations(self):
        """check() should detect violations from observation dict."""
        checker = TiKVInvariantChecker()
        # Observation with a down store
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-0:20160", "state": "Down"},
            ],
            "store_metrics": {},
        }

        result = checker.check(observation)

        assert len(result) == 1
        assert result[0].invariant_name == "store_down"
        assert result[0].store_id == "1"

    def test_check_with_healthy_observation(self):
        """check() should return empty list for healthy observation."""
        checker = TiKVInvariantChecker()
        # Healthy observation
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-0:20160", "state": "Up"},
                {"id": "2", "address": "tikv-1:20160", "state": "Up"},
            ],
            "store_metrics": {
                "1": {
                    "qps": 1000.0,
                    "latency_p99_ms": 25.0,  # Under threshold
                    "disk_used_bytes": 30_000_000_000,
                    "disk_total_bytes": 100_000_000_000,  # 30% usage
                    "cpu_percent": 40.0,
                    "raft_lag": 0,
                },
            },
        }

        result = checker.check(observation)

        assert isinstance(result, list)
        assert len(result) == 0


class TestInvariantViolationFromProtocols:
    """Tests that InvariantViolation comes from operator_protocols."""

    def test_invariant_violation_module(self):
        """InvariantViolation should be from operator_protocols."""
        assert InvariantViolation.__module__.startswith("operator_protocols")

    def test_invariant_violation_fields(self):
        """InvariantViolation should have required fields."""
        from datetime import datetime

        now = datetime.now()
        violation = InvariantViolation(
            invariant_name="test",
            message="test message",
            first_seen=now,
            last_seen=now,
            store_id="1",
            severity="warning",
        )

        assert violation.invariant_name == "test"
        assert violation.message == "test message"
        assert violation.first_seen == now
        assert violation.last_seen == now
        assert violation.store_id == "1"
        assert violation.severity == "warning"


class TestProtocolRuntimeCheckable:
    """Tests that protocols are runtime checkable."""

    def test_subject_protocol_is_runtime_checkable(self):
        """SubjectProtocol should be runtime checkable."""
        # Non-subject object should fail isinstance check
        assert not isinstance({}, SubjectProtocol)
        assert not isinstance("string", SubjectProtocol)
        assert not isinstance(123, SubjectProtocol)

    def test_invariant_checker_protocol_is_runtime_checkable(self):
        """InvariantCheckerProtocol should be runtime checkable."""
        # Non-checker object should fail isinstance check
        assert not isinstance({}, InvariantCheckerProtocol)
        assert not isinstance("string", InvariantCheckerProtocol)
        assert not isinstance(123, InvariantCheckerProtocol)
