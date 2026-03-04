"""
Tests for ChatDBAppSubject with mocked clients.

Verifies that observe() correctly merges data from AppClient and PgClient
into the expected observation dict structure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_db_app_observer.subject import (
    ChatDBAppSubject,
    _estimate_percentile_from_buckets,
)
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
    mock.get_histogram_buckets = AsyncMock(return_value={})
    mock.probe_search_latency_ms = AsyncMock(return_value=None)
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
    mock.get_table_bloat_stats = AsyncMock(return_value=[])
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


# ---------- Windowed percentile tests ----------


class TestEstimatePercentileFromBuckets:
    """Tests for the standalone percentile estimation function."""

    def test_all_fast_requests(self):
        """100 requests all under 10ms → P99 = 10."""
        buckets = [(10, 100), (50, 100), (100, 100), (250, 100), (500, 100), (1000, 100), (5000, 100)]
        assert _estimate_percentile_from_buckets(0.99, 100, buckets) == 10.0

    def test_mixed_latency(self):
        """90 fast, 10 slow → P99 should be in the 5000ms bucket."""
        buckets = [(10, 90), (50, 90), (100, 90), (250, 90), (500, 90), (1000, 90), (5000, 100)]
        assert _estimate_percentile_from_buckets(0.99, 100, buckets) == 5000.0

    def test_p50_calculation(self):
        """50 fast, 50 slow → P50 = 10ms."""
        buckets = [(10, 50), (50, 50), (100, 50), (250, 50), (500, 50), (1000, 50), (5000, 100)]
        assert _estimate_percentile_from_buckets(0.50, 100, buckets) == 10.0

    def test_empty_returns_zero(self):
        assert _estimate_percentile_from_buckets(0.99, 0, []) == 0.0


class TestWindowedPercentiles:
    """Tests for ChatDBAppSubject windowed percentile computation."""

    def _make_subject(self):
        app_client = _make_mock_app_client()
        pg_client = _make_mock_pg_client()
        return ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

    def test_first_scrape_returns_none(self):
        """First scrape has no previous data, should return None."""
        subject = self._make_subject()
        buckets = {10: 100, 50: 100, 100: 100, 250: 100, 500: 100, 1000: 100, 5000: 100, 0: 100}
        result = subject._compute_windowed_percentiles(buckets)
        assert result is None

    def test_second_scrape_computes_windowed(self):
        """Second scrape should compute from delta when enough requests."""
        subject = self._make_subject()
        # First scrape: 100 requests, all fast
        first = {10: 100, 50: 100, 100: 100, 250: 100, 500: 100, 1000: 100, 5000: 100, 0: 100}
        subject._compute_windowed_percentiles(first)

        # Second scrape: 50 more requests (>=30 threshold), all fast
        second = {10: 150, 50: 150, 100: 150, 250: 150, 500: 150, 1000: 150, 5000: 150, 0: 150}
        result = subject._compute_windowed_percentiles(second)
        assert result is not None
        assert result["latency_p99_ms"] == 10.0
        assert result["latency_p50_ms"] == 10.0

    def test_rolling_window_accumulates(self):
        """Rolling window uses oldest-to-newest delta across multiple scrapes."""
        subject = self._make_subject()
        # Feed 6 scrapes, each adding 10 requests (total delta = 50 across 6 scrapes)
        for i in range(6):
            count = 100 + i * 10
            buckets = {10: count, 50: count, 100: count, 250: count,
                       500: count, 1000: count, 5000: count, 0: count}
            result = subject._compute_windowed_percentiles(buckets)

        # After 6 scrapes: delta from oldest(100) to newest(150) = 50 requests
        assert result is not None
        assert result["latency_p99_ms"] == 10.0

    def test_cumulative_pollution_ignored(self):
        """Old slow requests in cumulative histogram don't affect windowed P99."""
        subject = self._make_subject()
        # First scrape: 100 requests, 5 were slow (>1000ms)
        first = {10: 90, 50: 93, 100: 94, 250: 95, 500: 95, 1000: 95, 5000: 100, 0: 100}
        subject._compute_windowed_percentiles(first)

        # Second scrape: 200 more requests, ALL fast (under 10ms)
        second = {10: 290, 50: 293, 100: 294, 250: 295, 500: 295, 1000: 295, 5000: 300, 0: 300}
        result = subject._compute_windowed_percentiles(second)
        assert result is not None
        # Delta: 200 requests in <=10ms bucket, P99 = 10ms (not 5000ms!)
        assert result["latency_p99_ms"] == 10.0

    def test_app_restart_clears_history(self):
        """When counters decrease (app restart), clear history and return None."""
        subject = self._make_subject()
        first = {10: 500, 50: 500, 100: 500, 250: 500, 500: 500, 1000: 500, 5000: 500, 0: 500}
        subject._compute_windowed_percentiles(first)

        # App restarted, counters reset to 0
        second = {10: 5, 50: 5, 100: 5, 250: 5, 500: 5, 1000: 5, 5000: 5, 0: 5}
        result = subject._compute_windowed_percentiles(second)
        assert result is None
        # History should be cleared to just the post-restart scrape
        assert len(subject._bucket_history) == 1

    def test_insufficient_requests_returns_none(self):
        """Fewer than MIN_WINDOW_REQUESTS (30) in the window → None."""
        subject = self._make_subject()
        first = {10: 100, 50: 100, 100: 100, 250: 100, 500: 100, 1000: 100, 5000: 100, 0: 100}
        subject._compute_windowed_percentiles(first)

        # Only 20 new requests (< 30 threshold)
        second = {10: 120, 50: 120, 100: 120, 250: 120, 500: 120, 1000: 120, 5000: 120, 0: 120}
        result = subject._compute_windowed_percentiles(second)
        assert result is None

    def test_window_size_capped(self):
        """History doesn't grow beyond _WINDOW_SIZE."""
        subject = self._make_subject()
        for i in range(20):
            count = 100 + i * 50
            buckets = {10: count, 50: count, 100: count, 250: count,
                       500: count, 1000: count, 5000: count, 0: count}
            subject._compute_windowed_percentiles(buckets)
        assert len(subject._bucket_history) == subject._WINDOW_SIZE

    @pytest.mark.asyncio
    async def test_observe_uses_windowed_p99(self):
        """Verify observe() replaces cumulative P99 with windowed P99."""
        # App reports cumulative P99=5000ms (startup artifact)
        app_client = _make_mock_app_client(
            endpoint_metrics=EndpointMetrics(
                latency_p99_ms=5000.0,
                latency_p50_ms=10.0,
                requests_per_sec=50.0,
            )
        )
        # But histogram shows all recent requests are fast
        first_buckets = {10: 100, 50: 100, 100: 100, 250: 100, 500: 100, 1000: 100, 5000: 100, 0: 100}
        second_buckets = {10: 200, 50: 200, 100: 200, 250: 200, 500: 200, 1000: 200, 5000: 200, 0: 200}
        app_client.get_histogram_buckets = AsyncMock(side_effect=[first_buckets, second_buckets])

        pg_client = _make_mock_pg_client()
        subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

        # First observe: no windowed data yet, uses cumulative P99
        obs1 = await subject.observe()
        assert obs1["endpoint_metrics"]["latency_p99_ms"] == 5000.0

        # Second observe: windowed data available, should use windowed P99
        obs2 = await subject.observe()
        assert obs2["endpoint_metrics"]["latency_p99_ms"] == 10.0  # All recent requests fast


