"""
Rate limiter chaos demo entry point.

This demo showcases the operator's ability to diagnose rate limiter
anomalies using the same generic infrastructure as the TiKV demo.

The demo demonstrates TWO distinct anomaly types:
1. Counter Drift: Redis PAUSE causes distributed counter to drift
2. Ghost Allowing: Burst traffic triggers allowing with limit=0

Each anomaly is injected via chaos, detected by invariant checking,
and diagnosed by AI reasoning - all without system-specific prompts.
"""

import asyncio

from demo.ratelimiter_chaos import (
    COUNTER_DRIFT_CONFIG,
    GHOST_ALLOWING_CONFIG,
    create_baseline_traffic,
    inject_burst_traffic,
    inject_redis_pause,
    setup_rate_limit,
)
from demo.ratelimiter_health import RateLimiterHealthPoller
from demo.runner import DemoRunner
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
        # Configure the rate limit
        await setup_rate_limit(
            target_url=TARGET_URLS[0],
            key=key,
            limit=limit,
            window_sec=window_sec,
        )
        # Create baseline traffic so workload panel shows healthy counters
        await create_baseline_traffic(
            keys=["api-users", "api-orders", "api-products"],
            count_per_key=5,
            limit=limit,
        )

    return Chapter(
        title="Stage 2: Setup",
        narration=f"""Creating baseline traffic ({limit} req/{window_sec}s limit)
Watch Workload panel → healthy counters appearing

[dim]Auto-advancing...[/dim]""",
        on_enter=setup,
        auto_advance=True,
    )


def create_counter_drift_chapter() -> Chapter:
    """
    Create counter drift chaos chapter.

    This chapter pauses Redis writes for 10 seconds, causing the
    distributed counter to drift as nodes can't sync with Redis.

    Returns:
        Chapter that blocks advance during countdown and chaos injection
    """

    async def inject_chaos() -> None:
        """Countdown and inject Redis PAUSE chaos."""
        # Countdown before chaos
        for i in range(3, 0, -1):
            demo_status.set(f"[yellow]Injecting chaos in {i}...[/yellow]")
            await asyncio.sleep(1.0)

        demo_status.set("[bold red]INJECTING REDIS PAUSE![/bold red]")
        await inject_redis_pause(duration_sec=COUNTER_DRIFT_CONFIG.duration_sec)
        demo_status.set("[green]Redis pause complete[/green]")

    return Chapter(
        title="Stage 3: Injecting Chaos",
        narration=f"""[bold yellow]Counter Drift[/bold yellow] - Creating over-limit counter
Simulates Redis sync failure causing counter inconsistency

[dim]Injecting...[/dim]""",
        on_enter=inject_chaos,
        blocks_advance=True,
        key_hint="[dim]Chaos in progress...[/dim]",
    )


def create_ghost_allowing_chapter(key: str, limit: int) -> Chapter:
    """
    Create ghost allowing chaos chapter.

    This chapter sends burst traffic (2x limit) to trigger ghost allowing,
    where the limit becomes 0 but requests are still allowed.

    Args:
        key: Rate limit key to burst
        limit: Known limit for the key

    Returns:
        Chapter that blocks advance during burst traffic
    """

    async def inject_chaos() -> None:
        """Countdown and inject burst traffic chaos."""
        # Countdown before chaos
        for i in range(3, 0, -1):
            demo_status.set(f"[yellow]Injecting chaos in {i}...[/yellow]")
            await asyncio.sleep(1.0)

        demo_status.set("[bold red]INJECTING BURST TRAFFIC![/bold red]")
        result = await inject_burst_traffic(
            target_urls=TARGET_URLS,
            key=key,
            limit=limit,
            multiplier=GHOST_ALLOWING_CONFIG.burst_multiplier,
        )
        demo_status.set(
            f"[green]Burst complete: {result['allowed']} allowed, {result['denied']} denied (expected {limit} allowed)[/green]"
        )

    return Chapter(
        title="Stage 7: Injecting Chaos",
        narration=f"""[bold yellow]Ghost Allowing[/bold yellow] - Burst traffic (2x limit)
Simulates race condition allowing requests past limit

[dim]Injecting...[/dim]""",
        on_enter=inject_chaos,
        blocks_advance=True,
        key_hint="[dim]Chaos in progress...[/dim]",
    )


# Rate limiter demo chapters - keep narrations SHORT (3-4 lines max)
RATELIMITER_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="""[bold cyan]Rate Limiter Chaos Demo[/bold cyan]

Demonstrating AI diagnosis of: [bold]Counter Drift[/bold] and [bold]Ghost Allowing[/bold]

[dim]Press SPACE to begin...[/dim]""",
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="""3 rate limiter nodes + Redis + Prometheus
Watch the Cluster panel → all nodes should be [green]Up[/green]

[dim]Press SPACE to continue...[/dim]""",
    ),
    # Stage 2: Setup (auto-advances)
    create_setup_chapter(DEMO_KEY, DEMO_LIMIT, DEMO_WINDOW),
    # Stage 3: Counter Drift Chaos (blocks advance, on_enter)
    create_counter_drift_chapter(),
    Chapter(
        title="Stage 4: Detection",
        narration="""Watch Monitor panel → should show [bold red]violation(s) detected[/bold red]
Watch Workload panel → counter should show [bold red]OVER LIMIT[/bold red]

[dim]Press SPACE when you see the violation...[/dim]""",
    ),
    Chapter(
        title="Stage 5: AI Diagnosis",
        narration="""Watch Agent panel → AI analyzing the anomaly
The AI sees: counters, nodes, metrics, violation details

[dim]Press SPACE to continue...[/dim]""",
    ),
    Chapter(
        title="Stage 6: Recovery",
        narration="""System recovering... counters resyncing with Redis

[dim]Auto-advancing...[/dim]""",
        auto_advance=True,
    ),
    # Stage 7: Ghost Allowing Chaos (blocks advance, on_enter)
    create_ghost_allowing_chapter(DEMO_KEY, DEMO_LIMIT),
    Chapter(
        title="Stage 8: Detection",
        narration="""Watch Monitor panel → new violation detected
Counter exceeds limit due to burst traffic race condition

[dim]Press SPACE when you see the violation...[/dim]""",
    ),
    Chapter(
        title="Stage 9: AI Diagnosis",
        narration="""Watch Agent panel → AI diagnosing ghost allowing
Same generic reasoning, different anomaly type

[dim]Press SPACE to continue...[/dim]""",
    ),
    Chapter(
        title="Complete",
        narration="""[bold green]Demo Complete![/bold green]

AI diagnosed both anomalies using generic invariant checking.
No rate-limiter-specific prompts needed.

[dim]Press Q to quit[/dim]""",
    ),
]


async def main() -> None:
    """
    Run the rate limiter chaos demo.

    Creates health poller, defines chapters, and starts the demo runner.
    """
    # Create health poller
    health_poller = RateLimiterHealthPoller(
        endpoints=TARGET_URLS,
        poll_interval=2.0,
    )

    # Create demo runner
    runner = DemoRunner(
        subject_name="Rate Limiter",
        chapters=RATELIMITER_CHAPTERS,
        health_poller=health_poller,
    )

    # Run demo
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
