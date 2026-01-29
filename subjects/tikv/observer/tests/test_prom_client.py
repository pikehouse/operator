"""
Tests for PrometheusClient - Prometheus metrics client for TiKV monitoring.

Tests cover:
- instant_query with success response -> returns result list
- instant_query with error status -> raises ValueError
- instant_query with HTTP error -> raises httpx.HTTPStatusError
- get_metric_value with single result -> returns float
- get_metric_value with empty result -> returns None
- get_store_metrics aggregates all metrics correctly

PITFALL: Prometheus returns values as strings ["timestamp", "string_value"]
Must convert to float explicitly (per RESEARCH.md Pitfall 2).
"""

import pytest
import httpx

from tikv_observer.prom_client import PrometheusClient
from operator_core.types import StoreMetrics


class MockResponse:
    """Mock httpx response for testing."""

    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://test"),
                response=self,
            )


class MockAsyncClient:
    """Mock httpx.AsyncClient for testing PrometheusClient."""

    def __init__(self, responses: dict[str, MockResponse] | None = None):
        self.responses = responses or {}
        self.requests: list[tuple[str, dict]] = []

    async def get(self, path: str, params: dict = None) -> MockResponse:
        self.requests.append((path, params or {}))
        # Look up response by query param if present
        if params and "query" in params:
            key = params["query"]
            if key in self.responses:
                return self.responses[key]
        # Fall back to path-based lookup
        if path in self.responses:
            return self.responses[path]
        # Default response
        return MockResponse({"status": "error", "error": "not mocked"}, 400)


# =============================================================================
# instant_query tests
# =============================================================================


@pytest.mark.asyncio
async def test_instant_query_success_returns_result_list():
    """instant_query with success response returns result list."""
    mock_http = MockAsyncClient(
        {
            "/api/v1/query": MockResponse(
                {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {"metric": {"__name__": "up"}, "value": [1234567890.123, "1"]},
                            {"metric": {"__name__": "up"}, "value": [1234567890.123, "0"]},
                        ],
                    },
                }
            )
        }
    )

    client = PrometheusClient(http=mock_http)
    results = await client.instant_query("up")

    assert len(results) == 2
    assert results[0]["metric"]["__name__"] == "up"
    assert results[0]["value"] == [1234567890.123, "1"]


@pytest.mark.asyncio
async def test_instant_query_error_status_raises_value_error():
    """instant_query with error status raises ValueError."""
    mock_http = MockAsyncClient(
        {
            "/api/v1/query": MockResponse(
                {
                    "status": "error",
                    "errorType": "bad_data",
                    "error": "invalid query",
                    "data": {"resultType": "vector", "result": []},
                }
            )
        }
    )

    client = PrometheusClient(http=mock_http)

    with pytest.raises(ValueError, match="Prometheus query failed"):
        await client.instant_query("invalid{")


@pytest.mark.asyncio
async def test_instant_query_http_error_raises_http_status_error():
    """instant_query with HTTP error raises httpx.HTTPStatusError."""
    mock_http = MockAsyncClient(
        {"/api/v1/query": MockResponse({"error": "server error"}, 500)}
    )

    client = PrometheusClient(http=mock_http)

    with pytest.raises(httpx.HTTPStatusError):
        await client.instant_query("up")


# =============================================================================
# get_metric_value tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_metric_value_single_result_returns_float():
    """get_metric_value with single result returns float (not string)."""
    mock_http = MockAsyncClient(
        {
            "up": MockResponse(
                {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {"metric": {"__name__": "up"}, "value": [1234567890.123, "42.5"]}
                        ],
                    },
                }
            )
        }
    )

    client = PrometheusClient(http=mock_http)
    value = await client.get_metric_value("up")

    # PITFALL: Value must be float, not string
    assert value == 42.5
    assert isinstance(value, float)


@pytest.mark.asyncio
async def test_get_metric_value_empty_result_returns_none():
    """get_metric_value with empty result returns None."""
    mock_http = MockAsyncClient(
        {
            "nonexistent": MockResponse(
                {
                    "status": "success",
                    "data": {"resultType": "vector", "result": []},
                }
            )
        }
    )

    client = PrometheusClient(http=mock_http)
    value = await client.get_metric_value("nonexistent")

    assert value is None


@pytest.mark.asyncio
async def test_get_metric_value_handles_string_to_float_conversion():
    """
    Prometheus returns values as strings, must convert to float.

    This tests RESEARCH.md Pitfall 2:
    "Prometheus returns values as strings ['timestamp', 'string_value']"
    """
    mock_http = MockAsyncClient(
        {
            "test_metric": MockResponse(
                {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            # Note: value is a STRING "3.14159"
                            {"metric": {}, "value": [1234567890.0, "3.14159"]}
                        ],
                    },
                }
            )
        }
    )

    client = PrometheusClient(http=mock_http)
    value = await client.get_metric_value("test_metric")

    assert value == pytest.approx(3.14159)
    assert isinstance(value, float)


