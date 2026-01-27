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
        narration=f"""Setting up rate limiter demo...

- Configuring rate limit: {limit} requests per {window_sec}s
- Creating baseline traffic for workload display

[dim]Watch the Workload panel for healthy counters...[/dim]""",
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
        title="Stage 3: Counter Drift Chaos",
        narration=f"""
[bold yellow]{COUNTER_DRIFT_CONFIG.name}[/bold yellow]

{COUNTER_DRIFT_CONFIG.description}

Redis will be paused for {COUNTER_DRIFT_CONFIG.duration_sec}s. During this time,
rate limiter nodes cannot update counters in Redis, but they continue
accepting requests. This creates counter drift between nodes and Redis.

[dim]Countdown will begin automatically...[/dim]
        """.strip(),
        on_enter=inject_chaos,
        blocks_advance=True,
        key_hint="[dim]Chaos in progress... please wait[/dim]",
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
        title="Stage 7: Ghost Allowing Chaos",
        narration=f"""
[bold yellow]{GHOST_ALLOWING_CONFIG.name}[/bold yellow]

{GHOST_ALLOWING_CONFIG.description}

Sending {limit * GHOST_ALLOWING_CONFIG.burst_multiplier} concurrent requests (2x limit) to trigger
ghost allowing. This creates a race condition where the distributed
counter becomes inconsistent, potentially allowing requests when limit is 0.

[dim]Countdown will begin automatically...[/dim]
        """.strip(),
        on_enter=inject_chaos,
        blocks_advance=True,
        key_hint="[dim]Chaos in progress... please wait[/dim]",
    )


# Rate limiter demo chapters
RATELIMITER_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="""
[bold cyan]Rate Limiter Chaos Demo[/bold cyan]

This demo showcases the operator's ability to diagnose rate limiter
anomalies using generic invariant checking and AI reasoning.

We'll demonstrate TWO distinct failure modes:
1. [bold]Counter Drift[/bold] - Redis pause causes distributed counter inconsistency
2. [bold]Ghost Allowing[/bold] - Burst traffic triggers allowing with limit=0

The operator will detect and diagnose both anomalies without any
rate limiter-specific prompts in the core reasoning engine.

[dim]Press SPACE to begin...[/dim]
        """.strip(),
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="""
[bold]Checking Rate Limiter Cluster[/bold]

The cluster consists of:
- 3 rate limiter nodes (ports 8001-8003)
- 1 Redis instance (shared state)
- Prometheus for metrics

Each node maintains a distributed counter for rate limiting using
a sliding window algorithm backed by Redis sorted sets.

[dim]Press SPACE to continue...[/dim]
        """.strip(),
    ),
    # Stage 2: Setup (auto-advances)
    create_setup_chapter(DEMO_KEY, DEMO_LIMIT, DEMO_WINDOW),
    # Stage 3: Counter Drift Chaos (blocks advance, on_enter)
    create_counter_drift_chapter(),
    Chapter(
        title="Stage 4: Counter Drift Detection",
        narration="""
[bold]Waiting for Counter Drift Detection[/bold]

The operator's invariant checker is monitoring for counter drift between
nodes and Redis. Counter drift occurs when:
- Nodes report different counter values than Redis
- Drift exceeds threshold after grace period

Watch the health panel for counter inconsistencies...

[dim]Press SPACE when anomaly is detected...[/dim]
        """.strip(),
    ),
    Chapter(
        title="Stage 5: Counter Drift Diagnosis",
        narration="""
[bold]AI Diagnosis: Counter Drift[/bold]

The AI will now analyze the counter drift anomaly and provide a diagnosis.

The AI has access to:
- Node counter values from management API
- Redis counter values from direct Redis queries
- Recent metric history from Prometheus
- Invariant violation details

[dim]AI diagnosis will appear here...[/dim]

[dim]Press SPACE to continue...[/dim]
        """.strip(),
    ),
    Chapter(
        title="Stage 6: Recovery",
        narration="""
[bold]Waiting for Recovery[/bold]

Redis CLIENT PAUSE expires automatically after the configured duration.
Counters will resync as nodes resume writing to Redis.

[dim]Waiting for system to stabilize...[/dim]
        """.strip(),
        auto_advance=True,
    ),
    # Stage 7: Ghost Allowing Chaos (blocks advance, on_enter)
    create_ghost_allowing_chapter(DEMO_KEY, DEMO_LIMIT),
    Chapter(
        title="Stage 8: Ghost Allowing Detection",
        narration="""
[bold]Waiting for Ghost Allowing Detection[/bold]

The operator's invariant checker is monitoring for ghost allowing.
Ghost allowing occurs when:
- Counter value is 0 or very low
- Requests are still being allowed (not denied)

This indicates a race condition in the distributed counter logic.

[dim]Press SPACE when anomaly is detected...[/dim]
        """.strip(),
    ),
    Chapter(
        title="Stage 9: Ghost Allowing Diagnosis",
        narration="""
[bold]AI Diagnosis: Ghost Allowing[/bold]

The AI will now analyze the ghost allowing anomaly and provide a diagnosis.

The AI has access to:
- Current counter state across all nodes
- Recent request patterns from metrics
- Allowed vs denied request counts
- Invariant violation details

[dim]AI diagnosis will appear here...[/dim]

[dim]Press SPACE to continue...[/dim]
        """.strip(),
    ),
    Chapter(
        title="Demo Complete",
        narration="""
[bold green]Rate Limiter Chaos Demo Complete![/bold green]

You've witnessed the operator detect and diagnose TWO distinct
rate limiter anomalies:

1. [bold]Counter Drift[/bold] - Caused by Redis pause, detected via counter inconsistency
2. [bold]Ghost Allowing[/bold] - Caused by burst traffic, detected via allowing with low limit

Both were diagnosed using:
- Generic invariant checking (no rate limiter-specific logic in core)
- AI reasoning over observations (no system-specific prompts)
- Protocol-based abstractions (same patterns as TiKV)

This demonstrates that the operator can reason about novel distributed
systems without hardcoded knowledge of their internals.

[dim]Press Q to quit[/dim]
        """.strip(),
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
