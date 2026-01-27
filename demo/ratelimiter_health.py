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
                # Query nodes list
                nodes_response = await self._client.get(f"{endpoint}/nodes")
                nodes_response.raise_for_status()
                nodes_data = nodes_response.json()

                # Query health status
                health_response = await self._client.get(f"{endpoint}/health")
                health_response.raise_for_status()
                health_data = health_response.json()

                # Parse health snapshot
                nodes = nodes_data.get("nodes", [])
                redis_connected = health_data.get("redis_connected", False)

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
        }
