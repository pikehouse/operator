"""
TiKV subject implementation for the AI-powered operator.

This package provides the TiKV-specific implementation of the Subject interface
defined in operator-core. It includes:

- PD API client for cluster state observation
- Prometheus metrics client for performance monitoring
- TiKV-specific response types for API parsing
- TiKV invariant definitions
- Log parser for event extraction
"""

from operator_tikv.log_parser import (
    LeadershipChange,
    LogEntry,
    extract_leadership_changes,
    parse_log_line,
)
from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient
from operator_tikv.types import (
    # PD API types
    PDRegionLeader,
    PDRegionPeer,
    PDRegionResponse,
    PDRegionsResponse,
    PDStoreInfo,
    PDStoreItem,
    PDStoresResponse,
    PDStoreStatus,
    # Prometheus types
    PrometheusData,
    PrometheusQueryResponse,
    PrometheusRangeResult,
    PrometheusVectorResult,
)

__all__ = [
    # Clients
    "PDClient",
    "PrometheusClient",
    # PD API types
    "PDStoreInfo",
    "PDStoreStatus",
    "PDStoreItem",
    "PDStoresResponse",
    "PDRegionPeer",
    "PDRegionLeader",
    "PDRegionResponse",
    "PDRegionsResponse",
    # Prometheus types
    "PrometheusVectorResult",
    "PrometheusRangeResult",
    "PrometheusData",
    "PrometheusQueryResponse",
    # Log parser types and functions
    "LogEntry",
    "LeadershipChange",
    "parse_log_line",
    "extract_leadership_changes",
]
