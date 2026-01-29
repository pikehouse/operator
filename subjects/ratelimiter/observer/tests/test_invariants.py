"""
Tests for RateLimiterInvariantChecker.

These tests verify the InvariantChecker correctly:
- Detects node down violations (immediate, no grace period)
- Detects redis disconnected violations (immediate)
- Detects high latency violations (with grace period)
- Detects counter drift violations (with grace period)
- Detects ghost allowing violations (immediate)
- Respects grace periods (violations within grace period not reported)
- Clears violations when conditions resolve
"""

from datetime import datetime, timedelta

import pytest

from ratelimiter_observer.invariants import (
    RateLimiterInvariantChecker,
    InvariantConfig,
    NODE_DOWN_CONFIG,
    REDIS_DISCONNECTED_CONFIG,
    HIGH_LATENCY_CONFIG,
    COUNTER_DRIFT_CONFIG,
    GHOST_ALLOWING_CONFIG,
)
from ratelimiter_observer.types import NodeInfo, CounterInfo


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def checker():
    """Create a fresh checker for each test."""
    return RateLimiterInvariantChecker()


@pytest.fixture
def healthy_observation():
    """Baseline healthy observation."""
    return {
        "nodes": [
            {"id": "node1", "address": "localhost:8001", "state": "Up"},
            {"id": "node2", "address": "localhost:8002", "state": "Up"},
        ],
        "counters": [
            {"key": "user:1", "count": 5, "limit": 10, "remaining": 5},
        ],
        "node_metrics": {
            "node1": {"latency_p99_ms": 10.0},
            "node2": {"latency_p99_ms": 15.0},
        },
        "redis_connected": True,
    }


@pytest.fixture
def healthy_nodes():
    """Sample healthy nodes - all Up."""
    return [
        NodeInfo(id="node1", address="localhost:8001", state="Up"),
        NodeInfo(id="node2", address="localhost:8002", state="Up"),
    ]


@pytest.fixture
def nodes_with_one_down():
    """Sample nodes with one Down."""
    return [
        NodeInfo(id="node1", address="localhost:8001", state="Up"),
        NodeInfo(id="node2", address="localhost:8002", state="Down"),
    ]


# =============================================================================
# Node Down Tests (MON-01)
# =============================================================================


class TestNodeDown:
    """Tests for node_down invariant (MON-01)."""

    def test_no_violation_when_all_up(self, checker, healthy_observation):
        """No violation when all nodes are Up."""
        violations = checker.check(healthy_observation)
        assert not any(v.invariant_name == "node_down" for v in violations)

    def test_violation_when_node_down(self, checker, healthy_observation):
        """Violation when node is Down."""
        healthy_observation["nodes"][0]["state"] = "Down"
        violations = checker.check(healthy_observation)
        node_down = [v for v in violations if v.invariant_name == "node_down"]
        assert len(node_down) == 1
        assert "node1" in node_down[0].message
        assert node_down[0].severity == "critical"

    def test_clears_when_node_recovers(self, checker, healthy_observation):
        """Violation clears when node comes back up."""
        healthy_observation["nodes"][0]["state"] = "Down"
        checker.check(healthy_observation)  # Record violation

        healthy_observation["nodes"][0]["state"] = "Up"
        violations = checker.check(healthy_observation)
        assert not any(v.invariant_name == "node_down" for v in violations)

    def test_multiple_nodes_down_returns_multiple_violations(self, checker):
        """Returns one violation per down node."""
        observation = {
            "nodes": [
                {"id": "node1", "address": "localhost:8001", "state": "Down"},
                {"id": "node2", "address": "localhost:8002", "state": "Down"},
                {"id": "node3", "address": "localhost:8003", "state": "Up"},
            ],
            "counters": [],
            "node_metrics": {},
            "redis_connected": True,
        }

        violations = checker.check(observation)
        node_down = [v for v in violations if v.invariant_name == "node_down"]
        assert len(node_down) == 2
        store_ids = {v.store_id for v in node_down}
        assert store_ids == {"node1", "node2"}

    def test_node_down_has_no_grace_period(self, checker, healthy_nodes):
        """Node down is reported immediately (grace_period=0)."""
        down_nodes = [NodeInfo(id="n1", address="host:8001", state="Down")]

        # First check should report violation immediately
        violations = checker.check_nodes_up(down_nodes)
        assert len(violations) == 1

        # Verify default config has no grace period
        assert NODE_DOWN_CONFIG.grace_period == timedelta(seconds=0)

    def test_check_nodes_up_method(self, checker, healthy_nodes, nodes_with_one_down):
        """Test check_nodes_up() method directly."""
        # All up - no violations
        violations = checker.check_nodes_up(healthy_nodes)
        assert len(violations) == 0

        # One down - violation
        violations = checker.check_nodes_up(nodes_with_one_down)
        assert len(violations) == 1
        assert violations[0].store_id == "node2"


