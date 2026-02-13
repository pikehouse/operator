"""
TiKV invariant definitions for health monitoring.

This module implements TiKV-specific invariants that detect cluster issues:
- Store down: A TiKV store is not in "Up" state
- High latency: P99 latency exceeds threshold
- Low disk space: Disk usage exceeds threshold

Implements InvariantCheckerProtocol from operator_protocols.

Per CONTEXT.md decisions:
- Grace period configurable per invariant
- Fixed thresholds (not baseline-relative)
- Conservative resource thresholds (70%+)

Per RESEARCH.md Pattern 4:
- Invariants track first_seen time for grace period logic
- Violations clear when condition resolves
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from operator_protocols import InvariantViolation
from operator_protocols.types import Store, StoreMetrics


@dataclass
class InvariantConfig:
    """
    Configuration for an invariant check.

    Attributes:
        name: Unique invariant identifier
        grace_period: How long a violation must persist before being reported
        threshold: Numeric threshold for the check (interpretation varies by invariant)
        severity: Default severity level for violations
    """

    name: str
    grace_period: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    threshold: float = 0.0
    severity: str = "warning"


# Default invariant configurations per CONTEXT.md
STORE_DOWN_CONFIG = InvariantConfig(
    name="store_down",
    grace_period=timedelta(seconds=0),  # Immediate - store down is critical
    severity="critical",
)

HIGH_LATENCY_CONFIG = InvariantConfig(
    name="high_latency",
    grace_period=timedelta(seconds=30),  # 30 seconds - allow Prometheus rate window to stabilize
    threshold=100.0,  # 100ms P99 threshold
    severity="warning",
)

LOW_DISK_SPACE_CONFIG = InvariantConfig(
    name="low_disk_space",
    grace_period=timedelta(seconds=0),  # Immediate - disk issues are critical
    threshold=70.0,  # 70% usage per CONTEXT.md
    severity="warning",
)

LEADER_IMBALANCE_CONFIG = InvariantConfig(
    name="leader_imbalance",
    grace_period=timedelta(seconds=15),
    threshold=2.0,  # max - min leader count difference; triggers when 1 store has 3+ more leaders
    severity="warning",
)

HIGH_RAFT_LAG_CONFIG = InvariantConfig(
    name="high_raft_lag",
    grace_period=timedelta(seconds=30),
    threshold=50.0,  # raft log entries behind
    severity="warning",
)

METRICS_UNAVAILABLE_CONFIG = InvariantConfig(
    name="metrics_unavailable",
    grace_period=timedelta(seconds=30),
    severity="warning",
)

HIGH_RAFT_COMMIT_CONFIG = InvariantConfig(
    name="high_raft_commit",
    grace_period=timedelta(seconds=30),
    threshold=50.0,  # 50ms, baseline is ~6ms
    severity="warning",
)

HIGH_SCRAPE_DURATION_CONFIG = InvariantConfig(
    name="high_scrape_duration",
    grace_period=timedelta(seconds=30),
    threshold=0.5,  # 500ms; baseline is ~10ms, network latency inflates scrape time
    severity="warning",
)

STALE_HEARTBEAT_CONFIG = InvariantConfig(
    name="stale_heartbeat",
    grace_period=timedelta(seconds=0),  # Immediate — staleness IS the grace
    threshold=60.0,  # seconds since last heartbeat
    severity="critical",
)

PD_HEALTH_CONFIG = InvariantConfig(
    name="pd_health",
    grace_period=timedelta(seconds=15),  # Brief grace: PD elections take ~5-10s
    threshold=3.0,  # Expected PD node count
    severity="critical",
)


class TiKVInvariantChecker:
    """
    TiKV-specific invariant checker implementing InvariantCheckerProtocol.

    Tracks invariant violations with grace period support.
    Maintains state for each invariant to track when violations
    were first seen, enabling grace period logic.

    Implements InvariantCheckerProtocol.check() for generic observation processing,
    while also exposing TiKV-specific check methods for backward compatibility.

    Example:
        checker = TiKVInvariantChecker()

        # Generic protocol usage (observation dict from TiKVSubject.observe())
        observation = await subject.observe()
        violations = checker.check(observation)

        # TiKV-specific usage (direct Store/StoreMetrics objects)
        stores = await pd_client.get_stores()
        violations = checker.check_stores_up(stores)

        metrics = await prom_client.get_store_metrics(...)
        violations = checker.check_latency(metrics)
    """

    def __init__(self) -> None:
        """Initialize checker with empty violation tracking state."""
        # Track first_seen time for each violation key
        # Key format: "{invariant_name}:{store_id}" or just "{invariant_name}"
        self._first_seen: dict[str, datetime] = {}

    # -------------------------------------------------------------------------
    # InvariantCheckerProtocol.check() - Generic observation interface
    # -------------------------------------------------------------------------

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """
        Check TiKV-specific invariants against an observation.

        Implements InvariantCheckerProtocol.check() by examining the observation
        dict (as returned by TiKVSubject.observe()) and running all TiKV-specific
        health checks.

        Args:
            observation: Dictionary with keys:
                - "stores": List of store dicts with id, address, state
                - "store_metrics": Dict mapping store_id to metrics dict

        Returns:
            List of InvariantViolation objects for all currently active
            violations. Returns an empty list if no violations are detected.
        """
        violations: list[InvariantViolation] = []

        # Check store health from observation
        stores_data = observation.get("stores", [])
        stores = [
            Store(
                id=s["id"],
                address=s["address"],
                state=s["state"],
            )
            for s in stores_data
        ]
        violations.extend(self.check_stores_up(stores))

        # Check metrics for stores that have metrics data
        store_metrics_data = observation.get("store_metrics", {})
        for store_id, metrics_data in store_metrics_data.items():
            metrics = StoreMetrics(
                store_id=store_id,
                qps=metrics_data.get("qps", 0.0),
                latency_p99_ms=metrics_data.get("latency_p99_ms", 0.0),
                disk_used_bytes=metrics_data.get("disk_used_bytes", 0),
                disk_total_bytes=metrics_data.get("disk_total_bytes", 1),
                cpu_percent=metrics_data.get("cpu_percent", 0.0),
                raft_lag=metrics_data.get("raft_lag", 0),
                raft_commit_p99_ms=metrics_data.get("raft_commit_p99_ms", 0.0),
                scrape_duration_seconds=metrics_data.get("scrape_duration_seconds", 0.0),
            )

            # Check latency invariant
            if violation := self.check_latency(metrics):
                violations.append(violation)

            # Check disk space invariant
            if violation := self.check_disk_space(metrics):
                violations.append(violation)

            # Check raft lag invariant
            if violation := self.check_raft_lag(metrics):
                violations.append(violation)

            # Check raft commit duration invariant
            if violation := self.check_raft_commit(metrics):
                violations.append(violation)

            # Check scrape duration invariant (workload-independent)
            if violation := self.check_scrape_duration(metrics):
                violations.append(violation)

        # Check leader balance across cluster
        # Skip when all counts are 0 — indicates a failed regions query
        # which would incorrectly clear the grace period timer
        cluster_metrics = observation.get("cluster_metrics", {})
        leader_counts = cluster_metrics.get("leader_count", {})
        if leader_counts and any(v > 0 for v in leader_counts.values()):
            violations.extend(self.check_leader_balance(leader_counts))

        # Check metrics availability (Up stores missing metrics)
        violations.extend(
            self.check_metrics_availability(stores_data, store_metrics_data)
        )

        # Check heartbeat staleness (network partition detection)
        violations.extend(self.check_heartbeat_stale(stores_data))

        # Check PD cluster health
        pd_health = observation.get("pd_health")
        if pd_health:
            violations.extend(self.check_pd_health(pd_health))

        return violations

    # -------------------------------------------------------------------------
    # TiKV-specific check methods (backward compatibility)
    # -------------------------------------------------------------------------

    def _get_violation_key(self, invariant_name: str, store_id: str | None) -> str:
        """Generate unique key for tracking a specific violation."""
        if store_id:
            return f"{invariant_name}:{store_id}"
        return invariant_name

    def _check_with_grace_period(
        self,
        config: InvariantConfig,
        is_violated: bool,
        message: str,
        store_id: str | None = None,
    ) -> InvariantViolation | None:
        """
        Check if violation should be reported, respecting grace period.

        Args:
            config: Invariant configuration with grace period and severity
            is_violated: Whether the invariant condition is currently violated
            message: Description of the violation
            store_id: Optional store ID for store-specific violations

        Returns:
            InvariantViolation if grace period has elapsed, None otherwise
        """
        key = self._get_violation_key(config.name, store_id)
        now = datetime.now()

        if not is_violated:
            # Clear tracking when violation resolves
            self._first_seen.pop(key, None)
            return None

        # Track when violation was first seen
        if key not in self._first_seen:
            self._first_seen[key] = now

        first_seen = self._first_seen[key]

        # Check if grace period has elapsed
        if now - first_seen < config.grace_period:
            return None  # Still within grace period

        return InvariantViolation(
            invariant_name=config.name,
            message=message,
            first_seen=first_seen,
            last_seen=now,
            store_id=store_id,
            severity=config.severity,
        )

    def check_stores_up(
        self,
        stores: list[Store],
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """
        Check that all stores are in "Up" state.

        Args:
            stores: List of Store objects from PD API
            config: Optional custom configuration (defaults to STORE_DOWN_CONFIG)

        Returns:
            List of violations for stores not in "Up" state
        """
        config = config or STORE_DOWN_CONFIG
        violations: list[InvariantViolation] = []

        # Track which stores are currently down
        current_down_stores: set[str] = set()

        for store in stores:
            is_down = store.state != "Up"
            current_down_stores.add(store.id) if is_down else None

            violation = self._check_with_grace_period(
                config=config,
                is_violated=is_down,
                message=f"Store {store.id} at {store.address} is {store.state}",
                store_id=store.id,
            )
            if violation:
                violations.append(violation)

        # Clear tracking for stores that came back up
        keys_to_clear = [
            key
            for key in self._first_seen
            if key.startswith(f"{config.name}:")
            and key.split(":", 1)[1] not in current_down_stores
        ]
        for key in keys_to_clear:
            self._first_seen.pop(key, None)

        return violations

    def check_latency(
        self,
        metrics: StoreMetrics,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """
        Check that P99 latency is below threshold.

        Args:
            metrics: StoreMetrics with latency_p99_ms field
            config: Optional custom configuration (defaults to HIGH_LATENCY_CONFIG)

        Returns:
            InvariantViolation if latency exceeds threshold past grace period
        """
        config = config or HIGH_LATENCY_CONFIG

        is_high = metrics.latency_p99_ms > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=f"Store {metrics.store_id} P99 latency {metrics.latency_p99_ms:.1f}ms exceeds threshold {config.threshold:.1f}ms",
            store_id=metrics.store_id,
        )

    def check_disk_space(
        self,
        metrics: StoreMetrics,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """
        Check that disk usage is below threshold.

        Args:
            metrics: StoreMetrics with disk_used_bytes and disk_total_bytes
            config: Optional custom configuration (defaults to LOW_DISK_SPACE_CONFIG)

        Returns:
            InvariantViolation if disk usage exceeds threshold
        """
        config = config or LOW_DISK_SPACE_CONFIG

        # Calculate usage percentage
        if metrics.disk_total_bytes <= 0:
            return None  # Can't calculate usage

        usage_percent = (metrics.disk_used_bytes / metrics.disk_total_bytes) * 100
        is_low = usage_percent > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_low,
            message=f"Store {metrics.store_id} disk usage {usage_percent:.1f}% exceeds threshold {config.threshold:.1f}%",
            store_id=metrics.store_id,
        )

    def check_leader_balance(
        self,
        leader_counts: dict[str, int],
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """Check that region leaders are balanced across stores.

        Args:
            leader_counts: Mapping of store_id to leader count
            config: Optional custom configuration (defaults to LEADER_IMBALANCE_CONFIG)

        Returns:
            List with a single violation if leader distribution is skewed
        """
        config = config or LEADER_IMBALANCE_CONFIG

        if len(leader_counts) < 2:
            return []

        counts = list(leader_counts.values())
        diff = max(counts) - min(counts)
        is_imbalanced = diff > config.threshold

        violation = self._check_with_grace_period(
            config=config,
            is_violated=is_imbalanced,
            message=(
                f"Leader imbalance: max-min difference is {diff} "
                f"(threshold {int(config.threshold)}), "
                f"distribution: {leader_counts}"
            ),
        )

        return [violation] if violation else []

    def check_raft_lag(
        self,
        metrics: StoreMetrics,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """Check that Raft log lag is below threshold.

        Args:
            metrics: StoreMetrics with raft_lag field
            config: Optional custom configuration (defaults to HIGH_RAFT_LAG_CONFIG)

        Returns:
            InvariantViolation if raft lag exceeds threshold past grace period
        """
        config = config or HIGH_RAFT_LAG_CONFIG

        is_high = metrics.raft_lag > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=(
                f"Store {metrics.store_id} raft lag {metrics.raft_lag} entries "
                f"exceeds threshold {int(config.threshold)}"
            ),
            store_id=metrics.store_id,
        )

    def check_raft_commit(
        self,
        metrics: StoreMetrics,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """Check that Raft commit duration is below threshold.

        Raft commit duration measures peer-to-peer network round-trip time.
        Spikes indicate network issues (latency, packet loss, partitions).

        Args:
            metrics: StoreMetrics with raft_commit_p99_ms field
            config: Optional custom configuration (defaults to HIGH_RAFT_COMMIT_CONFIG)

        Returns:
            InvariantViolation if raft commit duration exceeds threshold past grace period
        """
        config = config or HIGH_RAFT_COMMIT_CONFIG

        is_high = metrics.raft_commit_p99_ms > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=(
                f"Store {metrics.store_id} raft commit P99 {metrics.raft_commit_p99_ms:.1f}ms "
                f"exceeds threshold {config.threshold:.1f}ms"
            ),
            store_id=metrics.store_id,
        )

    def check_scrape_duration(
        self,
        metrics: StoreMetrics,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """Check that Prometheus scrape duration is below threshold.

        Scrape duration measures how long Prometheus takes to collect metrics
        from a TiKV instance. When tc netem adds network latency, scrapes
        slow down proportionally. This provides workload-independent detection
        of network degradation (does not require client traffic like YCSB).

        Args:
            metrics: StoreMetrics with scrape_duration_seconds field
            config: Optional custom configuration (defaults to HIGH_SCRAPE_DURATION_CONFIG)

        Returns:
            InvariantViolation if scrape duration exceeds threshold past grace period
        """
        config = config or HIGH_SCRAPE_DURATION_CONFIG

        is_high = metrics.scrape_duration_seconds > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=(
                f"Store {metrics.store_id} scrape duration {metrics.scrape_duration_seconds:.3f}s "
                f"exceeds threshold {config.threshold:.3f}s"
            ),
            store_id=metrics.store_id,
        )

    def check_heartbeat_stale(
        self,
        stores_data: list[dict],
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """Check that Up stores have recent heartbeats from PD.

        Detects network partitions by checking if a store's last heartbeat
        timestamp is older than the threshold. During a partition, TiKV cannot
        send heartbeats to PD, but PD keeps the store in "Up" state for up to
        30 minutes (max-store-down-time). This invariant detects the gap
        within ~75 seconds instead.

        Args:
            stores_data: List of store dicts with id, address, state,
                last_heartbeat_ts
            config: Optional custom configuration (defaults to STALE_HEARTBEAT_CONFIG)

        Returns:
            List of violations for Up stores with stale heartbeats
        """
        config = config or STALE_HEARTBEAT_CONFIG
        violations: list[InvariantViolation] = []
        now = datetime.now(timezone.utc)

        for store in stores_data:
            store_id = str(store.get("id", ""))
            state = store.get("state", "")
            address = store.get("address", "")
            heartbeat_ts = store.get("last_heartbeat_ts", "")

            if state != "Up":
                key = self._get_violation_key(config.name, store_id)
                self._first_seen.pop(key, None)
                continue

            if not heartbeat_ts:
                # No heartbeat data available — skip (don't false-alarm)
                continue

            try:
                # PD returns timestamps like "2024-01-15T10:30:00.123456789+08:00"
                # Python's fromisoformat handles most ISO formats; strip nanoseconds
                # beyond microseconds if present
                ts_str = heartbeat_ts
                # Handle nanosecond precision: keep only up to 6 fractional digits
                if "." in ts_str:
                    dot_idx = ts_str.index(".")
                    # Find the end of fractional digits
                    frac_end = dot_idx + 1
                    while frac_end < len(ts_str) and ts_str[frac_end].isdigit():
                        frac_end += 1
                    frac_digits = ts_str[dot_idx + 1 : frac_end]
                    remainder = ts_str[frac_end:]
                    ts_str = ts_str[: dot_idx + 1] + frac_digits[:6] + remainder

                last_hb = datetime.fromisoformat(ts_str)
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)
                staleness = (now - last_hb).total_seconds()
            except (ValueError, TypeError):
                continue

            is_stale = staleness > config.threshold

            violation = self._check_with_grace_period(
                config=config,
                is_violated=is_stale,
                message=(
                    f"Store {store_id} at {address} heartbeat stale by {staleness:.0f}s "
                    f"(threshold {config.threshold:.0f}s)"
                ),
                store_id=store_id,
            )
            if violation:
                violations.append(violation)

        return violations

    def check_metrics_availability(
        self,
        stores_data: list[dict],
        store_metrics_data: dict,
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """Check that all Up stores have metrics available.

        Detects stores that PD reports as Up but Prometheus has no data for.
        This can indicate a frozen process (SIGSTOP) or broken network where
        the store is technically running but not responsive.

        Args:
            stores_data: List of store dicts with id, address, state
            store_metrics_data: Dict mapping store_id to metrics dict
            config: Optional custom configuration (defaults to METRICS_UNAVAILABLE_CONFIG)

        Returns:
            List of violations for Up stores missing metrics
        """
        config = config or METRICS_UNAVAILABLE_CONFIG
        violations: list[InvariantViolation] = []

        for store in stores_data:
            store_id = str(store.get("id", ""))
            state = store.get("state", "")
            address = store.get("address", "")

            if state != "Up":
                # Only flag Up stores with missing metrics
                # Clear any existing tracking for non-Up stores
                key = self._get_violation_key(config.name, store_id)
                self._first_seen.pop(key, None)
                continue

            has_metrics = store_id in store_metrics_data

            violation = self._check_with_grace_period(
                config=config,
                is_violated=not has_metrics,
                message=(
                    f"Store {store_id} at {address} is Up but has no metrics data"
                ),
                store_id=store_id,
            )
            if violation:
                violations.append(violation)

        return violations

    def check_pd_health(
        self,
        pd_health: dict[str, Any],
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """Check that the PD cluster has all expected nodes healthy.

        Detects when a PD node is killed or unreachable by comparing the
        number of responsive PD endpoints to the expected total.

        Args:
            pd_health: Dict with "total" (expected count) and "healthy" (responsive count)
            config: Optional custom configuration (defaults to PD_HEALTH_CONFIG)

        Returns:
            List with a single violation if PD cluster is degraded
        """
        config = config or PD_HEALTH_CONFIG

        total = pd_health.get("total", 0)
        healthy = pd_health.get("healthy", 0)

        if total == 0:
            return []

        is_degraded = healthy < total

        violation = self._check_with_grace_period(
            config=config,
            is_violated=is_degraded,
            message=(
                f"PD cluster degraded: {healthy}/{total} nodes healthy"
            ),
        )

        return [violation] if violation else []

    def clear_state(self) -> None:
        """Clear all tracked violation state."""
        self._first_seen.clear()
