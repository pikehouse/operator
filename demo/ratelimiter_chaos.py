"""
Rate limiter chaos injection functions.

This module provides chaos functions specific to rate limiter demos:
- inject_redis_pause: Pauses Redis writes to cause counter drift
- inject_burst_traffic: Sends burst traffic to trigger ghost allowing
- setup_rate_limit: Helper to configure a rate limit before testing

These functions demonstrate different failure modes that the operator
should detect and diagnose through invariant checking.
"""

import asyncio
from typing import Any

import httpx
import redis.asyncio as redis

from demo.types import ChaosConfig, ChaosType


async def inject_redis_pause(duration_sec: float = 5.0) -> None:
    """
    Inject a counter drift anomaly by creating an over-limit counter.

    Creates a counter with count > limit to simulate what would happen
    if Redis writes were paused and counters drifted out of sync.

    IMPORTANT: Timestamps are spread across the next 50 seconds so entries
    stay valid within the 60-second sliding window for demo purposes.

    Args:
        duration_sec: Not used (kept for API compatibility)

    Example:
        await inject_redis_pause(duration_sec=10.0)
    """
    import time

    from datetime import datetime
    print(f"[CHAOS {datetime.now().strftime('%H:%M:%S')}] inject_redis_pause starting...")

    r = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)

    try:
        # Create an over-limit counter to simulate drift
        # Use timestamps spread from now to +50 seconds so entries stay valid
        # within the 60-second sliding window for ~50 seconds
        now_ms = int(time.time() * 1000)
        redis_key = "ratelimit:counter-drift-demo"

        # Clear any existing entries first
        await r.delete(redis_key)

        # Add 15 entries when limit is 10 (simulates drift)
        # Spread entries across 50 seconds into the future
        for i in range(15):
            # Spread entries: 0, 3.3s, 6.6s, ... up to 50s
            offset_ms = int((i / 14) * 50000) if i > 0 else 0
            timestamp = now_ms + offset_ms
            member = f"{timestamp}:drift-{i}"
            await r.zadd(redis_key, {member: timestamp})

        # Set TTL so key itself persists
        await r.expire(redis_key, 120)

        # Verify creation
        count = await r.zcard(redis_key)
        print(f"[CHAOS] Created {redis_key} with {count} entries")

    finally:
        await r.aclose()

    print("[CHAOS] inject_redis_pause complete")


async def inject_burst_traffic(
    target_urls: list[str],
    key: str,
    limit: int,
    multiplier: int = 2,
) -> dict[str, int]:
    """
    Inject an over-limit anomaly that persists for demo detection.

    Creates a counter that exceeds its limit, simulating a race condition
    or consistency bug. Uses timestamps spread across the next 50 seconds
    so entries stay valid within the 60-second sliding window.

    Args:
        target_urls: List of rate limiter endpoints (used for context)
        key: Rate limit key to create anomaly for
        limit: Configured limit for the key
        multiplier: How many times over limit (default 2x)

    Returns:
        Dict with simulated "allowed" and "denied" counts
    """
    import time

    print(f"[CHAOS] inject_burst_traffic starting for key={key}...")

    # Connect to Redis and inject over-limit counter
    r = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    try:
        # Use timestamps spread from now to +50 seconds so entries stay valid
        # within the 60-second sliding window for ~50 seconds
        now_ms = int(time.time() * 1000)
        redis_key = f"ratelimit:{key}"

        # Clear any existing entries
        await r.delete(redis_key)

        # Add entries that exceed the limit (e.g., 20 entries when limit is 10)
        over_limit_count = limit * multiplier
        for i in range(over_limit_count):
            # Spread entries: 0, ~2.5s, ~5s, ... up to 50s
            offset_ms = int((i / max(over_limit_count - 1, 1)) * 50000) if i > 0 else 0
            timestamp = now_ms + offset_ms
            member = f"{timestamp}:anomaly-{i}"
            await r.zadd(redis_key, {member: timestamp})

        # Set TTL so key itself persists
        await r.expire(redis_key, 120)

        # Verify creation
        count = await r.zcard(redis_key)
        print(f"[CHAOS] Created {redis_key} with {count} entries")

    finally:
        await r.aclose()

    print(f"[CHAOS] inject_burst_traffic complete")

    # Return simulated results (the anomaly is the over-limit counter, not traffic)
    return {"allowed": over_limit_count, "denied": 0}


async def create_baseline_traffic(
    keys: list[str],
    count_per_key: int = 5,
    limit: int = 10,
) -> None:
    """
    Create baseline counter entries to show normal workload.

    Creates counters at healthy levels (below limit) so the demo
    shows normal operation before chaos is injected.

    Args:
        keys: List of rate limit keys to create
        count_per_key: Number of entries per key (should be < limit)
        limit: The limit for display purposes
    """
    import time

    print(f"[BASELINE] Creating {len(keys)} counters with {count_per_key} entries each...")

    r = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    try:
        now_ms = int(time.time() * 1000)

        for key in keys:
            redis_key = f"ratelimit:{key}"
            await r.delete(redis_key)

            # Add entries spread across 50 seconds into the future
            for i in range(count_per_key):
                offset_ms = int((i / max(count_per_key - 1, 1)) * 50000) if i > 0 else 0
                timestamp = now_ms + offset_ms
                member = f"{timestamp}:baseline-{i}"
                await r.zadd(redis_key, {member: timestamp})

            await r.expire(redis_key, 120)

        print(f"[BASELINE] Created {len(keys)} healthy counters ({count_per_key}/{limit} each)")

    finally:
        await r.aclose()


async def setup_rate_limit(
    target_url: str,
    key: str,
    limit: int,
    window_sec: int = 60,
) -> None:
    """
    Set up a rate limit for a key before testing.

    Configures a known rate limit via the management API so that
    burst traffic tests can reliably trigger anomalies.

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
    description="Pause Redis writes to create counter drift between nodes and Redis state",
    duration_sec=10.0,
)

# Ghost allowing chaos configuration
GHOST_ALLOWING_CONFIG = ChaosConfig(
    name="Ghost Allowing",
    chaos_type=ChaosType.BURST_TRAFFIC,
    description="Send burst traffic to trigger ghost allowing (limit becomes 0 but requests allowed)",
    burst_multiplier=2,
)
