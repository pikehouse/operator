"""
Shared data types for the operator system.

This module re-exports generic types from operator_protocols and defines
TiKV-specific types for backward compatibility.

Generic types (from operator_protocols):
- Store: Generic node in a distributed system
- StoreMetrics: Performance metrics for a node
- ClusterMetrics: Cluster-wide aggregated metrics
- StoreId: Type alias for node identifiers

TiKV-specific types (defined locally, deprecated):
- Region: TiKV region (key range)
- RegionId: TiKV region identifier

NOTE: Region and RegionId are TiKV-specific and should be imported from
operator_tikv in new code. They are kept here only for backward compatibility.
"""

from dataclasses import dataclass

# Re-export generic types from operator_protocols
from operator_protocols import Store, StoreId, StoreMetrics, ClusterMetrics

# TiKV-specific types - DEPRECATED
# These should be imported from operator_tikv in new code.
# Kept here for backward compatibility only.

RegionId = int
"""Unique identifier for a TiKV region (key range).

DEPRECATED: This is TiKV-specific. Use operator_tikv.types.RegionId in new code.
"""


@dataclass
class Region:
    """
    Represents a TiKV region (key range).

    DEPRECATED: This is TiKV-specific. Use operator_tikv.types.Region in new code.

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


__all__ = [
    # Re-exported from operator_protocols (generic)
    "Store",
    "StoreId",
    "StoreMetrics",
    "ClusterMetrics",
    # TiKV-specific (deprecated, for backward compatibility)
    "Region",
    "RegionId",
]
