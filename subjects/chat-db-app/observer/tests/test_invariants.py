"""
Tests for ChatDBAppInvariantChecker.

Uses mock observation dicts to verify invariant detection logic
including grace periods and violation clearing.
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

import pytest

from chat_db_app_observer.invariants import (
    DB_UNREACHABLE_CONFIG,
    HIGH_ERROR_RATE_CONFIG,
    HIGH_LATENCY_CONFIG,
    IDLE_IN_TRANSACTION_CONFIG,
    LOCK_CONTENTION_CONFIG,
    POOL_EXHAUSTION_CONFIG,
    ChatDBAppInvariantChecker,
)


def _make_observation(
    *,
    pool_total: int = 5,
    pool_max: int = 20,
    pool_waiting: int = 0,
    pool_active: int = 3,
    pool_idle: int = 2,
    db_reachable: bool = True,
    active_connections: int = 5,
    max_connections: int = 100,
    idle_in_transaction: int = 0,
    waiting_on_lock: int = 0,
    long_running_queries: list | None = None,
    deadlocks_total: int = 0,
    latency_p99_ms: float = 10.0,
    latency_p50_ms: float = 5.0,
    requests_per_sec: float = 100.0,
    error_count_5xx: int = 0,
    app_status: str = "Up",
    error_rate_pct: float = 0.0,
    uptime_seconds: float = 3600.0,
) -> dict:
    """Build a complete observation dict for testing."""
    return {
        "app": {
            "status": app_status,
            "uptime_seconds": uptime_seconds,
            "error_rate_pct": error_rate_pct,
        },
        "connection_pool": {
            "active": pool_active,
            "idle": pool_idle,
            "waiting": pool_waiting,
            "total": pool_total,
            "max_size": pool_max,
        },
        "database": {
            "reachable": db_reachable,
            "active_connections": active_connections,
            "max_connections": max_connections,
            "idle_in_transaction": idle_in_transaction,
            "waiting_on_lock": waiting_on_lock,
            "long_running_queries": long_running_queries or [],
            "deadlocks_total": deadlocks_total,
        },
        "endpoint_metrics": {
            "latency_p99_ms": latency_p99_ms,
            "latency_p50_ms": latency_p50_ms,
            "requests_per_sec": requests_per_sec,
            "error_count_5xx": error_count_5xx,
        },
    }


class TestHealthySystem:
    """Tests that a healthy system produces no violations."""

    def test_no_violations_when_healthy(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation()
        violations = checker.check(obs)
        assert violations == []

    def test_low_pool_usage_no_violation(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(pool_total=5, pool_max=20)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "pool_exhaustion" for v in violations)


class TestPoolExhaustion:
    """Tests for pool_exhaustion invariant."""

    def test_waiting_connections_triggers(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(pool_waiting=3, pool_total=20, pool_max=20)
        # First check within grace period
        violations = checker.check(obs)
        assert not any(v.invariant_name == "pool_exhaustion" for v in violations)

        # Simulate time passing beyond grace period (30s)
        checker._first_seen["pool_exhaustion"] = checker._first_seen[
            "pool_exhaustion"
        ] - timedelta(seconds=31)
        violations = checker.check(obs)
        pool_violations = [v for v in violations if v.invariant_name == "pool_exhaustion"]
        assert len(pool_violations) == 1
        assert pool_violations[0].severity == "critical"

    def test_high_utilization_triggers(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(pool_total=19, pool_max=20, pool_waiting=0)
        # 95% utilization > 90% threshold
        checker.check(obs)
        checker._first_seen["pool_exhaustion"] = checker._first_seen[
            "pool_exhaustion"
        ] - timedelta(seconds=31)
        violations = checker.check(obs)
        assert any(v.invariant_name == "pool_exhaustion" for v in violations)

    def test_clears_when_resolved(self):
        checker = ChatDBAppInvariantChecker()
        # Trigger violation
        obs_bad = _make_observation(pool_waiting=5, pool_total=20, pool_max=20)
        checker.check(obs_bad)

        # Resolve
        obs_good = _make_observation(pool_waiting=0, pool_total=5, pool_max=20)
        violations = checker.check(obs_good)
        assert not any(v.invariant_name == "pool_exhaustion" for v in violations)
        assert "pool_exhaustion" not in checker._first_seen


class TestDbUnreachable:
    """Tests for db_unreachable invariant."""

    def test_triggers_immediately(self):
        """db_unreachable has 0 grace period."""
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(db_reachable=False)
        violations = checker.check(obs)
        db_violations = [v for v in violations if v.invariant_name == "db_unreachable"]
        assert len(db_violations) == 1
        assert db_violations[0].severity == "critical"

    def test_clears_when_reachable(self):
        checker = ChatDBAppInvariantChecker()
        obs_bad = _make_observation(db_reachable=False)
        checker.check(obs_bad)

        obs_good = _make_observation(db_reachable=True)
        violations = checker.check(obs_good)
        assert not any(v.invariant_name == "db_unreachable" for v in violations)


class TestIdleInTransaction:
    """Tests for idle_in_transaction invariant."""

    def test_below_threshold_no_violation(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(idle_in_transaction=2)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "idle_in_transaction" for v in violations)

    def test_above_threshold_with_grace(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(idle_in_transaction=5)

        # First check: within grace period (60s)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "idle_in_transaction" for v in violations)

        # After grace period
        checker._first_seen["idle_in_transaction"] = checker._first_seen[
            "idle_in_transaction"
        ] - timedelta(seconds=61)
        violations = checker.check(obs)
        assert any(v.invariant_name == "idle_in_transaction" for v in violations)


class TestLockContention:
    """Tests for lock_contention invariant."""

    def test_below_threshold_no_violation(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(waiting_on_lock=3)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "lock_contention" for v in violations)

    def test_above_threshold_with_grace(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(waiting_on_lock=8)

        # First check: within grace period (15s)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "lock_contention" for v in violations)

        # After grace period
        checker._first_seen["lock_contention"] = checker._first_seen[
            "lock_contention"
        ] - timedelta(seconds=16)
        violations = checker.check(obs)
        lock_violations = [v for v in violations if v.invariant_name == "lock_contention"]
        assert len(lock_violations) == 1
        assert lock_violations[0].severity == "warning"


class TestHighLatency:
    """Tests for high_latency invariant."""

    def test_normal_latency_no_violation(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(latency_p99_ms=50.0)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "high_latency" for v in violations)

    def test_high_latency_with_grace(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(latency_p99_ms=800.0)

        # First check: within grace period (60s)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "high_latency" for v in violations)

        # After grace period
        checker._first_seen["high_latency"] = checker._first_seen[
            "high_latency"
        ] - timedelta(seconds=61)
        violations = checker.check(obs)
        assert any(v.invariant_name == "high_latency" for v in violations)


class TestHighErrorRate:
    """Tests for high_error_rate invariant."""

    def test_low_error_rate_no_violation(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(error_rate_pct=1.0)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "high_error_rate" for v in violations)

    def test_high_error_rate_with_grace(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(error_rate_pct=10.0)

        # First check: within grace period (30s)
        violations = checker.check(obs)
        assert not any(v.invariant_name == "high_error_rate" for v in violations)

        # After grace period
        checker._first_seen["high_error_rate"] = checker._first_seen[
            "high_error_rate"
        ] - timedelta(seconds=31)
        violations = checker.check(obs)
        error_violations = [v for v in violations if v.invariant_name == "high_error_rate"]
        assert len(error_violations) == 1
        assert error_violations[0].severity == "critical"


class TestClearState:
    """Tests for clear_state method."""

    def test_clear_state_resets_tracking(self):
        checker = ChatDBAppInvariantChecker()
        obs = _make_observation(db_reachable=False)
        checker.check(obs)
        assert len(checker._first_seen) > 0

        checker.clear_state()
        assert len(checker._first_seen) == 0


class TestMultipleViolations:
    """Tests for multiple simultaneous violations."""

    def test_multiple_violations_detected(self):
        checker = ChatDBAppInvariantChecker()
        # Everything is broken
        obs = _make_observation(
            db_reachable=False,
            pool_waiting=5,
            idle_in_transaction=10,
            waiting_on_lock=10,
            latency_p99_ms=1000.0,
            error_rate_pct=20.0,
        )

        # db_unreachable fires immediately (0 grace)
        violations = checker.check(obs)
        assert any(v.invariant_name == "db_unreachable" for v in violations)

        # Fast-forward all grace periods
        for key in list(checker._first_seen.keys()):
            checker._first_seen[key] = checker._first_seen[key] - timedelta(seconds=120)

        violations = checker.check(obs)
        names = {v.invariant_name for v in violations}
        assert "db_unreachable" in names
        assert "pool_exhaustion" in names
        assert "idle_in_transaction" in names
        assert "lock_contention" in names
        assert "high_latency" in names
        assert "high_error_rate" in names