# =============================================================================
# get_store_metrics tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_store_metrics_aggregates_all_metrics():
    """get_store_metrics returns StoreMetrics with all fields populated."""
    store_address = "tikv-0:20160"

    # Mock responses for each metric query
    # Using flexible matching since queries contain the address pattern
    mock_responses = {
        # QPS query
        'sum(rate(tikv_storage_command_total{instance=~"tikv-0.*20160"}[1m]))': MockResponse(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1234567890.0, "1500.5"]}],
                },
            }
        ),
        # P99 latency query (returns seconds)
        'histogram_quantile(0.99, rate(tikv_grpc_msg_duration_seconds_bucket{instance=~"tikv-0.*20160"}[1m]))': MockResponse(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1234567890.0, "0.025"]}],  # 25ms
                },
            }
        ),
        # Disk used query
        'tikv_store_size_bytes{type="used", instance=~"tikv-0.*20160"}': MockResponse(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1234567890.0, "50000000000"]}],  # 50GB
                },
            }
        ),
        # Disk capacity query
        'tikv_store_size_bytes{type="capacity", instance=~"tikv-0.*20160"}': MockResponse(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1234567890.0, "100000000000"]}],  # 100GB
                },
            }
        ),
        # CPU query
        'rate(process_cpu_seconds_total{instance=~"tikv-0.*20160"}[1m]) * 100': MockResponse(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {}, "value": [1234567890.0, "45.5"]}],  # 45.5%
                },
            }
        ),
    }

    mock_http = MockAsyncClient(mock_responses)
    client = PrometheusClient(http=mock_http)

    metrics = await client.get_store_metrics(store_id="1", store_address=store_address)

    assert isinstance(metrics, StoreMetrics)
    assert metrics.store_id == "1"
    assert metrics.qps == pytest.approx(1500.5)
    assert metrics.latency_p99_ms == pytest.approx(25.0)  # 0.025s * 1000
    assert metrics.disk_used_bytes == 50000000000
    assert metrics.disk_total_bytes == 100000000000
    assert metrics.cpu_percent == pytest.approx(45.5)
    assert metrics.raft_lag == 0  # Deferred per CONTEXT.md


@pytest.mark.asyncio
async def test_get_store_metrics_uses_correct_tikv_metric_names():
    """Verify correct TiKV metric names are used in queries (from RESEARCH.md)."""
    store_address = "tikv-1:20160"
    mock_http = MockAsyncClient({})  # Will fail all queries, but we capture them

    # Override get to capture queries without failing
    queries_made = []

    async def capture_get(path: str, params: dict = None):
        queries_made.append(params.get("query", "") if params else "")
        return MockResponse(
            {"status": "success", "data": {"resultType": "vector", "result": []}}
        )

    mock_http.get = capture_get

    client = PrometheusClient(http=mock_http)
    await client.get_store_metrics(store_id="1", store_address=store_address)

    # Verify correct metric names are used
    query_text = " ".join(queries_made)
    assert "tikv_storage_command_total" in query_text  # QPS
    assert "tikv_grpc_msg_duration_seconds_bucket" in query_text  # Latency
    assert "tikv_store_size_bytes" in query_text  # Disk
    assert "process_cpu_seconds_total" in query_text  # CPU


@pytest.mark.asyncio
async def test_get_store_metrics_handles_missing_metrics():
    """get_store_metrics uses default values when metrics are missing."""
    # All queries return empty results
    mock_http = MockAsyncClient({})

    async def empty_response(path: str, params: dict = None):
        return MockResponse(
            {"status": "success", "data": {"resultType": "vector", "result": []}}
        )

    mock_http.get = empty_response

    client = PrometheusClient(http=mock_http)
    metrics = await client.get_store_metrics(store_id="1", store_address="tikv:20160")

    # Should have default values, not crash
    assert metrics.qps == 0.0
    assert metrics.latency_p99_ms == 0.0
    assert metrics.disk_used_bytes == 0
    assert metrics.disk_total_bytes == 1  # 1 to avoid division by zero
    assert metrics.cpu_percent == 0.0


@pytest.mark.asyncio
async def test_get_store_metrics_converts_latency_to_milliseconds():
    """Prometheus returns latency in seconds, must convert to milliseconds."""
    mock_http = MockAsyncClient({})

    async def latency_response(path: str, params: dict = None):
        query = params.get("query", "") if params else ""
        if "tikv_grpc_msg_duration_seconds" in query:
            return MockResponse(
                {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"metric": {}, "value": [1234567890.0, "0.123"]}],  # 123ms
                    },
                }
            )
        return MockResponse(
            {"status": "success", "data": {"resultType": "vector", "result": []}}
        )

    mock_http.get = latency_response

    client = PrometheusClient(http=mock_http)
    metrics = await client.get_store_metrics(store_id="1", store_address="tikv:20160")

    assert metrics.latency_p99_ms == pytest.approx(123.0)  # 0.123s * 1000


@pytest.mark.asyncio
async def test_get_store_metrics_address_pattern_escaping():
    """Store address colon is escaped for regex matching."""
    mock_http = MockAsyncClient({})
    queries_made = []

    async def capture_get(path: str, params: dict = None):
        queries_made.append(params.get("query", "") if params else "")
        return MockResponse(
            {"status": "success", "data": {"resultType": "vector", "result": []}}
        )

    mock_http.get = capture_get

    client = PrometheusClient(http=mock_http)
    await client.get_store_metrics(store_id="1", store_address="tikv-0:20160")

    # Verify address is pattern-escaped (colon -> .*)
    query_text = " ".join(queries_made)
    assert "tikv-0.*20160" in query_text  # Colon replaced with .*
