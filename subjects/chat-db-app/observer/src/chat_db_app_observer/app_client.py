"""
HTTP client for the chat-db-app observer.

Calls the app's /health and /metrics endpoints to collect
pool stats, latency histograms, and error rates.
"""

from __future__ import annotations

import re

import httpx

from chat_db_app_observer.types import (
    AppHealthResponse,
    EndpointMetrics,
    PoolMetrics,
)


class AppClient:
    """
    HTTP client for the chat app's health and metrics endpoints.

    Uses httpx.AsyncClient for async HTTP requests.
    """

    # Bucket upper bounds in ms, matching the app's histogram
    HISTOGRAM_BOUNDS = [10, 50, 100, 250, 500, 1000, 5000]

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get_health(self) -> AppHealthResponse:
        """
        Get app health status from GET /health.

        Returns:
            AppHealthResponse with status, pool info, and uptime.
        """
        try:
            resp = await self._http.get("/health")
            data = resp.json()
            return AppHealthResponse(
                status="Up" if data.get("status") == "healthy" else "Down",
                pool_size=data.get("pool_size", 0),
                pool_free=data.get("pool_free", 0),
                uptime_seconds=data.get("uptime_seconds", 0.0),
                error=data.get("error"),
            )
        except Exception as e:
            return AppHealthResponse(status="Down", error=str(e))

    async def get_pool_metrics(self) -> PoolMetrics:
        """
        Parse pool metrics from GET /metrics (Prometheus format).

        Extracts chatdb_pool_connections_* gauges.
        """
        text = await self._fetch_metrics_text()
        return PoolMetrics(
            active=_parse_gauge(text, "chatdb_pool_connections_active"),
            idle=_parse_gauge(text, "chatdb_pool_connections_idle"),
            total=_parse_gauge(text, "chatdb_pool_connections_total"),
            max_size=_parse_gauge(text, "chatdb_pool_connections_max_size"),
            min_size=_parse_gauge(text, "chatdb_pool_connections_min_size"),
        )

    async def get_endpoint_metrics(self) -> EndpointMetrics:
        """
        Parse endpoint performance metrics from GET /metrics.

        Extracts latency percentiles, request counts, error rates.
        """
        text = await self._fetch_metrics_text()
        return EndpointMetrics(
            latency_p99_ms=_parse_gauge_float(text, "chatdb_request_duration_ms_p99"),
            latency_p50_ms=_parse_gauge_float(text, "chatdb_request_duration_ms_p50"),
            latency_avg_ms=_parse_gauge_float(text, "chatdb_request_duration_ms_avg"),
            latency_max_ms=_parse_gauge_float(text, "chatdb_request_duration_ms_max"),
            requests_total=_parse_gauge(text, "chatdb_requests_total"),
            requests_5xx=_parse_gauge(text, "chatdb_requests_5xx_total"),
            requests_per_sec=_parse_gauge_float(text, "chatdb_requests_per_second"),
            error_rate_pct=_parse_gauge_float(text, "chatdb_error_rate_percent"),
            uptime_seconds=_parse_gauge_float(text, "chatdb_uptime_seconds"),
        )

    async def get_histogram_buckets(self) -> dict[int, int]:
        """
        Parse raw cumulative histogram bucket counts from /metrics.

        Returns:
            Dict mapping bucket upper bound (ms) to cumulative count,
            e.g. {10: 500, 50: 600, ..., 5000: 700}.
            Returns empty dict on failure.
        """
        text = await self._fetch_metrics_text()
        buckets: dict[int, int] = {}
        for bound in self.HISTOGRAM_BOUNDS:
            pattern = rf'chatdb_request_duration_ms_bucket\{{le="{bound}"\}}\s+(\S+)'
            match = re.search(pattern, text)
            if match:
                try:
                    buckets[bound] = int(float(match.group(1)))
                except ValueError:
                    pass
        # Also parse +Inf for total count
        inf_match = re.search(
            r'chatdb_request_duration_ms_bucket\{le="\+Inf"\}\s+(\S+)', text
        )
        if inf_match:
            try:
                buckets[0] = int(float(inf_match.group(1)))  # 0 key = +Inf total
            except ValueError:
                pass
        return buckets

    async def _fetch_metrics_text(self) -> str:
        """Fetch raw metrics text from /metrics endpoint."""
        try:
            resp = await self._http.get("/metrics")
            return resp.text
        except Exception:
            return ""


def _parse_gauge(text: str, metric_name: str) -> int:
    """Parse an integer gauge value from Prometheus text format."""
    # Match lines like: metric_name 42
    pattern = rf"^{re.escape(metric_name)}\s+(\S+)"
    match = re.search(pattern, text, re.MULTILINE)
    if match:
        try:
            return int(float(match.group(1)))
        except ValueError:
            pass
    return 0


def _parse_gauge_float(text: str, metric_name: str) -> float:
    """Parse a float gauge value from Prometheus text format."""
    pattern = rf"^{re.escape(metric_name)}\s+(\S+)"
    match = re.search(pattern, text, re.MULTILINE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0
