"""Type definitions for evaluation harness."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ChaosType(str, Enum):
    """Chaos types supported by evaluation harness."""

    NODE_KILL = "node_kill"
    # Future: LATENCY, DISK_PRESSURE, NETWORK_PARTITION


@runtime_checkable
class EvalSubject(Protocol):
    """Protocol for evaluation subjects.

    Any system under test must implement these methods to be evaluated.
    """

    async def reset(self) -> None:
        """Reset subject to clean initial state."""
        ...

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for subject to reach healthy state.

        Args:
            timeout_sec: Maximum time to wait in seconds

        Returns:
            True if healthy within timeout, False otherwise
        """
        ...

    async def capture_state(self) -> dict[str, Any]:
        """Capture current subject state for comparison.

        Returns:
            State snapshot as JSON-serializable dict
        """
        ...

    def get_chaos_types(self) -> list[str]:
        """Return list of chaos types this subject supports.

        Returns:
            List of chaos type identifiers (e.g., ["node_kill"])
        """
        ...

    async def inject_chaos(self, chaos_type: str) -> dict[str, Any]:
        """Inject specified chaos type.

        Args:
            chaos_type: One of get_chaos_types() values

        Returns:
            Chaos metadata as JSON-serializable dict

        Raises:
            ValueError: If chaos_type not supported
        """
        ...


@dataclass
class Campaign:
    """Evaluation campaign metadata."""

    id: int | None = None
    subject_name: str = ""
    chaos_type: str = ""
    trial_count: int = 0
    baseline: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class Trial:
    """Single trial execution record."""

    id: int | None = None
    campaign_id: int = 0
    started_at: str = ""
    chaos_injected_at: str = ""
    ticket_created_at: str | None = None  # None for baseline
    resolved_at: str | None = None  # None if not resolved
    ended_at: str = ""
    initial_state: str = ""  # JSON blob
    final_state: str = ""  # JSON blob
    chaos_metadata: str = ""  # JSON blob
    commands_json: str = "[]"  # JSON array of commands
