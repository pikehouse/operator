"""
Rate limiter demo chapters and chaos injection callbacks.

This module provides rate limiter-specific demo chapters and callbacks
for the TUI demo controller. It demonstrates the over-limit anomaly:
- Counter Drift: Injected entries cause counter to exceed its limit

Run via: python -m demo ratelimiter
"""

import asyncio

from demo.ratelimiter_chaos import (
    COUNTER_DRIFT_CONFIG,
    create_baseline_traffic,
    inject_redis_pause,
    setup_rate_limit,
    start_baseline_heartbeat,
)
from demo.status import demo_status
from demo.types import Chapter


# Demo configuration
DEMO_KEY = "demo-chaos-key"
DEMO_LIMIT = 10
DEMO_WINDOW = 60
TARGET_URLS = [
    "http://localhost:8001",
    "http://localhost:8002",
    "http://localhost:8003",
]


def create_setup_chapter(key: str, limit: int, window_sec: int) -> Chapter:
    """
    Create setup chapter that configures rate limit and baseline traffic.

    Args:
        key: Rate limit key to configure
        limit: Rate limit value
        window_sec: Time window in seconds

    Returns:
        Chapter that auto-advances after setup completes
    """

    async def setup() -> None:
        """Configure rate limit and create baseline traffic."""
        baseline_keys = ["api-users", "api-orders", "api-products"]
        chaos_key = "chaos-drift-demo"

        # Configure the rate limit
        await setup_rate_limit(
            target_url=TARGET_URLS[0],
            key=key,
            limit=limit,
            window_sec=window_sec,
        )
        # Create baseline traffic so workload panel shows healthy counters
        # Include chaos key with low count so it's visible before injection
        await create_baseline_traffic(
            keys=baseline_keys + [chaos_key],
            count_per_key=5,
            limit=limit,
        )
        # Start heartbeat to keep counters alive during demo (including chaos key)
        start_baseline_heartbeat(baseline_keys + [chaos_key], interval_sec=30.0)

    return Chapter(
        title="Stage 2: Setup",
        narration=f"""Creating baseline traffic ({limit} req/{window_sec}s limit)
Watch Workload panel → healthy counters appearing

[dim]Press SPACE when you see counters...[/dim]""",
        on_enter=setup,
    )


def create_counter_drift_chapter() -> Chapter:
    """
    Create counter drift chaos chapter.

    This chapter injects extra entries into Redis to simulate a sync bug
    that allowed more requests than the limit permits.

    Returns:
        Chapter that blocks advance during countdown and chaos injection
    """

    async def inject_chaos() -> None:
        """Countdown and inject counter drift chaos."""
        # Countdown before chaos
        for i in range(3, 0, -1):
            demo_status.set(f"[yellow]Injecting chaos in {i}...[/yellow]")
            await asyncio.sleep(1.0)

        demo_status.set("[bold red]INJECTING COUNTER DRIFT![/bold red]")
        await inject_redis_pause(duration_sec=COUNTER_DRIFT_CONFIG.duration_sec)
        demo_status.set("[green]Counter drift injected - check Workload panel[/green]")

    return Chapter(
        title="Stage 3: Injecting Chaos",
        narration="""[bold yellow]Over-Limit Injection[/bold yellow]
Simulates a sync bug that allowed requests past the limit

[dim]Watch Workload panel for OVER LIMIT counter...[/dim]""",
        on_enter=inject_chaos,
        blocks_advance=True,
        key_hint="[dim]Chaos in progress...[/dim]",
    )


# Rate limiter demo chapters - keep narrations SHORT (3-4 lines max)
RATELIMITER_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="""[bold cyan]Rate Limiter Chaos Demo[/bold cyan]

Demonstrating AI diagnosis of [bold]Over-Limit[/bold] anomaly

[dim]Press SPACE to begin...[/dim]""",
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="""3 rate limiter nodes + Redis + Prometheus
Watch the Cluster panel → all nodes should be [green]Up[/green]

[dim]Press SPACE to continue...[/dim]""",
    ),
    # Stage 2: Setup (creates baseline counters)
    create_setup_chapter(DEMO_KEY, DEMO_LIMIT, DEMO_WINDOW),
    # Stage 3: Counter Drift Chaos (blocks advance, on_enter)
    create_counter_drift_chapter(),
    Chapter(
        title="Stage 4: Detection",
        narration="""Watch Monitor panel → should show [bold red]violation(s) detected[/bold red]
Watch Workload panel → counter should show [bold red]OVER LIMIT[/bold red]

Next: Agent will diagnose and act automatically.""",
    ),
    Chapter(
        title="Stage 5: AI Remediation",
        narration="""Watch Agent panel for the complete agentic loop:
1. Diagnosis: AI identifies over-limit root cause
2. Action: reset_counter to fix the counter
3. Verify: Agent checks counter is back to normal

[dim]Autonomous remediation - no human approval.[/dim]""",
    ),
    Chapter(
        title="Stage 6: Recovery",
        narration="""Agent executed reset_counter, verifying fix...
Watch Agent panel for verification result.

[dim]Press SPACE when agent completes...[/dim]""",
    ),
    Chapter(
        title="Complete",
        narration="""[bold green]Demo Complete![/bold green]

AI diagnosed the over-limit anomaly using generic invariant checking.
No rate-limiter-specific prompts needed.

[dim]Press Q to quit[/dim]""",
    ),
]
