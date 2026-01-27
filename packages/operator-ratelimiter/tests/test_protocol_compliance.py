"""
Protocol compliance tests for operator-ratelimiter.

These tests verify that RateLimiterSubject and RateLimiterInvariantChecker
correctly implement the protocols defined in operator-protocols package.

Following the pattern established in operator-tikv/tests/test_protocol_compliance.py.
"""

import inspect
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest

from operator_protocols import (
    SubjectProtocol,
    InvariantCheckerProtocol,
    InvariantViolation,
)
from operator_ratelimiter.subject import RateLimiterSubject
from operator_ratelimiter.invariants import RateLimiterInvariantChecker
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient
from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.types import NodeInfo, CounterInfo


# =============================================================================
# Subject Protocol Compliance Tests
# =============================================================================


class TestSubjectProtocolCompliance:
    """Tests that RateLimiterSubject implements SubjectProtocol."""

    def test_subject_is_runtime_checkable(self):
        """RateLimiterSubject should pass isinstance check for SubjectProtocol."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_redis = MagicMock(spec=RedisClient)
        mock_prom = MagicMock(spec=PrometheusClient)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )

        # SubjectProtocol is runtime_checkable
        assert isinstance(subject, SubjectProtocol)

    def test_subject_has_observe_method(self):
        """RateLimiterSubject should have async observe() method."""
        assert hasattr(RateLimiterSubject, "observe")
        # Check it's a coroutine function
        assert inspect.iscoroutinefunction(RateLimiterSubject.observe)

    def test_subject_has_get_action_definitions_method(self):
        """RateLimiterSubject should have get_action_definitions() method."""
        assert hasattr(RateLimiterSubject, "get_action_definitions")
        assert callable(RateLimiterSubject.get_action_definitions)

    @pytest.mark.asyncio
    async def test_observe_returns_dict(self):
        """observe() should return dict[str, Any]."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_rl.get_nodes = AsyncMock(return_value=[])
        mock_rl.get_counters = AsyncMock(return_value=[])

        mock_redis = MagicMock(spec=RedisClient)
        mock_redis.ping = AsyncMock(return_value=True)

        mock_prom = MagicMock(spec=PrometheusClient)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )
        result = await subject.observe()

        assert isinstance(result, dict)

    def test_get_action_definitions_returns_list(self):
        """get_action_definitions() should return list."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_redis = MagicMock(spec=RedisClient)
        mock_prom = MagicMock(spec=PrometheusClient)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )

        result = subject.get_action_definitions()

        assert isinstance(result, list)
        assert len(result) > 0  # RateLimiter has reset_counter and update_limit


# =============================================================================
# Invariant Checker Protocol Compliance Tests
# =============================================================================


class TestInvariantCheckerProtocolCompliance:
    """Tests that RateLimiterInvariantChecker implements InvariantCheckerProtocol."""

    def test_checker_is_runtime_checkable(self):
        """RateLimiterInvariantChecker should pass isinstance check for InvariantCheckerProtocol."""
        checker = RateLimiterInvariantChecker()
        assert isinstance(checker, InvariantCheckerProtocol)

    def test_checker_has_check_method(self):
        """RateLimiterInvariantChecker should have check() method."""
        assert hasattr(RateLimiterInvariantChecker, "check")
        assert callable(RateLimiterInvariantChecker.check)

    def test_check_returns_list_of_violations(self):
        """check() should return list of InvariantViolation objects."""
        checker = RateLimiterInvariantChecker()
        observation = {
            "nodes": [],
            "counters": [],
            "node_metrics": {},
            "redis_connected": True,
        }
        result = checker.check(observation)
        assert isinstance(result, list)

    def test_check_returns_invariant_violation_instances(self):
        """check() violations should be InvariantViolation instances."""
        checker = RateLimiterInvariantChecker()
        observation = {
            "nodes": [],
            "counters": [],
            "node_metrics": {},
            "redis_connected": False,  # Trigger violation
        }
        result = checker.check(observation)
        assert len(result) > 0
        for violation in result:
            assert isinstance(violation, InvariantViolation)

    def test_check_with_healthy_observation(self):
        """check() should return empty list for healthy observation."""
        checker = RateLimiterInvariantChecker()
        observation = {
            "nodes": [
                {"id": "node1", "address": "localhost:8001", "state": "Up"},
                {"id": "node2", "address": "localhost:8002", "state": "Up"},
            ],
            "counters": [
                {"key": "user:1", "count": 5, "limit": 10, "remaining": 5},
            ],
            "node_metrics": {
                "node1": {"latency_p99_ms": 25.0},
                "node2": {"latency_p99_ms": 30.0},
            },
            "redis_connected": True,
        }

        result = checker.check(observation)

        assert isinstance(result, list)
        assert len(result) == 0

    def test_check_detects_violations(self):
        """check() should detect violations from observation dict."""
        checker = RateLimiterInvariantChecker()
        # Observation with a down node
        observation = {
            "nodes": [
                {"id": "node1", "address": "localhost:8001", "state": "Down"},
            ],
            "counters": [],
            "node_metrics": {},
            "redis_connected": True,
        }

        result = checker.check(observation)

        assert len(result) == 1
        assert result[0].invariant_name == "node_down"
        assert result[0].store_id == "node1"


# =============================================================================
# Observation Dict Structure Tests
# =============================================================================


class TestObservationDictStructure:
    """Tests for observation dictionary structure compatibility."""

    @pytest.mark.asyncio
    async def test_observe_returns_dict_with_expected_keys(self):
        """observe() should return dict with nodes, counters, node_metrics, redis_connected."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_rl.get_nodes = AsyncMock(return_value=[
            NodeInfo(id="n1", address="host:8001", state="Up", registered_at=datetime.now()),
        ])
        mock_rl.get_counters = AsyncMock(return_value=[
            CounterInfo(key="k1", count=1, limit=10, remaining=9),
        ])

        mock_redis = MagicMock(spec=RedisClient)
        mock_redis.ping = AsyncMock(return_value=True)

        mock_prom = MagicMock(spec=PrometheusClient)
        mock_prom.get_node_latency_p99 = AsyncMock(return_value=5.0)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )

        observation = await subject.observe()

        # Verify structure
        assert "nodes" in observation
        assert "counters" in observation
        assert "node_metrics" in observation
        assert "redis_connected" in observation

        # Verify types
        assert isinstance(observation["nodes"], list)
        assert isinstance(observation["counters"], list)
        assert isinstance(observation["node_metrics"], dict)
        assert isinstance(observation["redis_connected"], bool)

    @pytest.mark.asyncio
    async def test_observe_returns_expected_node_structure(self):
        """observe() nodes should have id, address, state keys."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_rl.get_nodes = AsyncMock(return_value=[
            NodeInfo(id="n1", address="host:8001", state="Up", registered_at=datetime.now()),
        ])
        mock_rl.get_counters = AsyncMock(return_value=[])

        mock_redis = MagicMock(spec=RedisClient)
        mock_redis.ping = AsyncMock(return_value=True)

        mock_prom = MagicMock(spec=PrometheusClient)
        mock_prom.get_node_latency_p99 = AsyncMock(return_value=5.0)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )

        observation = await subject.observe()

        assert len(observation["nodes"]) == 1
        node = observation["nodes"][0]
        assert "id" in node
        assert "address" in node
        assert "state" in node
        assert node["id"] == "n1"
        assert node["state"] == "Up"

    @pytest.mark.asyncio
    async def test_observe_returns_expected_counter_structure(self):
        """observe() counters should have key, count, limit, remaining keys."""
        mock_rl = MagicMock(spec=RateLimiterClient)
        mock_rl.get_nodes = AsyncMock(return_value=[])
        mock_rl.get_counters = AsyncMock(return_value=[
            CounterInfo(key="user:1", count=5, limit=10, remaining=5),
        ])

        mock_redis = MagicMock(spec=RedisClient)
        mock_redis.ping = AsyncMock(return_value=True)

        mock_prom = MagicMock(spec=PrometheusClient)

        subject = RateLimiterSubject(
            ratelimiter=mock_rl,
            redis=mock_redis,
            prom=mock_prom,
        )

        observation = await subject.observe()

        assert len(observation["counters"]) == 1
        counter = observation["counters"][0]
        assert "key" in counter
        assert "count" in counter
        assert "limit" in counter
        assert "remaining" in counter
        assert counter["key"] == "user:1"
        assert counter["count"] == 5

    def test_observation_can_be_passed_to_checker(self):
        """Observation from subject can be passed directly to checker."""
        # This is the key integration point - observation dict format must match
        observation = {
            "nodes": [{"id": "n1", "address": "host:8001", "state": "Up"}],
            "counters": [{"key": "k1", "count": 5, "limit": 10, "remaining": 5}],
            "node_metrics": {"n1": {"latency_p99_ms": 10.0}},
            "redis_connected": True,
        }

        checker = RateLimiterInvariantChecker()
        # Should not raise
        violations = checker.check(observation)
        assert isinstance(violations, list)


# =============================================================================
# InvariantViolation Tests
# =============================================================================


class TestInvariantViolationFromProtocols:
    """Tests that InvariantViolation comes from operator_protocols."""

    def test_invariant_violation_module(self):
        """InvariantViolation should be from operator_protocols."""
        assert InvariantViolation.__module__.startswith("operator_protocols")

    def test_invariant_violation_fields(self):
        """InvariantViolation should have required fields."""
        now = datetime.now()
        violation = InvariantViolation(
            invariant_name="test",
            message="test message",
            first_seen=now,
            last_seen=now,
            store_id="node1",
            severity="warning",
        )

        assert violation.invariant_name == "test"
        assert violation.message == "test message"
        assert violation.first_seen == now
        assert violation.last_seen == now
        assert violation.store_id == "node1"
        assert violation.severity == "warning"


# =============================================================================
# Protocol Runtime Checkable Tests
# =============================================================================


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
