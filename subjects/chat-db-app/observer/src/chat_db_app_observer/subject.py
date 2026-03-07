"""
ChatDBAppSubject - Implementation of SubjectProtocol for the chat-db-app.

Observes both the application (via HTTP) and its database (via direct PG
connection) to build a comprehensive view of system health.

The observer's PG connection is separate from the app's pool — a small
diagnostic pool (1-2 connections) querying pg_stat_activity and
pg_stat_database.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from chat_db_app_observer.app_client import AppClient
from chat_db_app_observer.pg_client import PgClient


def _estimate_percentile_from_buckets(
    pct: float, total: int, buckets: list[tuple[int, int]]
) -> float:
    """Estimate a percentile from histogram bucket deltas.

    Args:
        pct: Percentile (e.g. 0.99 for P99).
        total: Total request count in the window.
        buckets: List of (upper_bound_ms, count) pairs, sorted by bound.

    Returns:
        Estimated latency in ms for the given percentile.
    """
    if total <= 0:
        return 0.0
    target = pct * total
    for bound, count in buckets:
        if count >= target:
            return float(bound)
    # All requests exceeded the highest finite bucket
    return float(buckets[-1][0]) if buckets else 0.0


class ChatDBAppSubject:
    """
    Chat DB App implementation of SubjectProtocol.

    Combines data from two sources:
    - AppClient: HTTP calls to the app's /health and /metrics endpoints
    - PgClient: Direct PG queries to pg_stat_activity, pg_stat_database

    Produces an observation dict with keys: app, connection_pool,
    database, endpoint_metrics.

    Computes windowed (delta-based) latency percentiles from successive
    histogram scrapes, so that stale cumulative data doesn't pollute P99.
    """

    # Minimum requests in a window to trust the percentile calculation
    _MIN_WINDOW_REQUESTS = 30

    # Number of scrapes to keep for the rolling window.
    # At 5s interval, 12 scrapes = 60s window.
    _WINDOW_SIZE = 12

    # Number of probe results to keep for the search latency rolling window.
    # At 5s interval, 12 probes = 60s window.
    _SEARCH_PROBE_WINDOW = 12

    def __init__(self, app_client: AppClient, pg_client: PgClient) -> None:
        self._app = app_client
        self._pg = pg_client
        self._bucket_history: deque[dict[int, int]] = deque(maxlen=self._WINDOW_SIZE)
        self._search_probe_history: deque[float] = deque(maxlen=self._SEARCH_PROBE_WINDOW)

    async def observe(self) -> dict[str, Any]:
        """
        Gather current observations from the chat app and its database.

        Returns:
            Dictionary with the following structure:
            {
                "app": {status, uptime_seconds, error_rate_pct},
                "connection_pool": {active, idle, waiting, total, max_size},
                "database": {reachable, active_connections, max_connections,
                             idle_in_transaction, waiting_on_lock,
                             long_running_queries, deadlocks_total},
                "endpoint_metrics": {latency_p99_ms, latency_p50_ms,
                                     requests_per_sec, error_count_5xx},
            }
        """
        # Collect from both sources, tolerating failures
        health = await self._app.get_health()
        endpoint_metrics = await self._safe_endpoint_metrics()
        pool_metrics = await self._safe_pool_metrics()
        histogram_buckets = await self._safe_histogram_buckets()

        # Compute windowed percentiles from histogram deltas
        if histogram_buckets:
            windowed = self._compute_windowed_percentiles(histogram_buckets)
            if windowed is not None:
                endpoint_metrics = endpoint_metrics.model_copy(update=windowed)

        # Probe search latency directly (independent of app instrumentation)
        search_latency_ms = await self._app.probe_search_latency_ms()
        search_p99 = self._update_search_probes(search_latency_ms)

        db_reachable = await self._pg.is_reachable()

        # Only query PG stats if reachable
        if db_reachable:
            session_stats = await self._pg.get_session_stats()
            max_connections = await self._pg.get_max_connections()
            long_queries = await self._pg.get_long_running_queries(threshold_sec=10.0)
            deadlocks = await self._pg.get_deadlock_count()
            table_bloat = await self._pg.get_table_bloat_stats()
        else:
            from chat_db_app_observer.types import PgSessionStats

            session_stats = PgSessionStats()
            max_connections = 100
            long_queries = []
            deadlocks = 0
            table_bloat = []

        # Compute waiting from pool metrics (if pool reports a max and we're at it)
        pool_waiting = max(0, pool_metrics.total - pool_metrics.max_size) if pool_metrics.max_size > 0 else 0

        return {
            "app": {
                "status": health.status,
                "uptime_seconds": health.uptime_seconds,
                "error_rate_pct": endpoint_metrics.error_rate_pct,
            },
            "connection_pool": {
                "active": pool_metrics.active,
                "idle": pool_metrics.idle,
                "waiting": pool_waiting,
                "total": pool_metrics.total,
                "max_size": pool_metrics.max_size,
            },
            "database": {
                "reachable": db_reachable,
                "active_connections": session_stats.active_connections,
                "max_connections": max_connections,
                "idle_in_transaction": session_stats.idle_in_transaction,
                "waiting_on_lock": session_stats.waiting_on_lock,
                "long_running_queries": [
                    {
                        "pid": q.pid,
                        "duration_sec": q.duration_sec,
                        "state": q.state,
                        "query_preview": q.query_preview,
                    }
                    for q in long_queries
                ],
                "deadlocks_total": deadlocks,
                "table_bloat": [
                    {
                        "table_name": t.table_name,
                        "live_tuples": t.live_tuples,
                        "dead_tuples": t.dead_tuples,
                        "dead_ratio": t.dead_tuples / max(t.live_tuples, 1),
                        "last_autovacuum": t.last_autovacuum,
                    }
                    for t in table_bloat
                ],
            },
            "endpoint_metrics": {
                "latency_p99_ms": endpoint_metrics.latency_p99_ms,
                "latency_p50_ms": endpoint_metrics.latency_p50_ms,
                "requests_per_sec": endpoint_metrics.requests_per_sec,
                "error_count_5xx": endpoint_metrics.requests_5xx,
                "search_latency_p99_ms": search_p99,
            },
        }

    async def _safe_endpoint_metrics(self):
        """Get endpoint metrics, returning defaults on failure."""
        try:
            return await self._app.get_endpoint_metrics()
        except Exception:
            from chat_db_app_observer.types import EndpointMetrics

            return EndpointMetrics()

    async def _safe_pool_metrics(self):
        """Get pool metrics, returning defaults on failure."""
        try:
            return await self._app.get_pool_metrics()
        except Exception:
            from chat_db_app_observer.types import PoolMetrics

            return PoolMetrics()

    async def _safe_histogram_buckets(self) -> dict[int, int]:
        """Get histogram buckets, returning empty dict on failure."""
        try:
            return await self._app.get_histogram_buckets()
        except Exception:
            return {}

    def _update_search_probes(self, latency_ms: float | None) -> float:
        """Update search probe rolling window and return the median latency.

        Args:
            latency_ms: Latest probe result in ms, or None if probe failed.

        Returns:
            Median latency from the rolling window, or 0.0 if no data.
        """
        if latency_ms is not None:
            self._search_probe_history.append(latency_ms)

        if not self._search_probe_history:
            return 0.0

        # Use median for stability (all probes will be slow when ILIKE is slow)
        sorted_probes = sorted(self._search_probe_history)
        mid = len(sorted_probes) // 2
        if len(sorted_probes) % 2 == 0:
            return (sorted_probes[mid - 1] + sorted_probes[mid]) / 2
        return sorted_probes[mid]

    def _compute_windowed_percentiles(
        self,
        current: dict[int, int],
        history: deque[dict[int, int]] | None = None,
    ) -> dict[str, float] | None:
        """
        Compute windowed P50/P99 from the delta between the oldest and newest
        histogram scrapes in a rolling window.  Returns None if insufficient data.

        Using a rolling window (default 12 scrapes = ~60s at 5s interval) instead
        of a single-interval delta avoids noisy percentiles when RPS is low.
        With 2 RPS and a 60s window we get ~120 requests — enough for meaningful P99.

        Args:
            current: Current histogram bucket snapshot.
            history: Optional explicit history list to use. If None, uses
                     self._bucket_history (for general request latency).
        """
        if history is None:
            history = self._bucket_history

        history.append(current.copy())

        if len(history) < 2:
            return None  # Need at least 2 scrapes for a delta

        oldest = history[0]
        newest = history[-1]

        # Compute delta buckets across the full window
        bounds = AppClient.HISTOGRAM_BOUNDS
        delta_total = newest.get(0, 0) - oldest.get(0, 0)  # key 0 = +Inf

        if delta_total < 0:
            # App restarted, counters reset — discard history
            history.clear()
            history.append(current.copy())
            return None

        if delta_total < self._MIN_WINDOW_REQUESTS:
            return None  # Not enough requests in the window

        delta_buckets = []
        for bound in bounds:
            delta = newest.get(bound, 0) - oldest.get(bound, 0)
            delta_buckets.append((bound, max(0, delta)))

        # Estimate RPS from window span (WINDOW_SIZE * 5s interval)
        window_seconds = (len(history) - 1) * 5.0
        rps = delta_total / window_seconds if window_seconds > 0 else 0.0

        return {
            "latency_p50_ms": _estimate_percentile_from_buckets(0.50, delta_total, delta_buckets),
            "latency_p99_ms": _estimate_percentile_from_buckets(0.99, delta_total, delta_buckets),
            "requests_per_sec": rps,
        }
