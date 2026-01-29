"""
TiKV subject implementation for the AI-powered operator.

This package provides the TiKV-specific implementation of the Subject interface
defined in operator-protocols. It includes:

- TiKVSubject: Complete Subject Protocol implementation (SubjectProtocol)
- TiKVInvariantChecker: Health invariant checking (InvariantCheckerProtocol)
- PD API client for cluster state observation
- Prometheus metrics client for performance monitoring
- TiKV-specific response types for API parsing
- Factory function for CLI integration
- Log parser for event extraction
"""

# Subject-specific context for agent system prompt
AGENT_PROMPT = """
TiKV-specific context:
- TiKV is a distributed key-value store using Raft consensus
- PD (Placement Driver) manages cluster scheduling
- Containers: pd0, tikv0, tikv1, tikv2
- Key commands: pd-ctl, tikv-ctl
- Common issues: region leader imbalance, hot spots, store offline
"""

# Re-export InvariantViolation from operator_protocols for convenience
from operator_protocols import InvariantViolation

from tikv_observer.factory import create_tikv_subject_and_checker
from tikv_observer.invariants import (
    HIGH_LATENCY_CONFIG,
    InvariantConfig,
    LOW_DISK_SPACE_CONFIG,
    STORE_DOWN_CONFIG,
    TiKVInvariantChecker,
)
from tikv_observer.log_parser import (
    LeadershipChange,
    LogEntry,
    extract_leadership_changes,
    parse_log_line,
)
from tikv_observer.pd_client import PDClient
from tikv_observer.prom_client import PrometheusClient
from tikv_observer.subject import TiKVSubject
from tikv_observer.types import (
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

# Backward compatibility alias - InvariantChecker is now TiKVInvariantChecker
InvariantChecker = TiKVInvariantChecker

__all__ = [
    # Agent prompt
    "AGENT_PROMPT",
    # Subject
    "TiKVSubject",
    # Factory
    "create_tikv_subject_and_checker",
    # Clients
    "PDClient",
    "PrometheusClient",
    # Invariants (TiKVInvariantChecker is the new name, InvariantChecker kept for backward compat)
    "TiKVInvariantChecker",
    "InvariantChecker",  # Backward compatibility alias
    "InvariantConfig",
    "InvariantViolation",  # Re-exported from operator_protocols
    "STORE_DOWN_CONFIG",
    "HIGH_LATENCY_CONFIG",
    "LOW_DISK_SPACE_CONFIG",
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
