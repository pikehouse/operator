"""
TiKV demo entry point with chapter-based chaos demonstration.

This module provides the TiKV-specific demo entry point using the shared
demo framework. It defines chapters matching the existing TUI flow and
wires in TiKV-specific health polling and chaos injection.

Usage:
    python -m demo.tikv
"""

import asyncio
from pathlib import Path

from demo.runner import DemoRunner
from demo.tikv_chaos import kill_random_tikv, restart_container, start_ycsb_load
from demo.tikv_health import TiKVHealthPoller
from demo.types import Chapter


# Path to TiKV docker-compose file
COMPOSE_FILE = Path(__file__).parent.parent / "subjects" / "tikv" / "docker-compose.yaml"

# Track killed container for recovery
_killed_container: str | None = None


def create_load_chapter(compose_file: Path) -> Chapter:
    """
    Create load generation chapter that starts YCSB.

    Args:
        compose_file: Path to docker-compose.yaml

    Returns:
        Chapter configured to start YCSB load on enter
    """

    async def on_enter() -> None:
        """Start YCSB load generation."""
        await start_ycsb_load(compose_file)
        await asyncio.sleep(2.0)

    return Chapter(
        title="Stage 2: Load Generation",
        narration=(
            "Starting YCSB workload (50% reads, 50% updates)\n"
            "Watch the Workload panel for ops/sec\n\n"
            "[dim]Loading data and starting traffic...[/dim]"
        ),
        on_enter=on_enter,
        auto_advance=True,
    )


def create_fault_chapter(compose_file: Path) -> Chapter:
    """
    Create fault injection chapter with countdown and node kill.

    Args:
        compose_file: Path to docker-compose.yaml

    Returns:
        Chapter configured for fault injection with countdown callback
    """

    async def on_enter() -> None:
        """Run countdown then kill random TiKV node."""
        global _killed_container

        # Countdown
        for i in range(3, 0, -1):
            print(f"Injecting fault in {i}...")
            await asyncio.sleep(1.0)

        print("FAULT INJECTED!")

        # Kill random TiKV
        container = await kill_random_tikv(compose_file)
        if container:
            _killed_container = container
            print(f"Killed container: {container}")
        else:
            print("No TiKV containers found to kill!")

        await asyncio.sleep(1.0)

    return Chapter(
        title="Stage 4: Fault Injection",
        narration=(
            "Countdown started...\n\n"
            "Watch the cluster health - one TiKV node will be killed.\n"
            "The monitor will detect this invariant violation."
        ),
        on_enter=on_enter,
        blocks_advance=True,
    )


def create_recovery_chapter(compose_file: Path) -> Chapter:
    """
    Create recovery chapter with node restart.

    Args:
        compose_file: Path to docker-compose.yaml

    Returns:
        Chapter configured for recovery with restart callback
    """

    async def on_enter() -> None:
        """Restart the killed container."""
        global _killed_container

        if _killed_container:
            print(f"Restarting container: {_killed_container}")
            success = await restart_container(compose_file, _killed_container)
            if success:
                print(f"Container {_killed_container} restarted!")
                _killed_container = None
            else:
                print("Failed to restart container!")
        else:
            print("No container to restart!")

        await asyncio.sleep(2.0)

    return Chapter(
        title="Stage 7: Recovery",
        narration=(
            "Demo will now restart the killed node.\n"
            "[dim](Agent action execution coming in v2 — currently observe-only)[/dim]\n\n"
            "Watch the cluster health return to all green.\n"
            "Workload should recover to normal levels."
        ),
        on_enter=on_enter,
        auto_advance=True,
    )


# TiKV demo chapters matching existing TUI flow
TIKV_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration=(
            "Welcome to the TiKV Operator Demo.\n\n"
            "This demo showcases autonomous fault detection and AI diagnosis.\n"
            "Watch as the operator responds to infrastructure chaos."
        ),
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration=(
            "The operator first ensures the TiDB cluster is healthy.\n\n"
            "All TiKV stores and PD members should show UP status.\n"
            "Press SPACE to continue when ready."
        ),
    ),
    # Stage 2: Load Generation - added dynamically in main()
    # Stage 3: Fault Injection - added dynamically in main()
    Chapter(
        title="Stage 5: Detection",
        narration=(
            "The MONITOR is checking cluster health invariants.\n\n"
            "Watch for violation detection in monitor output.\n"
            "Detection typically takes 2-5 seconds."
        ),
    ),
    Chapter(
        title="Stage 6: AI Diagnosis",
        narration=(
            "Claude is now analyzing the violation.\n\n"
            "The AI correlates metrics, logs, and cluster state.\n"
            "Diagnosis provides root cause and recommended actions."
        ),
    ),
    # Recovery chapter added dynamically in main()
    Chapter(
        title="Stage 8: Complete",
        narration=(
            "The demo is complete!\n\n"
            "The killed node has been restarted.\n"
            "Press Q to exit or SPACE to restart."
        ),
    ),
]


async def main() -> None:
    """
    Run the TiKV demo.

    Creates health poller, assembles chapters (including fault/recovery),
    and runs the demo using DemoRunner.
    """
    # Create health poller
    health_poller = TiKVHealthPoller(
        pd_endpoint="http://localhost:2379",
        poll_interval=2.0,
    )

    # Assemble chapters with load, fault, and recovery
    chapters = [
        TIKV_CHAPTERS[0],  # Welcome
        TIKV_CHAPTERS[1],  # Cluster Health
        create_load_chapter(COMPOSE_FILE),  # Load Generation (starts YCSB)
        create_fault_chapter(COMPOSE_FILE),  # Fault Injection (kills node)
        TIKV_CHAPTERS[2],  # Detection
        TIKV_CHAPTERS[3],  # AI Diagnosis
        create_recovery_chapter(COMPOSE_FILE),  # Recovery (restarts node)
        TIKV_CHAPTERS[4],  # Complete
    ]

    # Create and run demo
    runner = DemoRunner(
        subject_name="TiKV",
        chapters=chapters,
        health_poller=health_poller,
    )

    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
