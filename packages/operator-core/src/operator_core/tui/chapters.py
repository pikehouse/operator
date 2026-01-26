"""
Chapter definitions and DemoState for TUI demo flow.

This module provides the chapter state machine for key-press driven
demo progression.

Per RESEARCH.md Pattern 2: Chapter State Machine
- Chapter dataclass holds title, narration, and key hints
- DemoState manages chapter progression with advance/get_current methods
- DEMO_CHAPTERS list defines the 7 demo stages

The demo flow matches the ChaosDemo stages:
1. Welcome
2. Stage 1: Cluster Health
3. Stage 2: Load Generation
4. Stage 3: Fault Injection
5. Stage 4: Detection
6. Stage 5: AI Diagnosis
7. Demo Complete

Per 11-02-PLAN.md:
- Chapter supports on_enter callback for automated actions
- auto_advance flag for auto-progression after callback completes
- blocks_advance flag to prevent manual advance during action
"""

from dataclasses import dataclass
from typing import Awaitable, Callable


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


# Demo chapters matching the ChaosDemo stages
DEMO_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration=(
            "Welcome to the Operator Chaos Demo.\n\n"
            "This demo showcases autonomous fault detection and AI diagnosis.\n"
            "Watch the panels as the operator responds to infrastructure chaos."
        ),
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration=(
            "The operator first ensures the TiDB cluster is healthy.\n\n"
            "Watch the CLUSTER panel on the left for node status.\n"
            "All nodes should show UP before we proceed."
        ),
    ),
    Chapter(
        title="Stage 2: Load Generation",
        narration=(
            "YCSB is starting to generate write-heavy workload.\n\n"
            "This simulates real production traffic hitting the cluster.\n"
            "Watch the WORKLOAD panel for operation throughput."
        ),
    ),
    Chapter(
        title="Stage 3: Fault Injection",
        narration=(
            "Now we kill a random TiKV node to simulate failure.\n\n"
            "Watch the CLUSTER panel - one node will turn DOWN.\n"
            "The monitor will detect this invariant violation."
        ),
    ),
    Chapter(
        title="Stage 4: Detection",
        narration=(
            "The MONITOR is checking cluster health invariants.\n\n"
            "Watch for violation detection in the MONITOR panel.\n"
            "Detection typically takes 2-5 seconds."
        ),
    ),
    Chapter(
        title="Stage 5: AI Diagnosis",
        narration=(
            "Claude is now analyzing the violation.\n\n"
            "The AGENT panel shows diagnosis progress.\n"
            "AI correlates metrics, logs, and cluster state."
        ),
    ),
    Chapter(
        title="Demo Complete",
        narration=(
            "The demo is complete!\n\n"
            "The killed node has been restarted.\n"
            "Press Q to exit or SPACE to restart."
        ),
    ),
]


def create_fault_chapter(on_enter: Callable[[], Awaitable[None]]) -> Chapter:
    """
    Create fault injection chapter with countdown callback.

    Args:
        on_enter: Async callback to run countdown and fault injection

    Returns:
        Chapter configured for fault injection with callback
    """
    return Chapter(
        title="Stage 3: Fault Injection",
        narration=(
            "Countdown started...\n\n"
            "Watch the CLUSTER panel - one node will turn DOWN.\n"
            "The monitor will detect this invariant violation."
        ),
        on_enter=on_enter,
        blocks_advance=True,  # Don't allow advance during countdown
    )


def create_recovery_chapter(on_enter: Callable[[], Awaitable[None]]) -> Chapter:
    """
    Create recovery chapter with restart callback.

    Args:
        on_enter: Async callback to run node recovery

    Returns:
        Chapter configured for recovery with callback
    """
    return Chapter(
        title="Stage 6: Recovery",
        narration=(
            "Demo will now restart the killed node.\n"
            "[dim](Agent action execution coming in v2 — currently observe-only)[/dim]\n\n"
            "Watch the CLUSTER panel return to all green.\n"
            "Workload should recover to normal levels."
        ),
        on_enter=on_enter,
        auto_advance=True,  # Auto-advance after recovery
    )
