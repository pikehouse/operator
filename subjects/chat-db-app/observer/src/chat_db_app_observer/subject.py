"""
ChatDBAppSubject - Implementation of SubjectProtocol for the chat-db-app.

Observes both the application (via HTTP) and its database (via direct PG
connection) to build a comprehensive view of system health.

The observer's PG connection is separate from the app's pool — a small
diagnostic pool (1-2 connections) querying pg_stat_activity and
pg_stat_database.
"""

from __future__ import annotations

from typing import Any

from chat_db_app_observer.app_client import AppClient
from chat_db_app_observer.pg_client import PgClient


class ChatDBAppSubject:
    """
    Chat DB App implementation of SubjectProtocol.

    Combines data from two sources:
    - AppClient: HTTP calls to the app's /health and /metrics endpoints
    - PgClient: Direct PG queries to pg_stat_activity, pg_stat_database

    Produces an observation dict with keys: app, connection_pool,
    database, endpoint_metrics.
    """

    def __init__(self, app_client: AppClient, pg_client: PgClient) -> None:
        self._app = app_client
        self._pg = pg_client

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
        db_reachable = await self._pg.is_reachable()

        # Only query PG stats if reachable
        if db_reachable:
            session_stats = await self._pg.get_session_stats()
            max_connections = await self._pg.get_max_connections()
            long_queries = await self._pg.get_long_running_queries(threshold_sec=10.0)
            deadlocks = await self._pg.get_deadlock_count()
        else:
            from chat_db_app_observer.types import PgSessionStats

            session_stats = PgSessionStats()
            max_connections = 100
            long_queries = []
            deadlocks = 0

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
            },
            "endpoint_metrics": {
                "latency_p99_ms": endpoint_metrics.latency_p99_ms,
                "latency_p50_ms": endpoint_metrics.latency_p50_ms,
                "requests_per_sec": endpoint_metrics.requests_per_sec,
                "error_count_5xx": endpoint_metrics.requests_5xx,
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
