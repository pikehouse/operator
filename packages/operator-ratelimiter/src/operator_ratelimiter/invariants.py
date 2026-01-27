"""
Rate Limiter invariant definitions for health monitoring.

This module implements rate limiter-specific invariants that detect cluster issues:
- Node down: A rate limiter node is not in "Up" state
- Redis disconnected: Redis connectivity lost
- High latency: P99 check latency exceeds threshold
- Counter drift: Redis counter doesn't match expected value
- Ghost allowing: Keys allowing requests with no valid limit

Implements InvariantCheckerProtocol from operator_protocols.

Pattern mirrors TiKVInvariantChecker for consistency.
Grace period support for latency and counter_drift invariants.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from operator_protocols import InvariantViolation
from operator_ratelimiter.types import CounterInfo, NodeInfo


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


# Default invariant configurations
NODE_DOWN_CONFIG = InvariantConfig(
    name="node_down",
    grace_period=timedelta(seconds=0),  # Immediate - node down is critical
    severity="critical",
)

REDIS_DISCONNECTED_CONFIG = InvariantConfig(
    name="redis_disconnected",
    grace_period=timedelta(seconds=0),  # Immediate - Redis is critical
    severity="critical",
)

HIGH_LATENCY_CONFIG = InvariantConfig(
    name="high_latency",
    grace_period=timedelta(seconds=60),  # 60 seconds - allow transient spikes
    threshold=100.0,  # 100ms P99 threshold
    severity="warning",
)

COUNTER_DRIFT_CONFIG = InvariantConfig(
    name="counter_drift",
    grace_period=timedelta(seconds=30),  # 30 seconds - allow brief inconsistencies
    threshold=5.0,  # 5 count difference threshold
    severity="warning",
)

GHOST_ALLOWING_CONFIG = InvariantConfig(
    name="ghost_allowing",
    grace_period=timedelta(seconds=0),  # Immediate - over-limit is critical
    threshold=0.0,  # Any over-limit allowing is a violation
    severity="warning",
)

OVER_LIMIT_CONFIG = InvariantConfig(
    name="over_limit",
    grace_period=timedelta(seconds=0),  # Immediate - over-limit is critical
    threshold=0.0,  # Any count > limit is a violation
    severity="warning",
)


class RateLimiterInvariantChecker:
    """
    Rate limiter-specific invariant checker implementing InvariantCheckerProtocol.

    Tracks invariant violations with grace period support.
    Maintains state for each invariant to track when violations
    were first seen, enabling grace period logic.

    Implements InvariantCheckerProtocol.check() for generic observation processing.

    Invariants:
    1. node_down: Detects nodes not in "Up" state
    2. redis_disconnected: Detects Redis connectivity loss
    3. high_latency: Detects P99 latency above threshold (with grace period)
    4. counter_drift: Detects Redis counter mismatch (with grace period)
    5. ghost_allowing: Detects keys allowing requests with limit=0

    Example:
        checker = RateLimiterInvariantChecker()

        # Generic protocol usage (observation dict from RateLimiterSubject.observe())
        observation = await subject.observe()
        violations = checker.check(observation)

        for v in violations:
            print(f"{v.invariant_name}: {v.message}")
    """

    def __init__(self) -> None:
        """Initialize checker with empty violation tracking state."""
        # Track first_seen time for each violation key
        # Key format: "{invariant_name}:{identifier}" or just "{invariant_name}"
        self._first_seen: dict[str, datetime] = {}

    # -------------------------------------------------------------------------
    # InvariantCheckerProtocol.check() - Generic observation interface
    # -------------------------------------------------------------------------

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """
        Check rate limiter-specific invariants against an observation.

        Implements InvariantCheckerProtocol.check() by examining the observation
        dict (as returned by RateLimiterSubject.observe()) and running all
        rate limiter-specific health checks.

        Args:
            observation: Dictionary with keys:
                - "nodes": List of node dicts with id, address, state
                - "counters": List of counter dicts with key, count, limit, remaining
                - "node_metrics": Dict mapping node_id to metrics dict
                - "redis_connected": Boolean Redis connectivity status

        Returns:
            List of InvariantViolation objects for all currently active
            violations. Returns an empty list if no violations are detected.
        """
        violations: list[InvariantViolation] = []

        # Check Redis connectivity (cluster-wide)
        redis_connected = observation.get("redis_connected", True)
        violations.extend(self.check_redis_connectivity(redis_connected))

        # Check node health from observation
        nodes_data = observation.get("nodes", [])
        nodes = [
            NodeInfo(
                id=n["id"],
                address=n["address"],
                state=n["state"],
            )
            for n in nodes_data
        ]
        violations.extend(self.check_nodes_up(nodes))

        # Check metrics for nodes that have metrics data
        node_metrics_data = observation.get("node_metrics", {})
        for node_id, metrics_data in node_metrics_data.items():
            latency_p99 = metrics_data.get("latency_p99_ms", 0.0)

            # Check latency invariant
            if violation := self.check_latency(node_id, latency_p99):
                violations.append(violation)

        # Check counter invariants
        counters_data = observation.get("counters", [])
        counters = [
            CounterInfo(
                key=c["key"],
                count=c["count"],
                limit=c["limit"],
                remaining=c["remaining"],
            )
            for c in counters_data
        ]
        violations.extend(self.check_counters(counters))

        return violations

    # -------------------------------------------------------------------------
    # Rate limiter-specific check methods
    # -------------------------------------------------------------------------

    def _get_violation_key(self, invariant_name: str, identifier: str | None) -> str:
        """Generate unique key for tracking a specific violation."""
        if identifier:
            return f"{invariant_name}:{identifier}"
        return invariant_name

    def _check_with_grace_period(
        self,
        config: InvariantConfig,
        is_violated: bool,
        message: str,
        identifier: str | None = None,
    ) -> InvariantViolation | None:
        """
        Check if violation should be reported, respecting grace period.

        Args:
            config: Invariant configuration with grace period and severity
            is_violated: Whether the invariant condition is currently violated
            message: Description of the violation
            identifier: Optional identifier for specific violations (node_id, key, etc.)

        Returns:
            InvariantViolation if grace period has elapsed, None otherwise
        """
        key = self._get_violation_key(config.name, identifier)
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
            store_id=identifier,  # Use identifier for backward compat with store_id field
            severity=config.severity,
        )

    def check_nodes_up(
        self,
        nodes: list[NodeInfo],
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """
        Check that all nodes are in "Up" state.

        Args:
            nodes: List of NodeInfo objects from management API
            config: Optional custom configuration (defaults to NODE_DOWN_CONFIG)

        Returns:
            List of violations for nodes not in "Up" state
        """
        config = config or NODE_DOWN_CONFIG
        violations: list[InvariantViolation] = []

        # Track which nodes are currently down
        current_down_nodes: set[str] = set()

        for node in nodes:
            is_down = node.state != "Up"
            current_down_nodes.add(node.id) if is_down else None

            violation = self._check_with_grace_period(
                config=config,
                is_violated=is_down,
                message=f"Node {node.id} at {node.address} is {node.state}",
                identifier=node.id,
            )
            if violation:
                violations.append(violation)

        # Clear tracking for nodes that came back up
        keys_to_clear = [
            key
            for key in self._first_seen
            if key.startswith(f"{config.name}:")
            and key.split(":", 1)[1] not in current_down_nodes
        ]
        for key in keys_to_clear:
            self._first_seen.pop(key, None)

        return violations

    def check_redis_connectivity(
        self,
        redis_connected: bool,
        config: InvariantConfig | None = None,
    ) -> list[InvariantViolation]:
        """
        Check Redis connectivity.

        Args:
            redis_connected: Boolean Redis connectivity status
            config: Optional custom configuration (defaults to REDIS_DISCONNECTED_CONFIG)

        Returns:
            List with single violation if Redis is disconnected, empty list otherwise
        """
        config = config or REDIS_DISCONNECTED_CONFIG

        violation = self._check_with_grace_period(
            config=config,
            is_violated=not redis_connected,
            message="Redis connection lost - rate limiting may not work correctly",
            identifier=None,  # Cluster-wide violation
        )

        return [violation] if violation else []

    def check_latency(
        self,
        node_id: str,
        latency_p99_ms: float,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """
        Check that P99 check latency is below threshold.

        Args:
            node_id: The node ID being checked
            latency_p99_ms: P99 latency in milliseconds
            config: Optional custom configuration (defaults to HIGH_LATENCY_CONFIG)

        Returns:
            InvariantViolation if latency exceeds threshold past grace period
        """
        config = config or HIGH_LATENCY_CONFIG

        is_high = latency_p99_ms > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=f"Node {node_id} P99 latency {latency_p99_ms:.1f}ms exceeds threshold {config.threshold:.1f}ms",
            identifier=node_id,
        )

    def check_counters(
        self,
        counters: list[CounterInfo],
    ) -> list[InvariantViolation]:
        """
        Check counter invariants: over-limit and ghost allowing.

        Detects:
        - Over-limit: count > limit (more requests allowed than limit permits)
        - Ghost allowing: limit is 0 but remaining > 0 (misconfigured key)

        Args:
            counters: List of CounterInfo objects from management API

        Returns:
            List of violations for counter anomalies
        """
        violations: list[InvariantViolation] = []

        # Track which keys currently have violations
        current_over_limit_keys: set[str] = set()
        current_ghost_keys: set[str] = set()

        for counter in counters:
            # Over-limit: count exceeds limit (requests allowed when they shouldn't be)
            is_over_limit = counter.count > counter.limit
            if is_over_limit:
                current_over_limit_keys.add(counter.key)

            violation = self._check_with_grace_period(
                config=OVER_LIMIT_CONFIG,
                is_violated=is_over_limit,
                message=f"Counter {counter.key} over limit: count={counter.count}, limit={counter.limit} (excess={counter.count - counter.limit})",
                identifier=counter.key,
            )
            if violation:
                violations.append(violation)

            # Ghost allowing: limit is 0 but remaining > 0 (requests being allowed with no limit)
            is_ghost = counter.limit == 0 and counter.remaining > 0
            if is_ghost:
                current_ghost_keys.add(counter.key)

            violation = self._check_with_grace_period(
                config=GHOST_ALLOWING_CONFIG,
                is_violated=is_ghost,
                message=f"Counter {counter.key} has limit=0 but remaining={counter.remaining} (ghost allowing)",
                identifier=counter.key,
            )
            if violation:
                violations.append(violation)

        # Clear tracking for keys that no longer have violations
        keys_to_clear = [
            key
            for key in self._first_seen
            if (key.startswith(f"{OVER_LIMIT_CONFIG.name}:")
                and key.split(":", 1)[1] not in current_over_limit_keys)
            or (key.startswith(f"{GHOST_ALLOWING_CONFIG.name}:")
                and key.split(":", 1)[1] not in current_ghost_keys)
        ]
        for key in keys_to_clear:
            self._first_seen.pop(key, None)

        return violations

    def check_counter_drift(
        self,
        counter: CounterInfo,
        redis_count: int,
        config: InvariantConfig | None = None,
    ) -> InvariantViolation | None:
        """
        Check for counter drift between API and Redis.

        This method is provided for testing but not used in the generic check()
        flow since it requires additional Redis queries that would be inefficient
        to run for every counter on every observation.

        Args:
            counter: CounterInfo from management API
            redis_count: Raw count from Redis
            config: Optional custom configuration (defaults to COUNTER_DRIFT_CONFIG)

        Returns:
            InvariantViolation if drift exceeds threshold past grace period
        """
        config = config or COUNTER_DRIFT_CONFIG

        drift = abs(counter.count - redis_count)
        is_drifted = drift > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_drifted,
            message=f"Counter {counter.key} drift: API={counter.count}, Redis={redis_count}, drift={drift}",
            identifier=counter.key,
        )

    def clear_state(self) -> None:
        """Clear all tracked violation state."""
        self._first_seen.clear()
