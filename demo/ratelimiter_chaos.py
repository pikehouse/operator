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
    Pause Redis write commands to simulate unavailability.

    Uses CLIENT PAUSE WRITE to block write commands while keeping
    replication working. This causes counter drift as rate limiter
    nodes can't update Redis state, but they continue accepting requests
    and storing counts in local memory.

    Args:
        duration_sec: Duration to pause Redis writes in seconds

    Example:
        # Pause Redis for 10 seconds
        await inject_redis_pause(duration_sec=10.0)
    """
    r = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)

    try:
        # CLIENT PAUSE <duration_ms> WRITE
        # WRITE mode: blocks write commands, allows reads
        duration_ms = int(duration_sec * 1000)
        await r.execute_command("CLIENT", "PAUSE", duration_ms, "WRITE")

    finally:
        await r.aclose()


async def inject_burst_traffic(
    target_urls: list[str],
    key: str,
    limit: int,
    multiplier: int = 2,
) -> dict[str, int]:
    """
    Send burst traffic to trigger ghost allowing.

    Sends burst_count = limit * multiplier requests concurrently
    to overwhelm the rate limiter. This can trigger ghost allowing
    when the distributed counter becomes inconsistent.

    Args:
        target_urls: List of rate limiter endpoints to target
        key: Rate limit key to test
        limit: Known limit for the key
        multiplier: How many times over limit to burst (default 2x)

    Returns:
        Dict with keys "allowed" and "denied" containing counts

    Example:
        # Send 20 requests to a key with limit 10
        result = await inject_burst_traffic(
            target_urls=["http://localhost:8001"],
            key="demo-key",
            limit=10,
            multiplier=2,
        )
        print(f"Allowed: {result['allowed']}, Denied: {result['denied']}")
    """
    burst_count = limit * multiplier

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Send all requests concurrently
        tasks = []
        for i in range(burst_count):
            # Round-robin across targets
            target_url = target_urls[i % len(target_urls)]
            task = client.post(
                f"{target_url}/check",
                json={"key": key},
            )
            tasks.append(task)

        # Gather all responses
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Count allowed (200) vs denied (429)
        allowed = sum(
            1
            for r in responses
            if not isinstance(r, Exception) and r.status_code == 200
        )
        denied = sum(
            1
            for r in responses
            if not isinstance(r, Exception) and r.status_code == 429
        )

        return {"allowed": allowed, "denied": denied}


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
        response = await client.post(
            f"{target_url}/limit",
            json={
                "key": key,
                "limit": limit,
                "window_sec": window_sec,
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
