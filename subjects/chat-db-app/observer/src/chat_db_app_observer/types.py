"""
Pydantic models for structured data from the chat-db-app.

Types for:
- App health/metrics responses
- PostgreSQL session stats
- Long-running query info
"""

from __future__ import annotations

from pydantic import BaseModel


class AppHealthResponse(BaseModel):
    """Response from GET /health."""

    status: str
    pool_size: int = 0
    pool_free: int = 0
    uptime_seconds: float = 0.0
    error: str | None = None


class PoolMetrics(BaseModel):
    """Connection pool metrics parsed from /metrics."""

    active: int = 0
    idle: int = 0
    total: int = 0
    max_size: int = 0
    min_size: int = 0


class EndpointMetrics(BaseModel):
    """Endpoint performance metrics parsed from /metrics."""

    latency_p99_ms: float = 0.0
    latency_p50_ms: float = 0.0
    latency_avg_ms: float = 0.0
    latency_max_ms: float = 0.0
    requests_total: int = 0
    requests_5xx: int = 0
    requests_per_sec: float = 0.0
    error_rate_pct: float = 0.0
    uptime_seconds: float = 0.0


class PgSessionStats(BaseModel):
    """PostgreSQL session statistics from pg_stat_activity."""

    active_connections: int = 0
    idle_connections: int = 0
    idle_in_transaction: int = 0
    waiting_on_lock: int = 0


class LongRunningQuery(BaseModel):
    """A long-running query detected in pg_stat_activity."""

    pid: int
    duration_sec: float
    state: str
    query_preview: str


class PgDatabaseStats(BaseModel):
    """Statistics from pg_stat_database."""

    deadlocks_total: int = 0