# =============================================================================
# Redis Disconnected Tests (MON-02)
# =============================================================================


class TestRedisDisconnected:
    """Tests for redis_disconnected invariant (MON-02)."""

    def test_no_violation_when_connected(self, checker, healthy_observation):
        """No violation when Redis is connected."""
        violations = checker.check(healthy_observation)
        assert not any(v.invariant_name == "redis_disconnected" for v in violations)

    def test_violation_when_disconnected(self, checker, healthy_observation):
        """Violation when Redis is disconnected."""
        healthy_observation["redis_connected"] = False
        violations = checker.check(healthy_observation)
        redis_down = [v for v in violations if v.invariant_name == "redis_disconnected"]
        assert len(redis_down) == 1
        assert redis_down[0].severity == "critical"

    def test_redis_disconnected_has_no_grace_period(self):
        """Redis disconnected is reported immediately."""
        assert REDIS_DISCONNECTED_CONFIG.grace_period == timedelta(seconds=0)

    def test_clears_when_reconnected(self, checker, healthy_observation):
        """Violation clears when Redis reconnects."""
        healthy_observation["redis_connected"] = False
        checker.check(healthy_observation)  # Record violation
        assert len(checker._first_seen) > 0

        healthy_observation["redis_connected"] = True
        violations = checker.check(healthy_observation)
        assert not any(v.invariant_name == "redis_disconnected" for v in violations)

    def test_check_redis_connectivity_method(self, checker):
        """Test check_redis_connectivity() method directly."""
        # Connected - no violations
        violations = checker.check_redis_connectivity(True)
        assert len(violations) == 0

        # Disconnected - violation
        violations = checker.check_redis_connectivity(False)
        assert len(violations) == 1
        assert violations[0].invariant_name == "redis_disconnected"


# =============================================================================
# High Latency Tests (MON-03)
# =============================================================================


class TestHighLatency:
    """Tests for high_latency invariant (MON-03)."""

    def test_no_violation_below_threshold(self, checker, healthy_observation):
        """No violation when latency is below threshold."""
        violations = checker.check(healthy_observation)
        assert not any(v.invariant_name == "high_latency" for v in violations)

    def test_no_immediate_violation_above_threshold(self, checker, healthy_observation):
        """No immediate violation due to grace period."""
        healthy_observation["node_metrics"]["node1"]["latency_p99_ms"] = 150.0
        violations = checker.check(healthy_observation)
        # Should not fire immediately due to grace period
        assert not any(v.invariant_name == "high_latency" for v in violations)

    def test_violation_after_grace_period(self, checker, healthy_observation):
        """Violation after grace period elapses."""
        healthy_observation["node_metrics"]["node1"]["latency_p99_ms"] = 150.0

        # First check - starts grace period
        checker.check(healthy_observation)

        # Manually expire grace period for testing
        key = checker._get_violation_key("high_latency", "node1")
        checker._first_seen[key] = datetime.now() - HIGH_LATENCY_CONFIG.grace_period - timedelta(seconds=1)

        # Second check - should fire
        violations = checker.check(healthy_observation)
        high_latency = [v for v in violations if v.invariant_name == "high_latency"]
        assert len(high_latency) == 1
        assert "node1" in high_latency[0].message

    def test_default_latency_threshold_is_100ms(self):
        """Verify default latency threshold."""
        assert HIGH_LATENCY_CONFIG.threshold == 100.0

    def test_default_latency_grace_period_is_60s(self):
        """Verify default latency grace period."""
        assert HIGH_LATENCY_CONFIG.grace_period == timedelta(seconds=60)

    def test_latency_exactly_at_threshold_is_not_violation(self, checker):
        """Latency exactly at threshold is not a violation (> not >=)."""
        # Use no grace period config
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        # Exactly at threshold - should not fire
        violation = checker.check_latency("node1", 100.0, config=config)
        assert violation is None

        # Just above threshold - should fire
        violation = checker.check_latency("node1", 100.1, config=config)
        assert violation is not None

    def test_latency_clears_when_normalized(self, checker):
        """Latency tracking clears when latency returns to normal."""
        # Start with high latency (within grace period)
        checker.check_latency("node1", 150.0)
        assert len(checker._first_seen) == 1

        # Latency normalizes
        checker.check_latency("node1", 50.0)
        assert len(checker._first_seen) == 0

    def test_check_latency_method(self, checker):
        """Test check_latency() method directly with no grace period."""
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        # Normal latency
        violation = checker.check_latency("node1", 50.0, config=config)
        assert violation is None

        # High latency
        violation = checker.check_latency("node1", 150.0, config=config)
        assert violation is not None
        assert "150.0ms" in violation.message


