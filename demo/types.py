"""
Shared types for demo infrastructure.

This module defines:
- Chapter: Immutable chapter definition with callbacks
- DemoState: Chapter progression state machine
- ChaosType: Enum of chaos injection types
- ChaosConfig: Configuration for chaos scenarios
- HealthPollerProtocol: Protocol for subject-specific health polling

These types enable the demo framework to work with any distributed system
by abstracting the subject-specific details into configurations and protocols.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol


@dataclass(frozen=True)
class Chapter:
    """
    Immutable chapter definition with optional action callback.

    Each chapter represents a stage in the demo with narration
    explaining what is happening and what to watch for.

    Attributes:
        title: Chapter title displayed in panel
        narration: Explanatory text for the chapter
        key_hint: Keyboard hints shown at bottom
        on_enter: Optional async callback run when entering chapter
        auto_advance: If True, auto-advance after on_enter completes
        blocks_advance: If True, don't allow manual advance (action in progress)
    """

    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"
    on_enter: Callable[[], Awaitable[None]] | None = None
    auto_advance: bool = False
    blocks_advance: bool = False


@dataclass
class DemoState:
    """
    Manages chapter progression state.

    Tracks current chapter index and provides methods for
    advancing through chapters and checking completion.
    """

    chapters: list[Chapter]
    current: int = 0

    def advance(self) -> bool:
        """
        Advance to next chapter.

        Returns:
            True if advanced, False if already at end
        """
        if self.current < len(self.chapters) - 1:
            self.current += 1
            return True
        return False

    def get_current(self) -> Chapter:
        """
        Get current chapter.

        Returns:
            Current Chapter object
        """
        return self.chapters[self.current]

    def is_complete(self) -> bool:
        """
        Check if demo is at final chapter.

        Returns:
            True if at last chapter
        """
        return self.current >= len(self.chapters) - 1

    def get_progress(self) -> str:
        """
        Get progress string like "[3/7]".

        Returns:
            Progress indicator showing current position
        """
        return f"[{self.current + 1}/{len(self.chapters)}]"


class ChaosType(Enum):
    """
    Types of chaos that can be injected into demo subjects.

    Each chaos type corresponds to a different failure mode that
    the operator should detect and diagnose.
    """

    CONTAINER_KILL = "container_kill"  # Kill a container (e.g., TiKV node)
    REDIS_PAUSE = "redis_pause"  # Pause Redis to cause counter drift
    BURST_TRAFFIC = "burst_traffic"  # Send burst traffic to cause ghost allowing


@dataclass
class ChaosConfig:
    """
    Configuration for a chaos injection scenario.

    Defines what type of chaos to inject, when, and with what parameters.

    Attributes:
        name: Human-readable name for the chaos scenario
        chaos_type: Type of chaos to inject
        description: Detailed description for narration
        duration_sec: How long the chaos lasts (default: 5.0)
        burst_multiplier: For BURST_TRAFFIC, multiplier over normal rate (default: 2)
    """

    name: str
    chaos_type: ChaosType
    description: str
    duration_sec: float = 5.0
    burst_multiplier: int = 2


class HealthPollerProtocol(Protocol):
    """
    Protocol for subject-specific health polling.

    The demo runner uses this protocol to poll health metrics from
    the subject system without knowing subject-specific details.

    Implementations should:
    - Run continuous health checks in background
    - Return latest health snapshot on demand
    - Clean up resources when stopped
    """

    async def run(self) -> None:
        """
        Run continuous health polling in background.

        This coroutine should run until stop() is called.
        """
        ...

    def get_health(self) -> dict[str, Any] | None:
        """
        Get latest health snapshot.

        Returns:
            Health data dict, or None if no data available yet
        """
        ...

    def stop(self) -> None:
        """
        Stop health polling and clean up resources.
        """
        ...
