"""Prometheus API client for rate limiter metrics collection."""

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class PrometheusClient:
    """
    Prometheus API client with injected httpx client.

    Queries Prometheus for rate limiter performance metrics including
    latency histograms and request counts.

    Attributes:
        http: Pre-configured httpx.AsyncClient with base_url set to Prometheus server.

    Example:
        async with httpx.AsyncClient(base_url="http://prometheus:9090") as http:
            client = PrometheusClient(http=http)
            p99 = await client.get_node_latency_p99("node-1")
            print(f"P99 latency: {p99}ms")
    """

    http: httpx.AsyncClient

    async def instant_query(self, query: str) -> list[dict[str, Any]]:
        """
        Execute instant PromQL query at current time.

        Args:
            query: PromQL query string.

        Returns:
            List of result dictionaries from Prometheus.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            ValueError: On Prometheus query errors (status != "success").

        Note:
            Fails loudly on HTTP errors per operator-core patterns.
        """
        response = await self.http.get("/api/v1/query", params={"query": query})
        response.raise_for_status()

        data = response.json()
        if data.get("status") != "success":
            raise ValueError(f"Prometheus query failed: {data.get('status')}")

        return data["data"]["result"]

    async def get_metric_value(self, query: str) -> float | None:
        """
        Get single numeric value from instant query.

        Args:
            query: PromQL query string expected to return a single value.

        Returns:
            Float value if result exists, None if no results.

        Note:
            IMPORTANT: Prometheus returns values as strings ["timestamp", "string_value"].
            This method handles the string-to-float conversion.
        """
        results = await self.instant_query(query)
        if not results:
            return None

        # Prometheus value format: [timestamp, "string_value"]
        return float(results[0]["value"][1])

    async def get_node_latency_p99(self, node_id: str) -> float:
        """
        Get P99 latency for a rate limiter node.

        Queries the ratelimiter_check_duration_seconds histogram for the
        99th percentile latency over the last 1 minute.

        Args:
            node_id: The node ID to query latency for.

        Returns:
            P99 latency in milliseconds. Returns 0.0 if no data available.

        Note:
            Uses histogram_quantile with 1-minute rate window.
            Metric: ratelimiter_check_duration_seconds (histogram)
        """
        query = (
            f'histogram_quantile(0.99, '
            f'rate(ratelimiter_check_duration_seconds_bucket{{node_id="{node_id}"}}[1m])) '
            f'* 1000'
        )

        value = await self.get_metric_value(query)
        return value if value is not None else 0.0

    async def get_total_allowed_requests(self, key: str, window_seconds: int) -> int:
        """
        Get total allowed requests for a key over a time window.

        Used for ghost rate limit detection - identifies keys that are allowed
        through but might indicate misconfiguration.

        Args:
            key: The rate limit key to query.
            window_seconds: Time window in seconds to look back.

        Returns:
            Total number of allowed requests. Returns 0 if no data available.

        Note:
            Queries increase() over window to get total count of allowed requests.
            Metric: ratelimiter_requests_checked_total (counter with result label)
        """
        query = (
            f'increase(ratelimiter_requests_checked_total{{'
            f'result="allowed", key="{key}"}}[{window_seconds}s])'
        )

        value = await self.get_metric_value(query)
        return int(value) if value is not None else 0
