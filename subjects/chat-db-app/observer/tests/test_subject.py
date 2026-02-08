"""
Tests for ChatDBAppSubject with mocked clients.

Verifies that observe() correctly merges data from AppClient and PgClient
into the expected observation dict structure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_db_app_observer.subject import ChatDBAppSubject
from chat_db_app_observer.types import (
    AppHealthResponse,
    EndpointMetrics,
    LongRunningQuery,
    PgSessionStats,
    PoolMetrics,
)


def _make_mock_app_client(
    health: AppHealthResponse | None = None,
    pool_metrics: PoolMetrics | None = None,
    endpoint_metrics: EndpointMetrics | None = None,
) -> MagicMock:
    """Create a mock AppClient with configurable responses."""
    mock = MagicMock()
    mock.get_health = AsyncMock(
        return_value=health or AppHealthResponse(status="Up", pool_size=10, pool_free=5, uptime_seconds=3600.0)
    )
    mock.get_pool_metrics = AsyncMock(
        return_value=pool_metrics or PoolMetrics(active=5, idle=5, total=10, max_size=20, min_size=2)
    )
    mock.get_endpoint_metrics = AsyncMock(
        return_value=endpoint_metrics
        or EndpointMetrics(
            latency_p99_ms=25.0,
            latency_p50_ms=10.0,
            latency_avg_ms=15.0,
            latency_max_ms=100.0,
            requests_total=1000,
            requests_5xx=2,
            requests_per_sec=50.0,
            error_rate_pct=0.2,
            uptime_seconds=3600.0,
        )
    )
    return mock


def _make_mock_pg_client(
    reachable: bool = True,
    max_connections: int = 100,
    session_stats: PgSessionStats | None = None,
    long_queries: list[LongRunningQuery] | None = None,
    deadlocks: int = 0,
) -> MagicMock:
    """Create a mock PgClient with configurable responses."""
    mock = MagicMock()
    mock.is_reachable = AsyncMock(return_value=reachable)
    mock.get_max_connections = AsyncMock(return_value=max_connections)
    mock.get_session_stats = AsyncMock(
        return_value=session_stats
        or PgSessionStats(active_connections=8, idle_connections=3, idle_in_transaction=1, waiting_on_lock=0)
    )
    mock.get_long_running_queries = AsyncMock(return_value=long_queries or [])
    mock.get_deadlock_count = AsyncMock(return_value=deadlocks)
    return mock


@pytest.mark.asyncio
async def test_observe_healthy_system():
    """Test observe() returns expected structure for a healthy system."""
    app_client = _make_mock_app_client()
    pg_client = _make_mock_pg_client()
    subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

    obs = await subject.observe()

    # Verify structure
    assert "app" in obs
    assert "connection_pool" in obs
    assert "database" in obs
    assert "endpoint_metrics" in obs

    # Verify app section
    assert obs["app"]["status"] == "Up"
    assert obs["app"]["uptime_seconds"] == 3600.0
    assert obs["app"]["error_rate_pct"] == 0.2

    # Verify connection pool
    assert obs["connection_pool"]["active"] == 5
    assert obs["connection_pool"]["idle"] == 5
    assert obs["connection_pool"]["total"] == 10
    assert obs["connection_pool"]["max_size"] == 20

    # Verify database
    assert obs["database"]["reachable"] is True
    assert obs["database"]["active_connections"] == 8
    assert obs["database"]["max_connections"] == 100
    assert obs["database"]["idle_in_transaction"] == 1
    assert obs["database"]["waiting_on_lock"] == 0
    assert obs["database"]["long_running_queries"] == []
    assert obs["database"]["deadlocks_total"] == 0

    # Verify endpoint metrics
    assert obs["endpoint_metrics"]["latency_p99_ms"] == 25.0
    assert obs["endpoint_metrics"]["requests_per_sec"] == 50.0
    assert obs["endpoint_metrics"]["error_count_5xx"] == 2


@pytest.mark.asyncio
async def test_observe_with_long_running_queries():
    """Test observe() includes long-running query details."""
    long_queries = [
        LongRunningQuery(pid=1234, duration_sec=45.2, state="active", query_preview="UPDATE users SET token_usage..."),
        LongRunningQuery(pid=5678, duration_sec=20.1, state="active", query_preview="SELECT * FROM messages WHERE..."),
    ]
    pg_client = _make_mock_pg_client(long_queries=long_queries)
    subject = ChatDBAppSubject(app_client=_make_mock_app_client(), pg_client=pg_client)

    obs = await subject.observe()

    queries = obs["database"]["long_running_queries"]
    assert len(queries) == 2
    assert queries[0]["pid"] == 1234
    assert queries[0]["duration_sec"] == 45.2
    assert "token_usage" in queries[0]["query_preview"]


@pytest.mark.asyncio
async def test_observe_db_unreachable():
    """Test observe() handles unreachable database gracefully."""
    pg_client = _make_mock_pg_client(reachable=False)
    subject = ChatDBAppSubject(app_client=_make_mock_app_client(), pg_client=pg_client)

    obs = await subject.observe()

    assert obs["database"]["reachable"] is False
    # Should use defaults when DB is unreachable
    assert obs["database"]["active_connections"] == 0
    assert obs["database"]["max_connections"] == 100
    assert obs["database"]["idle_in_transaction"] == 0
    assert obs["database"]["long_running_queries"] == []

    # PG stat queries should not be called when unreachable
    pg_client.get_session_stats.assert_not_awaited()
    pg_client.get_long_running_queries.assert_not_awaited()


@pytest.mark.asyncio
async def test_observe_app_down():
    """Test observe() when app health endpoint reports down."""
    app_client = _make_mock_app_client(
        health=AppHealthResponse(status="Down", error="Connection refused")
    )
    subject = ChatDBAppSubject(app_client=app_client, pg_client=_make_mock_pg_client())

    obs = await subject.observe()

    assert obs["app"]["status"] == "Down"


@pytest.mark.asyncio
async def test_observe_with_deadlocks():
    """Test observe() reports deadlock count."""
    pg_client = _make_mock_pg_client(deadlocks=5)
    subject = ChatDBAppSubject(app_client=_make_mock_app_client(), pg_client=pg_client)

    obs = await subject.observe()

    assert obs["database"]["deadlocks_total"] == 5


@pytest.mark.asyncio
async def test_observe_under_pressure():
    """Test observe() captures symptoms of a system under pressure."""
    app_client = _make_mock_app_client(
        pool_metrics=PoolMetrics(active=18, idle=0, total=18, max_size=20, min_size=2),
        endpoint_metrics=EndpointMetrics(
            latency_p99_ms=800.0,
            latency_p50_ms=200.0,
            requests_per_sec=10.0,
            requests_5xx=50,
            error_rate_pct=12.0,
        ),
    )
    pg_client = _make_mock_pg_client(
        session_stats=PgSessionStats(
            active_connections=25,
            idle_in_transaction=8,
            waiting_on_lock=4,
        ),
        long_queries=[
            LongRunningQuery(pid=111, duration_sec=30.0, state="active", query_preview="UPDATE users..."),
        ],
        deadlocks=3,
    )
    subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

    obs = await subject.observe()

    # High pool usage
    assert obs["connection_pool"]["active"] == 18
    assert obs["connection_pool"]["total"] == 18
    # Database pressure
    assert obs["database"]["idle_in_transaction"] == 8
    assert obs["database"]["waiting_on_lock"] == 4
    assert len(obs["database"]["long_running_queries"]) == 1
    assert obs["database"]["deadlocks_total"] == 3
    # Degraded performance
    assert obs["endpoint_metrics"]["latency_p99_ms"] == 800.0
    assert obs["endpoint_metrics"]["error_count_5xx"] == 50


@pytest.mark.asyncio
async def test_observe_app_metrics_failure_returns_defaults():
    """Test observe() returns defaults when app metrics endpoint fails."""
    app_client = _make_mock_app_client()
    app_client.get_endpoint_metrics = AsyncMock(side_effect=Exception("Connection refused"))
    app_client.get_pool_metrics = AsyncMock(side_effect=Exception("Connection refused"))

    subject = ChatDBAppSubject(app_client=app_client, pg_client=_make_mock_pg_client())

    obs = await subject.observe()

    # Should use defaults, not crash
    assert obs["endpoint_metrics"]["latency_p99_ms"] == 0.0
    assert obs["connection_pool"]["total"] == 0