# =============================================================================
# Counter Drift Tests (MON-04)
# =============================================================================


class TestCounterDrift:
    """Tests for counter_drift invariant (MON-04)."""

    def test_default_counter_drift_threshold_is_5(self):
        """Verify default counter drift threshold."""
        assert COUNTER_DRIFT_CONFIG.threshold == 5.0

    def test_default_counter_drift_grace_period_is_30s(self):
        """Verify default counter drift grace period."""
        assert COUNTER_DRIFT_CONFIG.grace_period == timedelta(seconds=30)

    def test_no_drift_within_threshold(self, checker):
        """No violation when drift is within threshold."""
        counter = CounterInfo(key="user:1", count=10, limit=100, remaining=90)
        redis_count = 12  # Drift of 2, within threshold of 5

        violation = checker.check_counter_drift(counter, redis_count)
        assert violation is None

    def test_drift_exceeds_threshold_starts_grace_period(self, checker):
        """Drift above threshold starts grace period."""
        counter = CounterInfo(key="user:1", count=10, limit=100, remaining=90)
        redis_count = 20  # Drift of 10, above threshold of 5

        # First check - starts grace period
        violation = checker.check_counter_drift(counter, redis_count)
        # With default 30s grace period, should not fire immediately
        assert violation is None
        assert len(checker._first_seen) == 1

    def test_drift_exceeds_threshold_after_grace_period(self, checker):
        """Drift fires after grace period elapses."""
        counter = CounterInfo(key="user:1", count=10, limit=100, remaining=90)
        redis_count = 20  # Drift of 10, above threshold of 5

        # First check - starts grace period
        checker.check_counter_drift(counter, redis_count)

        # Manually expire grace period
        key = checker._get_violation_key("counter_drift", counter.key)
        checker._first_seen[key] = datetime.now() - COUNTER_DRIFT_CONFIG.grace_period - timedelta(seconds=1)

        # Second check - should fire
        violation = checker.check_counter_drift(counter, redis_count)
        assert violation is not None
        assert "user:1" in violation.message
        assert "drift=10" in violation.message

    def test_drift_clears_when_resolved(self, checker):
        """Drift tracking clears when drift resolves."""
        counter = CounterInfo(key="user:1", count=10, limit=100, remaining=90)

        # Start tracking drift
        checker.check_counter_drift(counter, 20)
        assert len(checker._first_seen) == 1

        # Drift resolves (counts match)
        checker.check_counter_drift(counter, 10)
        assert len(checker._first_seen) == 0


# =============================================================================
# Ghost Allowing Tests (MON-05)
# =============================================================================


