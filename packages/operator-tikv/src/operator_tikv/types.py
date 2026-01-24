"""
TiKV-specific Pydantic response types.

This module provides Pydantic models for parsing responses from:
- PD API (Placement Driver): Cluster state, stores, regions
- Prometheus HTTP API: Metrics queries

These are API response types for external data validation. Internal
types (Store, Region, etc.) are dataclasses in operator_core.types.

Notes:
- PD API returns nested structures (see Pitfall 1 in RESEARCH.md)
- Prometheus values are strings that must be converted to float (Pitfall 2)
- Store IDs may be int in PD API but string in Prometheus labels (Pitfall 3)
"""

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# PD API Response Types
# =============================================================================
# Based on: https://tikv.org/docs/6.5/deploy/monitor/api/
# Response structure: {"stores": [{"store": {...}, "status": {...}}]}


class PDStoreInfo(BaseModel):
    """
    Inner store info from PD API.

    This is the nested 'store' object within each store entry.
    """

    id: int
    address: str
    state_name: str  # "Up", "Down", "Offline", "Tombstone"
    version: str = ""


class PDStoreStatus(BaseModel):
    """
    Store status metrics from PD API.

    This is the nested 'status' object within each store entry.
    Contains capacity and replica counts.
    """

    capacity: str = ""  # e.g., "100GiB"
    available: str = ""
    leader_count: int = 0
    region_count: int = 0


class PDStoreItem(BaseModel):
    """
    Single store entry from PD /stores endpoint.

    PD wraps store info in a nested structure with separate
    'store' (metadata) and 'status' (metrics) objects.
    """

    store: PDStoreInfo
    status: PDStoreStatus | None = None


class PDStoresResponse(BaseModel):
    """
    Response from GET /pd/api/v1/stores.

    Example response:
    {
        "count": 3,
        "stores": [
            {
                "store": {"id": 1, "address": "tikv:20160", "state_name": "Up"},
                "status": {"capacity": "100GiB", "leader_count": 10}
            }
        ]
    }
    """

    count: int
    stores: list[PDStoreItem]


class PDRegionPeer(BaseModel):
    """
    Region peer info.

    A peer is a replica of a region stored on a specific store.
    """

    id: int
    store_id: int


class PDRegionLeader(BaseModel):
    """
    Region leader info.

    The leader handles all reads and writes for a region.
    """

    id: int
    store_id: int


class PDRegionResponse(BaseModel):
    """
    Response from GET /pd/api/v1/region/id/{id}.

    Single region details including leader and peer information.
    """

    id: int
    leader: PDRegionLeader | None = None
    peers: list[PDRegionPeer] = Field(default_factory=list)


class PDRegionsResponse(BaseModel):
    """
    Response from GET /pd/api/v1/regions.

    Lists all regions in the cluster.
    """

    count: int
    regions: list[PDRegionResponse]


# =============================================================================
# Prometheus Response Types
# =============================================================================
# Based on: https://prometheus.io/docs/prometheus/latest/querying/api/
# IMPORTANT: Prometheus returns values as strings (Pitfall 2 in RESEARCH.md)


class PrometheusVectorResult(BaseModel):
    """
    Single result from instant vector query.

    The value tuple is [unix_timestamp, "string_value"].
    Note: The value is always a string and must be converted to float.
    """

    metric: dict[str, str]  # Labels as dict for flexibility
    value: tuple[float, str]  # [timestamp, "string_value"]


class PrometheusRangeResult(BaseModel):
    """
    Single result from range vector query.

    Values is a list of [timestamp, "string_value"] pairs.
    """

    metric: dict[str, str]
    values: list[tuple[float, str]]


class PrometheusData(BaseModel):
    """
    The 'data' field from Prometheus query response.

    Contains result type and the actual results.
    """

    model_config = ConfigDict(extra="allow")

    resultType: str  # "vector", "matrix", "scalar", "string"
    result: list[dict]  # Raw results - parsed based on resultType


class PrometheusQueryResponse(BaseModel):
    """
    Response from GET /api/v1/query (instant query).

    Example response:
    {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"__name__": "up"}, "value": [1234567890, "1"]}
            ]
        }
    }
    """

    status: str  # "success" or "error"
    data: PrometheusData
    errorType: str | None = None
    error: str | None = None

    def get_vector_results(self) -> list[PrometheusVectorResult]:
        """
        Extract results from an instant vector query.

        Returns empty list if status is not success or resultType is not vector.
        """
        if self.status != "success":
            return []
        if self.data.resultType != "vector":
            return []
        return [PrometheusVectorResult(**r) for r in self.data.result]

    def get_single_value(self) -> float | None:
        """
        Get single numeric value from query result.

        Useful for simple queries that return exactly one value.
        Returns None if no results or query failed.

        PITFALL: Prometheus returns string values, this method handles conversion.
        """
        results = self.get_vector_results()
        if not results:
            return None
        # Value is (timestamp, "string_value") - convert string to float
        return float(results[0].value[1])

    def get_all_values(self) -> list[tuple[dict[str, str], float]]:
        """
        Get all metric/value pairs from query result.

        Returns list of (labels_dict, numeric_value) tuples.
        Useful for queries that return multiple series.
        """
        results = self.get_vector_results()
        return [(r.metric, float(r.value[1])) for r in results]
