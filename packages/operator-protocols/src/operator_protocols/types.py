"""
Generic types for the operator protocol system.

This module defines core data structures used to represent distributed
system components and metrics. These types are generic and can be used
by any Subject implementation.

All types use @dataclass for simplicity and immutability.
"""

from dataclasses import dataclass


# Type aliases for common patterns
StoreId = str
"""Unique identifier for a node in a distributed system."""


@dataclass
class Store:
    """
    Represents a node in a distributed system.

    A Store is a single instance/node, typically running on one physical
    or virtual machine. The term "store" is used generically to represent
    any stateful node in a distributed system.

    Attributes:
        id: Unique identifier for this node.
        address: Network address in format "host:port" (e.g., "node-1:8080").
        state: Current node state. Common values:
            - "Up": Node is healthy and serving requests
            - "Down": Node is unreachable or unhealthy
            - "Offline": Node is being drained/decommissioned
            - "Tombstone": Node has been removed from cluster
    """

    id: StoreId
    address: str
    state: str


@dataclass
class StoreMetrics:
    """
    Performance and resource metrics for a single node.

    These metrics are typically collected from monitoring systems and used
    to detect hotspots, resource pressure, and performance degradation.

    Attributes:
        store_id: The node these metrics belong to.
        qps: Queries per second (combined read + write throughput).
        latency_p99_ms: 99th percentile latency in milliseconds.
        disk_used_bytes: Bytes of disk currently used.
        disk_total_bytes: Total disk capacity in bytes.
        cpu_percent: CPU utilization as percentage (0-100).
        raft_lag: Number of replication log entries behind leader (0 if leader).
            For non-Raft systems, this can represent any replication lag metric.
    """

    store_id: StoreId
    qps: float
    latency_p99_ms: float
    disk_used_bytes: int
    disk_total_bytes: int
    cpu_percent: float
    raft_lag: int


@dataclass
class ClusterMetrics:
    """
    Cluster-wide aggregated metrics.

    Provides a high-level view of cluster health and balance.
    Used for detecting imbalances and capacity issues.

    Attributes:
        store_count: Total number of nodes in the cluster.
        region_count: Total number of data partitions across all nodes.
            For non-partitioned systems, this can represent other
            distribution units (shards, buckets, etc.).
        leader_count: Mapping of store_id to number of leaders on that node.
            Used to detect leader/primary imbalance.
    """

    store_count: int
    region_count: int
    leader_count: dict[StoreId, int]