class TestGhostAllowing:
    """Tests for ghost_allowing invariant (MON-05)."""

    def test_no_violation_when_count_at_limit(self, checker, healthy_observation):
        """No violation when count equals limit."""
        healthy_observation["counters"][0]["count"] = 10
        healthy_observation["counters"][0]["limit"] = 10
        healthy_observation["counters"][0]["remaining"] = 0
        violations = checker.check(healthy_observation)
        ghost = [v for v in violations if v.invariant_name == "ghost_allowing"]
        assert len(ghost) == 0

    def test_no_violation_normal_operation(self, checker, healthy_observation):
        """No violation during normal rate limiting."""
        # Normal: limit=10, count=5, remaining=5
        violations = checker.check(healthy_observation)
        ghost = [v for v in violations if v.invariant_name == "ghost_allowing"]
        assert len(ghost) == 0

    def test_violation_when_limit_zero_and_remaining(self, checker, healthy_observation):
        """Violation when limit=0 but remaining > 0 (ghost allowing)."""
        healthy_observation["counters"][0]["limit"] = 0
        healthy_observation["counters"][0]["remaining"] = 5  # Still allowing
        violations = checker.check(healthy_observation)
        ghost = [v for v in violations if v.invariant_name == "ghost_allowing"]
        assert len(ghost) == 1
        assert "ghost allowing" in ghost[0].message.lower()

    def test_ghost_allowing_has_no_grace_period(self):
        """Ghost allowing is reported immediately."""
        assert GHOST_ALLOWING_CONFIG.grace_period == timedelta(seconds=0)

    def test_ghost_clears_when_resolved(self, checker, healthy_observation):
        """Ghost tracking clears when issue resolves."""
        # Create ghost allowing condition
        healthy_observation["counters"][0]["limit"] = 0
        healthy_observation["counters"][0]["remaining"] = 5
        checker.check(healthy_observation)

        # Fix the issue (set proper limit)
        healthy_observation["counters"][0]["limit"] = 10
        healthy_observation["counters"][0]["remaining"] = 5
        violations = checker.check(healthy_observation)
        ghost = [v for v in violations if v.invariant_name == "ghost_allowing"]
        assert len(ghost) == 0


# =============================================================================
# Clear State Tests
# =============================================================================


class TestClearState:
    """Tests for clear_state() method."""

    def test_clear_state_resets_tracking(self, checker, healthy_observation):
        """clear_state() should reset violation tracking."""
        # Create a violation
        healthy_observation["nodes"][0]["state"] = "Down"
        checker.check(healthy_observation)
        assert len(checker._first_seen) > 0

        # Clear state
        checker.clear_state()
        assert len(checker._first_seen) == 0


# =============================================================================
# Grace Period Logic Tests
# =============================================================================


class TestGracePeriodLogic:
    """Tests for grace period tracking across invariants."""

    def test_different_nodes_tracked_separately(self, checker):
        """Each node has independent grace period tracking."""
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        # Both nodes have high latency
        v1 = checker.check_latency("node1", 150.0, config=config)
        v2 = checker.check_latency("node2", 160.0, config=config)

        assert v1 is not None and v1.store_id == "node1"
        assert v2 is not None and v2.store_id == "node2"

    def test_first_seen_time_preserved_across_checks(self, checker):
        """First seen time is preserved when violation persists."""
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        # First check
        v1 = checker.check_latency("node1", 150.0, config=config)
        first_seen_1 = v1.first_seen

        # Second check - first_seen should be same
        v2 = checker.check_latency("node1", 150.0, config=config)
        first_seen_2 = v2.first_seen

        assert first_seen_1 == first_seen_2


# =============================================================================
# InvariantConfig Tests
# =============================================================================


class TestInvariantConfig:
    """Tests for InvariantConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = InvariantConfig(name="test")
        assert config.grace_period == timedelta(seconds=0)
        assert config.threshold == 0.0
        assert config.severity == "warning"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = InvariantConfig(
            name="custom",
            grace_period=timedelta(seconds=30),
            threshold=50.0,
            severity="critical",
        )
        assert config.grace_period == timedelta(seconds=30)
        assert config.threshold == 50.0
        assert config.severity == "critical"
