"""
Invariant protocol and violation types.

The InvariantCheckerProtocol defines the interface for checking health
invariants against observations. InvariantViolation represents a detected
violation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class InvariantViolation:
    """
    Represents an active invariant violation.

    This dataclass captures all information about a detected violation,
    including when it was first seen (for grace period tracking) and
    optional entity identification.

    Attributes:
        invariant_name: Name of the violated invariant (e.g., "store_down",
            "high_latency", "rate_limit_exhausted")
        message: Human-readable description of the violation
        first_seen: When the violation was first detected
        last_seen: When the violation was most recently confirmed
        store_id: Optional identifier for the affected entity. Named store_id
            for backward compatibility but can represent any entity (node,
            service, etc.)
        severity: Violation severity level:
            - "critical": Requires immediate attention
            - "warning": Should be investigated
            - "info": Informational only
    """

    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    store_id: str | None = None
    severity: str = "warning"


@runtime_checkable
class InvariantCheckerProtocol(Protocol):
    """
    Protocol for invariant checkers.

    An InvariantChecker examines observations and detects violations
    of health invariants. Each implementation defines its own set of
    invariants appropriate for the subject being monitored.

    Example invariants:
    - TiKV: store_down, high_latency, low_disk_space
    - Rate limiter: quota_exhausted, high_rejection_rate

    Implementations should:
    - Track first_seen times for grace period support
    - Clear violations when conditions resolve
    - Return all currently active violations
    """

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """
        Check invariants against an observation.

        Args:
            observation: A dictionary containing the current state of the
                subject, as returned by SubjectProtocol.observe().

        Returns:
            List of InvariantViolation objects for all currently active
            violations. Returns an empty list if no violations are detected.
        """
        ...
