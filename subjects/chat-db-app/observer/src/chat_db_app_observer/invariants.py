"""
Chat DB App invariant definitions for health monitoring.

Invariants detect common database-backed application issues:
- Pool exhaustion: connection pool at capacity
- Database unreachable: can't connect to PostgreSQL
- Idle in transaction: connections held open too long
- Lock contention: too many sessions waiting on locks
- High latency: P99 response time too high
- High error rate: too many 5xx responses

Implements InvariantCheckerProtocol from operator_protocols.
Follows the grace-period pattern from tikv_observer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from operator_protocols import InvariantViolation


@dataclass
class InvariantConfig:
    """Configuration for an invariant check."""

    name: str
    grace_period: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    threshold: float = 0.0
    severity: str = "warning"
    clearing_criteria: str = ""


# Invariant configurations
POOL_EXHAUSTION_CONFIG = InvariantConfig(
    name="pool_exhaustion",
    grace_period=timedelta(seconds=30),
    threshold=90.0,  # total/max > 90% OR waiting > 0
    severity="critical",
    clearing_criteria="Pool utilization drops below 90% with zero waiting connections",
)

DB_UNREACHABLE_CONFIG = InvariantConfig(
    name="db_unreachable",
    grace_period=timedelta(seconds=0),  # Immediate
    severity="critical",
    clearing_criteria="Database becomes reachable",
)

IDLE_IN_TRANSACTION_CONFIG = InvariantConfig(
    name="idle_in_transaction",
    grace_period=timedelta(seconds=60),
    threshold=3.0,  # count > 3
    severity="warning",
    clearing_criteria="Fewer than 3 idle-in-transaction sessions",
)

LOCK_CONTENTION_CONFIG = InvariantConfig(
    name="lock_contention",
    grace_period=timedelta(seconds=15),
    threshold=5.0,  # waiting_on_lock > 5
    severity="warning",
    clearing_criteria="Fewer than 5 sessions waiting on locks",
)

HIGH_LATENCY_CONFIG = InvariantConfig(
    name="high_latency",
    grace_period=timedelta(seconds=60),
    threshold=500.0,  # p99 > 500ms
    severity="warning",
    clearing_criteria="P99 latency drops below 500ms",
)

HIGH_ERROR_RATE_CONFIG = InvariantConfig(
    name="high_error_rate",
    grace_period=timedelta(seconds=30),
    threshold=5.0,  # error_rate > 5%
    severity="critical",
    clearing_criteria="Error rate drops below 5%",
)

TABLE_BLOAT_CONFIG = InvariantConfig(
    name="table_bloat",
    grace_period=timedelta(seconds=30),
    threshold=2.0,  # dead_tuples / live_tuples > 2.0 for any table
    severity="warning",
    clearing_criteria="Dead tuple ratio drops below 2.0x for all tables",
)

HIGH_SEARCH_LATENCY_CONFIG = InvariantConfig(
    name="high_search_latency",
    grace_period=timedelta(seconds=30),
    threshold=2000.0,  # search P99 > 2000ms
    severity="warning",
    clearing_criteria="Search latency drops below 2000ms",
)


class ChatDBAppInvariantChecker:
    """
    Chat DB App invariant checker implementing InvariantCheckerProtocol.

    Tracks violations with grace period support. Maintains state for
    each invariant to track when violations were first seen.
    """

    def __init__(self) -> None:
        self._first_seen: dict[str, datetime] = {}

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """
        Check all invariants against an observation.

        Args:
            observation: Dictionary from ChatDBAppSubject.observe() with keys:
                app, connection_pool, database, endpoint_metrics.

        Returns:
            List of active InvariantViolation objects.
        """
        violations: list[InvariantViolation] = []

        pool = observation.get("connection_pool", {})
        db = observation.get("database", {})
        app = observation.get("app", {})
        metrics = observation.get("endpoint_metrics", {})

        # 1. Pool exhaustion
        v = self._check_pool_exhaustion(pool)
        if v:
            violations.append(v)

        # 2. Database unreachable
        v = self._check_db_unreachable(db)
        if v:
            violations.append(v)

        # 3. Idle in transaction
        v = self._check_idle_in_transaction(db)
        if v:
            violations.append(v)

        # 4. Lock contention
        v = self._check_lock_contention(db)
        if v:
            violations.append(v)

        # 5. High latency
        v = self._check_high_latency(metrics)
        if v:
            violations.append(v)

        # 6. High error rate
        v = self._check_high_error_rate(app)
        if v:
            violations.append(v)

        # 7. Table bloat (write amplification)
        v = self._check_table_bloat(db)
        if v:
            violations.append(v)

        # 8. High search latency
        v = self._check_high_search_latency(metrics)
        if v:
            violations.append(v)

        return violations

    def _check_pool_exhaustion(self, pool: dict) -> InvariantViolation | None:
        """Check if connection pool is at or near capacity."""
        config = POOL_EXHAUSTION_CONFIG
        total = pool.get("total", 0)
        max_size = pool.get("max_size", 0)
        waiting = pool.get("waiting", 0)

        # Pool exhausted if: waiting > 0 OR (max_size > 0 AND total/max > 90%)
        is_exhausted = waiting > 0
        if max_size > 0 and total > 0:
            utilization = (total / max_size) * 100
            is_exhausted = is_exhausted or utilization > config.threshold

        if is_exhausted:
            msg = f"Connection pool pressure: {total} total, {max_size} max, {waiting} waiting"
        else:
            msg = ""

        return self._check_with_grace_period(
            config=config,
            is_violated=is_exhausted,
            message=msg,
        )

    def _check_db_unreachable(self, db: dict) -> InvariantViolation | None:
        """Check if database is unreachable."""
        config = DB_UNREACHABLE_CONFIG
        reachable = db.get("reachable", True)

        return self._check_with_grace_period(
            config=config,
            is_violated=not reachable,
            message="Database is unreachable",
        )

    def _check_idle_in_transaction(self, db: dict) -> InvariantViolation | None:
        """Check for excessive idle-in-transaction sessions."""
        config = IDLE_IN_TRANSACTION_CONFIG
        count = db.get("idle_in_transaction", 0)
        is_violated = count > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"{count} sessions idle in transaction (threshold: {int(config.threshold)})",
        )

    def _check_lock_contention(self, db: dict) -> InvariantViolation | None:
        """Check for excessive lock contention."""
        config = LOCK_CONTENTION_CONFIG
        count = db.get("waiting_on_lock", 0)
        is_violated = count > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"{count} sessions waiting on locks (threshold: {int(config.threshold)})",
        )

    # Minimum RPS to trust P99 for the high_latency invariant.
    # At low RPS, a single slow query makes P99 spike to 5000ms.
    _MIN_RPS_FOR_LATENCY = 5.0

    def _check_high_latency(self, metrics: dict) -> InvariantViolation | None:
        """Check if P99 latency exceeds threshold.

        Only fires when RPS >= _MIN_RPS_FOR_LATENCY because at very low
        request rates, P99 is dominated by noise (a single slow query
        on a large dataset pushes P99 to the max histogram bucket).
        """
        config = HIGH_LATENCY_CONFIG
        p99 = metrics.get("latency_p99_ms", 0.0)
        rps = metrics.get("requests_per_sec", 0.0)
        is_violated = p99 > config.threshold and rps >= self._MIN_RPS_FOR_LATENCY

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"P99 latency {p99:.1f}ms exceeds threshold {config.threshold:.0f}ms (at {rps:.1f} RPS)",
        )

    def _check_high_error_rate(self, app: dict) -> InvariantViolation | None:
        """Check if error rate exceeds threshold."""
        config = HIGH_ERROR_RATE_CONFIG
        error_rate = app.get("error_rate_pct", 0.0)
        is_violated = error_rate > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"Error rate {error_rate:.1f}% exceeds threshold {config.threshold:.0f}%",
        )

    def _check_table_bloat(self, db: dict) -> InvariantViolation | None:
        """Check for excessive dead tuple accumulation (write amplification)."""
        config = TABLE_BLOAT_CONFIG
        table_bloat = db.get("table_bloat", [])

        worst_ratio = 0.0
        worst_table = ""
        worst_dead = 0
        for t in table_bloat:
            dead = t.get("dead_tuples", 0)
            live = t.get("live_tuples", 0)
            ratio = dead / max(live, 1)
            if ratio > worst_ratio:
                worst_ratio = ratio
                worst_table = t.get("table_name", "")
                worst_dead = dead

        is_violated = worst_ratio > config.threshold and worst_dead > 100

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"Table '{worst_table}' has {worst_dead} dead tuples ({worst_ratio:.1f}x live ratio, threshold: {config.threshold:.1f}x)",
        )

    def _check_high_search_latency(self, metrics: dict) -> InvariantViolation | None:
        """Check if search latency (from direct probes) exceeds threshold.

        Uses probe-based measurement — the observer directly calls the
        search endpoint — so no RPS gate is needed. A probe returning
        high latency is direct evidence of slow search.
        """
        config = HIGH_SEARCH_LATENCY_CONFIG
        latency = metrics.get("search_latency_p99_ms", 0.0)
        is_violated = latency > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_violated,
            message=f"Search latency {latency:.0f}ms exceeds threshold {config.threshold:.0f}ms",
        )

    def _check_with_grace_period(
        self,
        config: InvariantConfig,
        is_violated: bool,
        message: str,
    ) -> InvariantViolation | None:
        """
        Check if violation should be reported, respecting grace period.

        Follows the same pattern as tikv_observer.invariants.
        """
        key = config.name
        now = datetime.now()

        if not is_violated:
            self._first_seen.pop(key, None)
            return None

        if key not in self._first_seen:
            self._first_seen[key] = now

        first_seen = self._first_seen[key]

        if now - first_seen < config.grace_period:
            return None

        return InvariantViolation(
            invariant_name=config.name,
            message=message,
            first_seen=first_seen,
            last_seen=now,
            severity=config.severity,
            clearing_criteria=config.clearing_criteria or None,
        )

    def clear_state(self) -> None:
        """Clear all tracked violation state."""
        self._first_seen.clear()
