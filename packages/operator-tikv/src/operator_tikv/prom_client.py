"""
Prometheus API client for TiKV metrics collection.

This module provides the PrometheusClient class for querying TiKV performance
metrics from Prometheus. It supports:
- Instant PromQL queries
- Single value extraction
- Aggregated store metrics collection

Key design decisions:
- Uses injected httpx.AsyncClient (per CONTEXT.md - core injects clients)
- Converts string metric values to floats (per RESEARCH.md Pitfall 2)
- Uses correct TiKV metric names (per RESEARCH.md)
- Fails loudly on HTTP errors (per CONTEXT.md)

Metric sources (from RESEARCH.md):
- QPS: tikv_storage_command_total
- P99 latency: tikv_grpc_msg_duration_seconds_bucket
- Disk usage: tikv_store_size_bytes
- CPU: process_cpu_seconds_total
"""

from dataclasses import dataclass
from typing import Any

import httpx

from operator_core.types import StoreId, StoreMetrics
from operator_tikv.types import PrometheusQueryResponse


@dataclass
class PrometheusClient:
    """
    Prometheus API client with injected httpx client.

    The httpx.AsyncClient should be pre-configured with the Prometheus server
    base_url (e.g., http://prometheus:9090).

    Example:
        async with httpx.AsyncClient(base_url="http://prometheus:9090") as http:
            client = PrometheusClient(http=http)
            qps = await client.get_metric_value('sum(rate(tikv_storage_command_total[1m]))')
    """

    http: httpx.AsyncClient

    async def instant_query(self, query: str) -> list[dict[str, Any]]:
        """
        Execute instant query at current time.

        Args:
            query: PromQL query string

        Returns:
            List of result dictionaries from Prometheus

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx)
            ValueError: On Prometheus query errors (status != "success")

        Note:
            Per CONTEXT.md: Fail loudly on HTTP errors
        """
        response = await self.http.get("/api/v1/query", params={"query": query})
        response.raise_for_status()  # Fail loudly per CONTEXT.md

        data = PrometheusQueryResponse(**response.json())
        if data.status != "success":
            raise ValueError(f"Prometheus query failed: {data.status}")

        return data.data.result

    async def get_metric_value(self, query: str) -> float | None:
        """
        Get single numeric value from instant query.

        Args:
            query: PromQL query string expected to return a single value

        Returns:
            Float value if result exists, None if no results

        Note:
            PITFALL: Prometheus returns values as strings ["timestamp", "string_value"]
            This method handles the string-to-float conversion (RESEARCH.md Pitfall 2)
        """
        results = await self.instant_query(query)
        if not results:
            return None

        # PITFALL (RESEARCH.md Pitfall 2): Value is string, must convert
        # Format: {"metric": {...}, "value": [timestamp, "string_value"]}
        return float(results[0]["value"][1])

    async def get_store_metrics(
        self, store_id: StoreId, store_address: str
    ) -> StoreMetrics:
        """
        Get aggregated metrics for a TiKV store.

        Queries Prometheus for QPS, latency, disk usage, and CPU metrics
        for the specified store.

        Args:
            store_id: The store ID to include in returned StoreMetrics
            store_address: Store address in format "host:port" (e.g., "tikv-0:20160")
                          Used for instance label matching in queries

        Returns:
            StoreMetrics with all fields populated (defaults for missing metrics)

        Note:
            Per RESEARCH.md: Uses regex matching for instance label flexibility
            Address colon is replaced with .* for flexible port matching
        """
        # Use regex matching for instance label flexibility (per RESEARCH.md)
        # tikv:20160 -> tikv.*20160 (handles port variations)
        addr_pattern = store_address.replace(":", ".*")

        # Query all metrics
        qps = await self.get_metric_value(
            f'sum(rate(tikv_storage_command_total{{instance=~"{addr_pattern}"}}[1m]))'
        ) or 0.0

        latency_seconds = await self.get_metric_value(
            f'histogram_quantile(0.99, rate(tikv_grpc_msg_duration_seconds_bucket{{instance=~"{addr_pattern}"}}[1m]))'
        ) or 0.0

        disk_used = await self.get_metric_value(
            f'tikv_store_size_bytes{{type="used", instance=~"{addr_pattern}"}}'
        ) or 0

        disk_capacity = await self.get_metric_value(
            f'tikv_store_size_bytes{{type="capacity", instance=~"{addr_pattern}"}}'
        ) or 1  # Default 1 to avoid division by zero downstream

        cpu_percent = await self.get_metric_value(
            f'rate(process_cpu_seconds_total{{instance=~"{addr_pattern}"}}[1m]) * 100'
        ) or 0.0

        return StoreMetrics(
            store_id=store_id,
            qps=qps,
            latency_p99_ms=latency_seconds * 1000,  # Convert seconds to milliseconds
            disk_used_bytes=int(disk_used),
            disk_total_bytes=int(disk_capacity),
            cpu_percent=cpu_percent,
            raft_lag=0,  # Raft-specific metrics deferred per CONTEXT.md
        )
