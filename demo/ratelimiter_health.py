"""
Rate limiter health poller for demo infrastructure.

This module provides RateLimiterHealthPoller, which implements the
HealthPollerProtocol to poll rate limiter management APIs and Redis
connectivity status.

The poller queries the /nodes endpoint to check node registration and
the /health endpoint to verify Redis connectivity, storing the latest
health snapshot for the demo TUI to display.
"""

import asyncio
from datetime import datetime
from typing import Any

import httpx
import redis.asyncio as redis


class RateLimiterHealthPoller:
    """
    Health poller for rate limiter cluster.

    Implements HealthPollerProtocol by polling rate limiter management
    API endpoints and storing the latest health snapshot.

    The poller checks:
    - /nodes: List of registered nodes with state
    - /health: Redis connectivity status

    Health snapshot includes:
    - nodes: List of dicts with id, address, state
    - redis_connected: Boolean from health check
    - has_issues: Boolean (any node not "Up" OR Redis disconnected)
    - last_updated: datetime of last successful poll

    Attributes:
        endpoints: List of rate limiter management API URLs
        poll_interval: Seconds between polls (default 2.0)
    """

    def __init__(
        self,
        endpoints: list[str] | None = None,
        poll_interval: float = 2.0,
    ):
        """
        Initialize rate limiter health poller.

        Args:
            endpoints: List of rate limiter API URLs. Defaults to localhost:8001-8003
            poll_interval: Seconds between health polls
        """
        self.endpoints = endpoints or [
            "http://localhost:8001",
            "http://localhost:8002",
            "http://localhost:8003",
        ]
        self.poll_interval = poll_interval
        self._health: dict[str, Any] | None = None
        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._redis_url = "redis://localhost:6379"

    async def run(self) -> None:
        """
        Run continuous health polling in background.

        Polls the first reachable endpoint every poll_interval seconds
        until stop() is called. Stores latest health snapshot in _health.
        """
        self._running = True
        self._client = httpx.AsyncClient(timeout=5.0)

        try:
            while self._running:
                await self._poll_health()
                await asyncio.sleep(self.poll_interval)
        finally:
            if self._client:
                await self._client.aclose()

    def get_health(self) -> dict[str, Any] | None:
        """
        Get latest health snapshot.

        Returns:
            Health data dict with keys: nodes, redis_connected, has_issues, last_updated
            Returns None if no successful poll yet
        """
        return self._health

    def stop(self) -> None:
        """
        Stop health polling and clean up resources.

        Sets _running flag to False, causing run() to exit gracefully.
        """
        self._running = False

    async def _poll_health(self) -> None:
        """
        Poll health from first reachable endpoint.

        Tries each endpoint until one succeeds, then queries /nodes and /health.
        Updates _health with snapshot or sets has_issues=True on failure.
        """
        if not self._client:
            return

        # Try endpoints until one works
        for endpoint in self.endpoints:
            try:
                # Query nodes list (under /api prefix)
                nodes_response = await self._client.get(f"{endpoint}/api/nodes")
                nodes_response.raise_for_status()
                nodes_data = nodes_response.json()

                # Query health status
                health_response = await self._client.get(f"{endpoint}/health")
                health_response.raise_for_status()
                health_data = health_response.json()

                # Parse health snapshot
                nodes = nodes_data.get("nodes", [])
                # Redis is connected if service is healthy (status="healthy")
                redis_connected = health_data.get("status") == "healthy"

                # Poll counter stats from Redis
                counters = await self._poll_counters()

                # Check for issues
                has_issues = not redis_connected or any(
                    node.get("state") != "Up" for node in nodes
                )

                # Store snapshot
                self._health = {
                    "nodes": nodes,
                    "redis_connected": redis_connected,
                    "has_issues": has_issues,
                    "last_updated": datetime.now(),
                    "counters": counters,
                }

                # Success - don't try other endpoints
                return

            except (httpx.HTTPError, Exception):
                # This endpoint failed, try next one
                continue

        # All endpoints failed - set has_issues
        self._health = {
            "nodes": [],
            "redis_connected": False,
            "has_issues": True,
            "last_updated": datetime.now(),
            "counters": [],
        }

    async def _poll_counters(self) -> list[dict[str, Any]]:
        """
        Poll Redis for counter statistics.

        Scans for ratelimit:* keys (sorted sets only) and returns count vs limit.
        Fetches actual configured limits from ratelimit:limit:{key} hashes.

        Returns:
            List of dicts with key, count, limit, over_limit
        """
        import time

        counters = []
        try:
            r = redis.Redis.from_url(self._redis_url, decode_responses=True)
            try:
                now_ms = int(time.time() * 1000)

                # Scan for rate limit keys, collecting sorted sets until we have 10
                async for key in r.scan_iter(match="ratelimit:*"):
                    # Skip limit config keys and loadgen sequence keys
                    if ":limit:" in key or ":seq" in key:
                        continue

                    # Check key type - only process sorted sets
                    key_type = await r.type(key)
                    if key_type != "zset":
                        continue

                    # Get the key name without prefix
                    key_name = key.replace("ratelimit:", "")

                    # Fetch configured limit from ratelimit:limit:{key}
                    limit_key = f"ratelimit:limit:{key_name}"
                    limit_data = await r.hgetall(limit_key)
                    limit = int(limit_data.get("limit", 10)) if limit_data else 10

                    # Just count entries - DON'T prune here, let the service handle that
                    # Pruning here with wrong window was wiping counters
                    count = await r.zcard(key)
                    if count == 0:
                        continue  # Key is effectively empty, skip

                    counters.append(
                        {
                            "key": key_name,
                            "count": count,
                            "limit": limit,
                            "over_limit": count > limit,
                        }
                    )

                    # Stop after collecting 10 counters
                    if len(counters) >= 10:
                        break

            finally:
                await r.aclose()
        except Exception:
            pass  # Redis unavailable, return empty list

        return counters
