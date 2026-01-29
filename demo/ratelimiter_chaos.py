"""
Rate limiter chaos injection functions.

This module provides chaos functions specific to rate limiter demos:
- inject_redis_pause: Injects over-limit counter to simulate sync bug
- setup_rate_limit: Helper to configure a rate limit before testing
- create_baseline_traffic: Creates healthy counters for demo visualization

These functions demonstrate failure modes that the operator
should detect and diagnose through invariant checking.
"""

import time

import httpx
import redis.asyncio as aioredis

from demo.status import demo_status
from demo.types import ChaosConfig, ChaosType


async def inject_redis_pause(duration_sec: float = 5.0) -> None:
    """
    Inject a counter drift anomaly by manipulating Redis behind the rate limiter's back.

    Creates a counter via the API, then injects extra entries directly into Redis
    to simulate a sync bug or race condition that allowed more requests than the limit.

    This creates a TRUE over-limit violation (count > limit) that the monitor can detect.

    Args:
        duration_sec: Not used (kept for API compatibility)

    Example:
        await inject_redis_pause(duration_sec=10.0)
    """
    demo_status.set("[dim]Injecting counter drift...[/dim]")

    key = "chaos-drift-demo"
    limit = 10
    target_url = "http://localhost:8001"

    async with httpx.AsyncClient(timeout=5.0) as client:
        # 1. Set a limit for the key (10 min window so it persists during demo)
        await client.put(
            f"{target_url}/api/limits/{key}",
            json={"limit": limit, "window_ms": 600000},
        )

        # 2. Create some baseline traffic via API (5 requests)
        for _ in range(5):
            try:
                await client.post(f"{target_url}/check", json={"key": key})
            except Exception:
                pass

    # 3. Inject extra entries directly into Redis to push counter over limit
    # This simulates a sync bug where Redis has more entries than it should
    r = aioredis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    try:
        redis_key = f"ratelimit:{key}"
        now_ms = int(time.time() * 1000)

        # Add 10 extra entries (5 from API + 10 injected = 15 total, limit is 10)
        for i in range(10):
            member = f"{now_ms}:drift-injected-{i}"
            await r.zadd(redis_key, {member: now_ms})

        # Verify the injection worked
        count = await r.zcard(redis_key)
        demo_status.set(f"Counter drift injected: {count} entries (limit: {limit})")

    finally:
        await r.aclose()


async def create_baseline_traffic(
    keys: list[str],
    count_per_key: int = 5,
    limit: int = 10,
    window_ms: int = 600000,  # 10 minutes - long enough for demo to complete
) -> None:
    """
    Create baseline traffic through the rate limiter.

    Sends requests through the rate limiter's /check endpoint to create
    real counters at healthy levels (below limit).

    Args:
        keys: List of rate limit keys to create traffic for
        count_per_key: Number of requests per key (should be < limit)
        limit: The limit to configure for each key
        window_ms: Sliding window size in ms (default 5 min for demo persistence)
    """
    demo_status.set(f"[dim]Creating {len(keys)} baseline counters...[/dim]")

    target_urls = [
        "http://localhost:8001",
        "http://localhost:8002",
        "http://localhost:8003",
    ]

    async with httpx.AsyncClient(timeout=5.0) as client:
        for key in keys:
            # Set limit for the key (use longer window so counters persist during demo)
            await client.put(
                f"{target_urls[0]}/api/limits/{key}",
                json={"limit": limit, "window_ms": window_ms},
            )

            # Send requests to create counter (below limit)
            for i in range(count_per_key):
                try:
                    url = target_urls[i % len(target_urls)]
                    await client.post(
                        f"{url}/check",
                        json={"key": key},
                    )
                except Exception:
                    pass  # Ignore individual failures

        demo_status.set(f"Created {len(keys)} baseline counters ({count_per_key}/{limit} each)")


async def setup_rate_limit(
    target_url: str,
    key: str,
    limit: int,
    window_sec: int = 60,
) -> None:
    """
    Set up a rate limit for a key before testing.

    Configures a known rate limit via the management API so that
    chaos injection can reliably trigger anomalies.

    Args:
        target_url: Rate limiter management API URL
        key: Rate limit key to configure
        limit: Rate limit value (requests per window)
        window_sec: Time window in seconds (default 60)

    Example:
        # Configure demo-key with limit of 10 requests per 60 seconds
        await setup_rate_limit(
            target_url="http://localhost:8001",
            key="demo-key",
            limit=10,
        )
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # PUT /api/limits/{key} with limit and window_ms
        response = await client.put(
            f"{target_url}/api/limits/{key}",
            json={
                "limit": limit,
                "window_ms": window_sec * 1000,
            },
        )
        response.raise_for_status()


# Counter drift chaos configuration
COUNTER_DRIFT_CONFIG = ChaosConfig(
    name="Counter Drift",
    chaos_type=ChaosType.REDIS_PAUSE,
    description="Inject over-limit counter to simulate sync bug",
    duration_sec=10.0,
)