class TestSearchProbeLatency:
    """Tests for probe-based search latency tracking."""

    def _make_subject(self):
        app_client = _make_mock_app_client()
        pg_client = _make_mock_pg_client()
        return ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

    def test_no_probe_data_returns_zero(self):
        subject = self._make_subject()
        result = subject._update_search_probes(None)
        assert result == 0.0

    def test_single_probe(self):
        subject = self._make_subject()
        result = subject._update_search_probes(2500.0)
        assert result == 2500.0

    def test_median_of_probes(self):
        subject = self._make_subject()
        # Feed 3 probes
        subject._update_search_probes(100.0)
        subject._update_search_probes(200.0)
        result = subject._update_search_probes(3000.0)
        # Median of [100, 200, 3000] = 200
        assert result == 200.0

    def test_window_trimming(self):
        subject = self._make_subject()
        # Fill beyond window size
        for i in range(20):
            subject._update_search_probes(float(i * 100))
        assert len(subject._search_probe_history) == subject._SEARCH_PROBE_WINDOW

    def test_failed_probes_ignored(self):
        subject = self._make_subject()
        subject._update_search_probes(2000.0)
        # Failed probe (None) should not affect the window
        result = subject._update_search_probes(None)
        assert result == 2000.0

    @pytest.mark.asyncio
    async def test_observe_reports_search_latency(self):
        """Verify observe() includes probe-based search latency."""
        app_client = _make_mock_app_client()
        app_client.probe_search_latency_ms = AsyncMock(return_value=2500.0)
        pg_client = _make_mock_pg_client()
        subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

        obs = await subject.observe()
        assert obs["endpoint_metrics"]["search_latency_p99_ms"] == 2500.0

    @pytest.mark.asyncio
    async def test_observe_search_latency_none_is_zero(self):
        """Verify observe() reports 0.0 when probe fails."""
        app_client = _make_mock_app_client()
        app_client.probe_search_latency_ms = AsyncMock(return_value=None)
        pg_client = _make_mock_pg_client()
        subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)

        obs = await subject.observe()
        assert obs["endpoint_metrics"]["search_latency_p99_ms"] == 0.0
