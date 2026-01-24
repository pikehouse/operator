"""
Shared data types for the operator system.

This module defines the core data structures used to represent TiKV cluster
components and metrics. These are internal types used by the operator core
and subject implementations - not API models.

All types use @dataclass for simplicity and immutability. Pydantic models
are reserved for config file parsing and API responses.
"""

from dataclasses import dataclass

# Type aliases for common patterns
StoreId = str
"""Unique identifier for a TiKV store (node)."""

RegionId = int
"""Unique identifier for a TiKV region (key range)."""


@dataclass
class Store:
    """
    Represents a TiKV store (node) in the cluster.

    A store is a single TiKV instance, typically running on one physical
    or virtual machine. Stores hold replicas of regions and participate
    in Raft consensus.

    Attributes:
        id: Unique store identifier assigned by PD.
        address: Network address in format "host:port" (e.g., "tikv-1:20160").
        state: Current store state - one of:
            - "Up": Store is healthy and serving requests
            - "Down": Store is unreachable or unhealthy
            - "Offline": Store is being drained/decommissioned
            - "Tombstone": Store has been removed from cluster
    """

    id: StoreId
    address: str
    state: str


@dataclass
class Region:
    """
    Represents a TiKV region (key range).

    A region is a contiguous range of keys, replicated across multiple stores
    using Raft consensus. Each region has exactly one leader that handles
    reads and writes, and multiple followers that replicate data.

    Attributes:
        id: Unique region identifier assigned by PD.
        leader_store_id: ID of the store currently holding the region leader.
        peer_store_ids: IDs of all stores holding replicas (including leader).
    """

    id: RegionId
    leader_store_id: StoreId
    peer_store_ids: list[StoreId]


@dataclass
class StoreMetrics:
    """
    Performance and resource metrics for a single TiKV store.

    These metrics are typically collected from Prometheus and used to
    detect hotspots, resource pressure, and performance degradation.

    Attributes:
        store_id: The store these metrics belong to.
        qps: Queries per second (combined read + write).
        latency_p99_ms: 99th percentile latency in milliseconds.
        disk_used_bytes: Bytes of disk currently used.
        disk_total_bytes: Total disk capacity in bytes.
        cpu_percent: CPU utilization as percentage (0-100).
        raft_lag: Number of Raft log entries behind leader (0 if leader).
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
        store_count: Total number of stores in the cluster.
        region_count: Total number of regions across all stores.
        leader_count: Mapping of store_id to number of region leaders on that store.
            Used to detect leader imbalance.
    """

    store_count: int
    region_count: int
    leader_count: dict[StoreId, int]
