"""HTTP client for rate limiter management API."""

from dataclasses import dataclass

import httpx

from operator_ratelimiter.types import (
    BlockedKeyInfo,
    BlocksResponse,
    CounterInfo,
    CountersResponse,
    LimitsResponse,
    NodeInfo,
    NodesResponse,
)


@dataclass
class RateLimiterClient:
    """
    Rate limiter management API client with injected httpx client.

    Queries the rate limiter service HTTP API for cluster state information.

    Attributes:
        http: Pre-configured httpx.AsyncClient with base_url set to rate limiter service.

    Example:
        async with httpx.AsyncClient(base_url="http://ratelimiter:8000") as http:
            client = RateLimiterClient(http=http)
            nodes = await client.get_nodes()
            for node in nodes:
                print(f"Node {node.id} at {node.address}: {node.state}")
    """

    http: httpx.AsyncClient

    async def get_nodes(self) -> list[NodeInfo]:
        """
        Get all registered rate limiter nodes.

        Calls GET /api/nodes and returns list of node information.

        Returns:
            List of NodeInfo objects representing rate limiter nodes.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.
        """
        response = await self.http.get("/api/nodes")
        response.raise_for_status()

        data = NodesResponse.model_validate(response.json())
        return data.nodes

    async def get_counters(self) -> list[CounterInfo]:
        """
        Get all active rate limit counters.

        Calls GET /api/counters and returns list of counter information.

        Returns:
            List of CounterInfo objects with key, count, limit, and remaining.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.
        """
        response = await self.http.get("/api/counters")
        response.raise_for_status()

        data = CountersResponse.model_validate(response.json())
        return data.counters

    async def get_limits(self) -> LimitsResponse:
        """
        Get configured rate limits.

        Calls GET /api/limits and returns limit configuration.

        Returns:
            LimitsResponse with default_limit and default_window_ms.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.
        """
        response = await self.http.get("/api/limits")
        response.raise_for_status()

        return LimitsResponse.model_validate(response.json())

    async def get_blocks(self) -> list[BlockedKeyInfo]:
        """
        Get all blocked keys (at or over limit).

        Calls GET /api/blocks and returns list of blocked key information.

        Returns:
            List of BlockedKeyInfo objects for keys currently blocked.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.
        """
        response = await self.http.get("/api/blocks")
        response.raise_for_status()

        data = BlocksResponse.model_validate(response.json())
        return data.blocked

    async def reset_counter(self, key: str) -> None:
        """
        Reset a rate limit counter.

        Calls POST /api/counters/{key}/reset to clear the counter.
        Fire-and-forget operation.

        Args:
            key: The counter key to reset.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).

        Note:
            Fire-and-forget: Returns when service accepts the request.
            Does not wait for actual reset confirmation.
        """
        response = await self.http.post(f"/api/counters/{key}/reset")
        response.raise_for_status()
