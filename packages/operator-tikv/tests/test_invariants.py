"""
Tests for TiKV invariant checks.

These tests verify the InvariantChecker correctly:
- Detects store down violations (immediate, no grace period)
- Detects high latency violations (with grace period)
- Detects low disk space violations
- Respects grace periods (violations within grace period not reported)
- Clears violations when conditions resolve
"""

from datetime import datetime, timedelta

import pytest

from operator_core.types import Store, StoreMetrics
from operator_tikv.invariants import (
    HIGH_LATENCY_CONFIG,
    InvariantChecker,
    InvariantConfig,
    InvariantViolation,
    LOW_DISK_SPACE_CONFIG,
    STORE_DOWN_CONFIG,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def checker():
    """Create a fresh InvariantChecker for each test."""
    return InvariantChecker()


@pytest.fixture
def healthy_stores():
    """Sample healthy stores - all Up."""
    return [
        Store(id="1", address="tikv-0:20160", state="Up"),
        Store(id="2", address="tikv-1:20160", state="Up"),
        Store(id="3", address="tikv-2:20160", state="Up"),
    ]


@pytest.fixture
def stores_with_one_down():
    """Sample stores with one Down."""
    return [
        Store(id="1", address="tikv-0:20160", state="Up"),
        Store(id="2", address="tikv-1:20160", state="Down"),
        Store(id="3", address="tikv-2:20160", state="Up"),
    ]


@pytest.fixture
def healthy_metrics():
    """Sample healthy store metrics - low latency, low disk usage."""
    return StoreMetrics(
        store_id="1",
        qps=1000.0,
        latency_p99_ms=25.0,  # Well under 100ms threshold
        disk_used_bytes=30_000_000_000,  # 30GB
        disk_total_bytes=100_000_000_000,  # 100GB = 30% usage
        cpu_percent=40.0,
        raft_lag=0,
    )


@pytest.fixture
def high_latency_metrics():
    """Sample metrics with high latency."""
    return StoreMetrics(
        store_id="1",
        qps=1000.0,
        latency_p99_ms=150.0,  # Above 100ms threshold
        disk_used_bytes=30_000_000_000,
        disk_total_bytes=100_000_000_000,
        cpu_percent=40.0,
        raft_lag=0,
    )


@pytest.fixture
def low_disk_metrics():
    """Sample metrics with low disk space."""
    return StoreMetrics(
        store_id="1",
        qps=1000.0,
        latency_p99_ms=25.0,
        disk_used_bytes=80_000_000_000,  # 80GB
        disk_total_bytes=100_000_000_000,  # 100GB = 80% usage (above 70% threshold)
        cpu_percent=40.0,
        raft_lag=0,
    )


# =============================================================================
# Store Down Tests
# =============================================================================


class TestCheckStoresUp:
    """Tests for InvariantChecker.check_stores_up()."""

    def test_all_stores_up_returns_empty(self, checker, healthy_stores):
        """No violations when all stores are Up."""
        violations = checker.check_stores_up(healthy_stores)
        assert violations == []

    def test_store_down_returns_violation(self, checker, stores_with_one_down):
        """Returns violation when store is Down."""
        violations = checker.check_stores_up(stores_with_one_down)

        assert len(violations) == 1
        assert violations[0].invariant_name == "store_down"
        assert violations[0].store_id == "2"
        assert "Down" in violations[0].message
        assert violations[0].severity == "critical"

    def test_multiple_stores_down_returns_multiple_violations(self, checker):
        """Returns one violation per down store."""
        stores = [
            Store(id="1", address="tikv-0:20160", state="Down"),
            Store(id="2", address="tikv-1:20160", state="Offline"),
            Store(id="3", address="tikv-2:20160", state="Up"),
        ]

        violations = checker.check_stores_up(stores)

        assert len(violations) == 2
        store_ids = {v.store_id for v in violations}
        assert store_ids == {"1", "2"}

    def test_tombstone_state_is_violation(self, checker):
        """Tombstone state is also a violation (not Up)."""
        stores = [Store(id="1", address="tikv-0:20160", state="Tombstone")]

        violations = checker.check_stores_up(stores)

        assert len(violations) == 1
        assert "Tombstone" in violations[0].message

    def test_store_down_has_no_grace_period(self, checker, stores_with_one_down):
        """Store down is reported immediately (grace_period=0)."""
        # First check should report violation immediately
        violations = checker.check_stores_up(stores_with_one_down)
        assert len(violations) == 1

        # Verify default config has no grace period
        assert STORE_DOWN_CONFIG.grace_period == timedelta(seconds=0)

    def test_violation_clears_when_store_comes_up(self, checker):
        """Violation tracking clears when store returns to Up."""
        down_stores = [Store(id="1", address="tikv-0:20160", state="Down")]
        up_stores = [Store(id="1", address="tikv-0:20160", state="Up")]

        # First check - violation
        violations = checker.check_stores_up(down_stores)
        assert len(violations) == 1

        # Store comes back up
        violations = checker.check_stores_up(up_stores)
        assert len(violations) == 0

        # Verify internal state is cleared
        assert len(checker._first_seen) == 0


# =============================================================================
# High Latency Tests
# =============================================================================


class TestCheckLatency:
    """Tests for InvariantChecker.check_latency()."""

    def test_normal_latency_returns_none(self, checker, healthy_metrics):
        """No violation when latency is under threshold."""
        violation = checker.check_latency(healthy_metrics)
        assert violation is None

    def test_high_latency_within_grace_period_returns_none(
        self, checker, high_latency_metrics
    ):
        """Latency violation within grace period is not reported."""
        # First check - starts tracking but within grace period
        violation = checker.check_latency(high_latency_metrics)

        # With default 60s grace period, immediate check returns None
        assert violation is None

    def test_high_latency_after_grace_period_returns_violation(
        self, checker, high_latency_metrics
    ):
        """Latency violation is reported after grace period elapses."""
        # Use a very short grace period for testing
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(milliseconds=1),
            threshold=100.0,
            severity="warning",
        )

        # First check - starts tracking
        checker.check_latency(high_latency_metrics, config=config)

        # Wait for grace period (in real test this would use time.sleep or mock)
        # For this test, we'll manually set first_seen in the past
        key = checker._get_violation_key("high_latency", high_latency_metrics.store_id)
        checker._first_seen[key] = datetime.now() - timedelta(seconds=1)

        # Second check - grace period elapsed
        violation = checker.check_latency(high_latency_metrics, config=config)

        assert violation is not None
        assert violation.invariant_name == "high_latency"
        assert violation.store_id == "1"
        assert "150.0ms" in violation.message
        assert violation.severity == "warning"

    def test_latency_exactly_at_threshold_is_not_violation(self, checker):
        """Latency exactly at threshold is not a violation (> not >=)."""
        metrics = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=100.0,  # Exactly at threshold
            disk_used_bytes=30_000_000_000,
            disk_total_bytes=100_000_000_000,
            cpu_percent=40.0,
            raft_lag=0,
        )

        # Use no grace period to get immediate result
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        violation = checker.check_latency(metrics, config=config)
        assert violation is None

    def test_latency_clears_when_normalized(self, checker, high_latency_metrics):
        """Latency tracking clears when latency returns to normal."""
        healthy = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=50.0,  # Under threshold
            disk_used_bytes=30_000_000_000,
            disk_total_bytes=100_000_000_000,
            cpu_percent=40.0,
            raft_lag=0,
        )

        # First check - high latency
        checker.check_latency(high_latency_metrics)
        assert len(checker._first_seen) == 1

        # Latency normalizes
        checker.check_latency(healthy)
        assert len(checker._first_seen) == 0

    def test_default_latency_threshold_is_100ms(self):
        """Verify default latency threshold per CONTEXT.md."""
        assert HIGH_LATENCY_CONFIG.threshold == 100.0

    def test_default_latency_grace_period_is_60s(self):
        """Verify default latency grace period per CONTEXT.md."""
        assert HIGH_LATENCY_CONFIG.grace_period == timedelta(seconds=60)


