"""
TiKV invariant definitions for health monitoring.

This module implements TiKV-specific invariants that detect cluster issues:
- Store down: A TiKV store is not in "Up" state
- High latency: P99 latency exceeds threshold
- Low disk space: Disk usage exceeds threshold

Per CONTEXT.md decisions:
- Grace period configurable per invariant
- Fixed thresholds (not baseline-relative)
- Conservative resource thresholds (70%+)

Per RESEARCH.md Pattern 4:
- Invariants track first_seen time for grace period logic
- Violations clear when condition resolves
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from operator_core.types import Store, StoreMetrics


@dataclass
class InvariantViolation:
    """
    Represents an active invariant violation.

    Attributes:
        invariant_name: Name of the violated invariant (e.g., "store_down")
        message: Human-readable description of the violation
        first_seen: When the violation was first detected
        last_seen: When the violation was most recently confirmed
        store_id: Optional store ID if violation is store-specific
        severity: Violation severity ("critical", "warning", "info")
    """

    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    store_id: str | None = None
    severity: str = "warning"


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
    grace_period=timedelta(seconds=60),  # 60 seconds - allow transient spikes
    threshold=100.0,  # 100ms P99 threshold
    severity="warning",
)

LOW_DISK_SPACE_CONFIG = InvariantConfig(
    name="low_disk_space",
    grace_period=timedelta(seconds=0),  # Immediate - disk issues are critical
    threshold=70.0,  # 70% usage per CONTEXT.md
    severity="warning",
)


class InvariantChecker:
    """
    Tracks invariant violations with grace period support.

    Maintains state for each invariant to track when violations
    were first seen, enabling grace period logic.

    Example:
        checker = InvariantChecker()

        # Check store health
        stores = await pd_client.get_stores()
        violations = checker.check_stores_up(stores)

        # Check latency (with grace period)
        metrics = await prom_client.get_store_metrics(...)
        violations = checker.check_latency(metrics)
    """

    def __init__(self) -> None:
        """Initialize checker with empty violation tracking state."""
        # Track first_seen time for each violation key
        # Key format: "{invariant_name}:{store_id}" or just "{invariant_name}"
        self._first_seen: dict[str, datetime] = {}

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

    def clear_state(self) -> None:
        """Clear all tracked violation state."""
        self._first_seen.clear()
