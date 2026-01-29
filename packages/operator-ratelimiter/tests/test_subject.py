"""Tests for RateLimiterSubject."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest

from operator_ratelimiter.subject import RateLimiterSubject
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient
from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.types import NodeInfo, CounterInfo


@pytest.fixture
def mock_ratelimiter_client():
    """Create mock RateLimiterClient."""
    client = MagicMock(spec=RateLimiterClient)
    client.get_nodes = AsyncMock(return_value=[
        NodeInfo(id="node1", address="localhost:8001", state="Up", registered_at=datetime.now()),
        NodeInfo(id="node2", address="localhost:8002", state="Up", registered_at=datetime.now()),
    ])
    client.get_counters = AsyncMock(return_value=[
        CounterInfo(key="user:1", count=5, limit=10, remaining=5),
    ])
    return client


@pytest.fixture
def mock_redis_client():
    """Create mock RedisClient."""
    client = MagicMock(spec=RedisClient)
    client.ping = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_prom_client():
    """Create mock PrometheusClient."""
    client = MagicMock(spec=PrometheusClient)
    client.get_node_latency_p99 = AsyncMock(return_value=10.0)
    return client


@pytest.fixture
def subject(mock_ratelimiter_client, mock_redis_client, mock_prom_client):
    """Create RateLimiterSubject with mocked clients."""
    return RateLimiterSubject(
        ratelimiter=mock_ratelimiter_client,
        redis=mock_redis_client,
        prom=mock_prom_client,
    )


class TestObserve:
    """Tests for observe() method."""

    @pytest.mark.asyncio
    async def test_observe_returns_dict(self, subject):
        """observe() should return a dictionary."""
        result = await subject.observe()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_observe_contains_nodes(self, subject):
        """observe() should include nodes list."""
        result = await subject.observe()
        assert "nodes" in result
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["id"] == "node1"
        assert result["nodes"][0]["state"] == "Up"

    @pytest.mark.asyncio
    async def test_observe_contains_counters(self, subject):
        """observe() should include counters list."""
        result = await subject.observe()
        assert "counters" in result
        assert len(result["counters"]) == 1
        assert result["counters"][0]["key"] == "user:1"

    @pytest.mark.asyncio
    async def test_observe_contains_redis_connected(self, subject):
        """observe() should include redis_connected status."""
        result = await subject.observe()
        assert "redis_connected" in result
        assert result["redis_connected"] is True

    @pytest.mark.asyncio
    async def test_observe_contains_node_metrics(self, subject):
        """observe() should include per-node metrics."""
        result = await subject.observe()
        assert "node_metrics" in result
        assert "node1" in result["node_metrics"]
        assert result["node_metrics"]["node1"]["latency_p99_ms"] == 10.0

    @pytest.mark.asyncio
    async def test_observe_redis_disconnected(self, subject, mock_redis_client):
        """observe() should report redis_connected=False when ping fails."""
        mock_redis_client.ping = AsyncMock(return_value=False)
        result = await subject.observe()
        assert result["redis_connected"] is False

    @pytest.mark.asyncio
    async def test_observe_skips_metrics_for_down_nodes(
        self, mock_ratelimiter_client, mock_redis_client, mock_prom_client
    ):
        """observe() should skip metrics for nodes not in Up state."""
        mock_ratelimiter_client.get_nodes = AsyncMock(return_value=[
            NodeInfo(id="node1", address="localhost:8001", state="Down", registered_at=datetime.now()),
        ])

        subject = RateLimiterSubject(
            ratelimiter=mock_ratelimiter_client,
            redis=mock_redis_client,
            prom=mock_prom_client,
        )

        result = await subject.observe()
        # Down nodes should not have metrics collected
        assert "node1" not in result["node_metrics"]
        # Prometheus client should not be called for down nodes
        mock_prom_client.get_node_latency_p99.assert_not_called()

    @pytest.mark.asyncio
    async def test_observe_handles_metrics_error_gracefully(
        self, mock_ratelimiter_client, mock_redis_client, mock_prom_client
    ):
        """observe() should skip failed metrics without blocking."""
        mock_prom_client.get_node_latency_p99 = AsyncMock(side_effect=Exception("Connection error"))

        subject = RateLimiterSubject(
            ratelimiter=mock_ratelimiter_client,
            redis=mock_redis_client,
            prom=mock_prom_client,
        )

        # Should not raise, just skip failed metrics
        result = await subject.observe()
        assert "node_metrics" in result
        # Nodes with failed metrics are skipped
        assert result["node_metrics"] == {}
