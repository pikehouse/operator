"""
Re-exports generic types from operator_protocols.

This module provides convenient access to generic distributed system types.
All types are defined in operator_protocols and re-exported here for
backward compatibility.
"""

from operator_protocols.types import ClusterMetrics, Store, StoreId, StoreMetrics

__all__ = [
    "Store",
    "StoreId",
    "StoreMetrics",
    "ClusterMetrics",
]
