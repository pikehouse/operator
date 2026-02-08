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

Diagnostic guidance for exotic failure modes:
- Zombie/frozen process (SIGSTOP): container looks alive in docker ps but process
  is frozen. Check with `ps aux` inside container or `docker top`. Resume with
  `docker kill --signal CONT <container>`.
- Packet loss: intermittent failures, some RPCs succeed. Check `tc qdisc show dev eth0`
  inside the container for netem loss rules. Remove with `tc qdisc del dev eth0 root`.
- Leader imbalance: all leaders concentrated on one store. Check leader distribution
  via PD API `GET /pd/api/v1/stores` (leader_count field). Use PD operator
  `transfer-leader` to rebalance, or let balance-leader-scheduler auto-fix.
- PD issues: control plane down but data plane may still serve existing leaders.
  Check PD health with `GET /pd/api/v1/health`. Distinguish control plane vs data
  plane impact. Restart PD container if needed.
- Raft lag: followers behind leader, usually self-resolves after store resumes.
  Check `tikv_raftstore_log_lag` metric. High lag after a pause is expected.
- Missing metrics: store is Up per PD but Prometheus has no data. Process may be
  frozen (SIGSTOP) or network is partially broken. Cross-reference PD store state
  with actual container health.
"""

# Re-export InvariantViolation from operator_protocols for convenience
from operator_protocols import InvariantViolation

from tikv_observer.factory import create_tikv_subject_and_checker
from tikv_observer.invariants import (
    HIGH_LATENCY_CONFIG,
    HIGH_RAFT_LAG_CONFIG,
    InvariantConfig,
    LEADER_IMBALANCE_CONFIG,
    LOW_DISK_SPACE_CONFIG,
    METRICS_UNAVAILABLE_CONFIG,
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
    # TiKV domain types
    Region,
    RegionId,
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
    "HIGH_RAFT_LAG_CONFIG",
    "LEADER_IMBALANCE_CONFIG",
    "METRICS_UNAVAILABLE_CONFIG",
    # TiKV domain types
    "Region",
    "RegionId",
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
