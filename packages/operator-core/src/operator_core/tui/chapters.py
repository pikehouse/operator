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
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    """
    Immutable chapter definition.

    Each chapter represents a stage in the demo with narration
    explaining what is happening and what to watch for.
    """

    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"


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
