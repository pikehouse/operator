"""
Subject Protocol - Interface for subject systems.

This module defines the Subject Protocol, which is the core abstraction
enabling the operator to work with different distributed systems (TiKV,
Kafka, etc.) without coupling to their specific implementations.

The Protocol pattern enables structural subtyping - a class implementing
all the required methods is considered a Subject without explicitly
inheriting from it. This provides:

1. Clean separation between operator core and subject implementations
2. Easy addition of new subjects without modifying core code
3. Type checking at development time via static analysis
4. Optional runtime checking via @runtime_checkable decorator

Example:
    A new subject can be added by implementing the protocol methods:

    ```python
    class TiKVSubject:
        async def get_stores(self) -> list[Store]:
            # Implementation using PD API
            ...

        # ... implement other methods
    ```

    The TiKVSubject class is a valid Subject without inheriting from it.
    Type checkers will verify the method signatures match.

All methods are async to support non-blocking I/O with httpx clients.
The operator core injects HTTP clients - subjects should not create their own.
"""

from typing import Protocol, runtime_checkable

from operator_core.types import ClusterMetrics, Region, Store, StoreMetrics


@runtime_checkable
class Subject(Protocol):
    """
    Interface for subject systems (TiKV, Kafka, etc.).

    A Subject provides observations (read-only data about the system).

    Implementations receive injected HTTP clients for external communication.
    All methods are async to support non-blocking I/O.

    Observations:
        - get_stores: List all stores in the cluster
        - get_hot_write_regions: Find regions with high write traffic
        - get_store_metrics: Get performance metrics for a specific store
        - get_cluster_metrics: Get cluster-wide aggregated metrics
    """

    # -------------------------------------------------------------------------
    # Observations - Read-only queries about system state
    # -------------------------------------------------------------------------

    async def get_stores(self) -> list[Store]:
        """
        Get all stores in the cluster.

        Returns:
            List of Store objects representing all TiKV nodes.
        """
        ...

    async def get_hot_write_regions(self) -> list[Region]:
        """
        Get regions with high write traffic.

        Used to detect hotspots that may need splitting or leader
        redistribution.

        Returns:
            List of Region objects with high write QPS.
        """
        ...

    async def get_store_metrics(self, store_id: str) -> StoreMetrics:
        """
        Get performance metrics for a specific store.

        Args:
            store_id: The unique identifier of the store.

        Returns:
            StoreMetrics containing QPS, latency, disk, CPU, and Raft lag.
        """
        ...

    async def get_cluster_metrics(self) -> ClusterMetrics:
        """
        Get cluster-wide aggregated metrics.

        Returns:
            ClusterMetrics containing store count, region count, and
            leader distribution.
        """
        ...