# =============================================================================
# Low Disk Space Tests
# =============================================================================


class TestCheckDiskSpace:
    """Tests for InvariantChecker.check_disk_space()."""

    def test_healthy_disk_returns_none(self, checker, healthy_metrics):
        """No violation when disk usage is under threshold."""
        violation = checker.check_disk_space(healthy_metrics)
        assert violation is None

    def test_low_disk_returns_violation(self, checker, low_disk_metrics):
        """Returns violation when disk usage exceeds threshold."""
        violation = checker.check_disk_space(low_disk_metrics)

        assert violation is not None
        assert violation.invariant_name == "low_disk_space"
        assert violation.store_id == "1"
        assert "80.0%" in violation.message
        assert violation.severity == "warning"

    def test_disk_exactly_at_threshold_is_not_violation(self, checker):
        """Disk usage exactly at threshold is not a violation (> not >=)."""
        metrics = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=25.0,
            disk_used_bytes=70_000_000_000,  # 70GB
            disk_total_bytes=100_000_000_000,  # 100GB = exactly 70%
            cpu_percent=40.0,
            raft_lag=0,
        )

        violation = checker.check_disk_space(metrics)
        assert violation is None

    def test_zero_total_disk_returns_none(self, checker):
        """Zero total disk bytes returns None (can't calculate usage)."""
        metrics = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=25.0,
            disk_used_bytes=50_000_000_000,
            disk_total_bytes=0,  # Edge case
            cpu_percent=40.0,
            raft_lag=0,
        )

        violation = checker.check_disk_space(metrics)
        assert violation is None

    def test_default_disk_threshold_is_70_percent(self):
        """Verify default disk threshold per CONTEXT.md."""
        assert LOW_DISK_SPACE_CONFIG.threshold == 70.0

    def test_disk_has_no_grace_period(self):
        """Disk space issues are reported immediately."""
        assert LOW_DISK_SPACE_CONFIG.grace_period == timedelta(seconds=0)


