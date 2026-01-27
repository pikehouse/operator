"""
Main entry point for demo module.

Allows invoking demos via:
    python -m demo              # TiKV demo (default)
    python -m demo tikv         # TiKV demo (explicit)
    python -m demo ratelimiter  # Rate limiter demo

Routes to the appropriate TUI controller based on subject argument.
"""

import asyncio
import sys
from pathlib import Path


def usage() -> None:
    """Print usage message and exit."""
    print(
        """
Usage: python -m demo [tikv|ratelimiter]

Run the chaos demo with TUI integration for the specified subject.

Arguments:
  tikv         Run TiKV chaos demo (default)
  ratelimiter  Run Rate Limiter chaos demo

Examples:
  python -m demo              # Run TiKV demo
  python -m demo tikv         # Run TiKV demo
  python -m demo ratelimiter  # Run Rate Limiter demo

Requirements:
  - Docker Compose running appropriate cluster
  - ANTHROPIC_API_KEY environment variable
        """.strip()
    )


async def main() -> None:
    """
    Main entry point for demo module.

    Parses command line arguments, imports subject-specific configuration,
    and runs TUIDemoController with appropriate parameters.
    """
    # Parse command line
    subject = "tikv"  # Default
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--help", "-h"):
            usage()
            sys.exit(0)
        elif arg in ("tikv", "ratelimiter"):
            subject = arg
        else:
            print(f"Error: Invalid subject '{arg}'. Must be 'tikv' or 'ratelimiter'.")
            print()
            usage()
            sys.exit(1)

    # Import subject-specific modules
    if subject == "tikv":
        from demo.tikv import COMPOSE_FILE, TIKV_CHAPTERS, create_fault_chapter, create_load_chapter, create_recovery_chapter
        from demo.tikv_health import TiKVHealthPoller
        from demo.tui_integration import TUIDemoController

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

        # Create and run TUI demo
        controller = TUIDemoController(
            subject_name="tikv",
            chapters=chapters,
            health_poller=health_poller,
            compose_file=COMPOSE_FILE,
        )

    elif subject == "ratelimiter":
        from demo.ratelimiter import RATELIMITER_CHAPTERS
        from demo.ratelimiter_health import RateLimiterHealthPoller
        from demo.tui_integration import TUIDemoController

        # Create health poller
        health_poller = RateLimiterHealthPoller(
            endpoints=[
                "http://localhost:8001",
                "http://localhost:8002",
                "http://localhost:8003",
            ],
            poll_interval=2.0,
        )

        # Create TUI demo controller
        controller = TUIDemoController(
            subject_name="ratelimiter",
            chapters=RATELIMITER_CHAPTERS,
            health_poller=health_poller,
            compose_file=Path("docker/docker-compose.yml"),
        )

    else:
        # Should never reach here due to validation above
        print(f"Error: Unknown subject '{subject}'")
        sys.exit(1)

    # Run the demo
    try:
        await controller.run()
    except KeyboardInterrupt:
        print("\nDemo interrupted.")
    except Exception as e:
        print(f"\nDemo error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