# =============================================================================
# Grace Period Logic Tests
# =============================================================================


class TestGracePeriodLogic:
    """Tests for grace period tracking across invariants."""

    def test_different_stores_tracked_separately(self, checker):
        """Each store has independent grace period tracking."""
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        metrics_1 = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=150.0,
            disk_used_bytes=30_000_000_000,
            disk_total_bytes=100_000_000_000,
            cpu_percent=40.0,
            raft_lag=0,
        )

        metrics_2 = StoreMetrics(
            store_id="2",
            qps=1000.0,
            latency_p99_ms=150.0,
            disk_used_bytes=30_000_000_000,
            disk_total_bytes=100_000_000_000,
            cpu_percent=40.0,
            raft_lag=0,
        )

        # Both stores have violations
        v1 = checker.check_latency(metrics_1, config=config)
        v2 = checker.check_latency(metrics_2, config=config)

        assert v1 is not None and v1.store_id == "1"
        assert v2 is not None and v2.store_id == "2"

    def test_first_seen_time_preserved_across_checks(self, checker):
        """First seen time is preserved when violation persists."""
        config = InvariantConfig(
            name="high_latency",
            grace_period=timedelta(seconds=0),
            threshold=100.0,
        )

        metrics = StoreMetrics(
            store_id="1",
            qps=1000.0,
            latency_p99_ms=150.0,
            disk_used_bytes=30_000_000_000,
            disk_total_bytes=100_000_000_000,
            cpu_percent=40.0,
            raft_lag=0,
        )

        # First check
        v1 = checker.check_latency(metrics, config=config)
        first_seen_1 = v1.first_seen

        # Second check - first_seen should be same
        v2 = checker.check_latency(metrics, config=config)
        first_seen_2 = v2.first_seen

        assert first_seen_1 == first_seen_2

    def test_clear_state_removes_all_tracking(self, checker, stores_with_one_down):
        """clear_state() removes all tracking data."""
        # Create some violations
        checker.check_stores_up(stores_with_one_down)
        assert len(checker._first_seen) > 0

        # Clear state
        checker.clear_state()

        assert len(checker._first_seen) == 0


# =============================================================================
# InvariantViolation Tests
# =============================================================================


class TestInvariantViolation:
    """Tests for InvariantViolation dataclass."""

    def test_violation_has_required_fields(self):
        """InvariantViolation has all required fields."""
        now = datetime.now()
        violation = InvariantViolation(
            invariant_name="test",
            message="test message",
            first_seen=now,
            last_seen=now,
        )

        assert violation.invariant_name == "test"
        assert violation.message == "test message"
        assert violation.first_seen == now
        assert violation.last_seen == now
        assert violation.store_id is None  # Optional
        assert violation.severity == "warning"  # Default

    def test_violation_with_store_id(self):
        """InvariantViolation can include store_id."""
        now = datetime.now()
        violation = InvariantViolation(
            invariant_name="test",
            message="test message",
            first_seen=now,
            last_seen=now,
            store_id="42",
            severity="critical",
        )

        assert violation.store_id == "42"
        assert violation.severity == "critical"
