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

        async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
            # Implementation using PD API
            ...

        # ... implement other methods
    ```

    The TiKVSubject class is a valid Subject without inheriting from it.
    Type checkers will verify the method signatures match.

All methods are async to support non-blocking I/O with httpx clients.
The operator core injects HTTP clients - subjects should not create their own.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from operator_core.types import ClusterMetrics, Region, Store, StoreMetrics

if TYPE_CHECKING:
    from operator_core.actions.registry import ActionDefinition


@runtime_checkable
class Subject(Protocol):
    """
    Interface for subject systems (TiKV, Kafka, etc.).

    A Subject provides observations (read-only data about the system)
    and actions (operations that modify the system state).

    Implementations receive injected HTTP clients for external communication.
    All methods are async to support non-blocking I/O.

    Observations:
        - get_stores: List all stores in the cluster
        - get_hot_write_regions: Find regions with high write traffic
        - get_store_metrics: Get performance metrics for a specific store
        - get_cluster_metrics: Get cluster-wide aggregated metrics

    Actions:
        - transfer_leader: Move region leadership to another store
        - split_region: Split a region into two smaller regions
        - set_leader_schedule_limit: Control leader rebalancing rate
        - set_replica_schedule_limit: Control replica rebalancing rate
        - drain_store: Evacuate all regions from a store

    Config:
        - set_low_space_threshold: Configure disk space threshold
        - set_region_schedule_limit: Control region scheduling rate
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

    # -------------------------------------------------------------------------
    # Actions - Operations that modify system state
    # -------------------------------------------------------------------------

    async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
        """
        Transfer region leadership to another store.

        Used to rebalance leader distribution or evacuate a store.

        Args:
            region_id: The region whose leader should be transferred.
            to_store_id: The destination store for leadership.
        """
        ...

    async def split_region(self, region_id: int) -> None:
        """
        Split a region into two smaller regions.

        Used to break up hotspots and distribute load more evenly.
        The split point is determined automatically by PD.

        Args:
            region_id: The region to split.
        """
        ...

    async def set_leader_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of leader transfers per scheduling cycle.

        Higher values allow faster rebalancing but may cause more
        transient unavailability.

        Args:
            n: Maximum leader transfers per cycle (0 to disable).
        """
        ...

    async def set_replica_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of replica moves per scheduling cycle.

        Controls how aggressively PD redistributes data across stores.

        Args:
            n: Maximum replica moves per cycle (0 to disable).
        """
        ...

    async def drain_store(self, store_id: str) -> None:
        """
        Evacuate all regions from a store.

        Marks the store as offline and triggers migration of all
        regions to other stores. Used before decommissioning a node.

        Args:
            store_id: The store to drain.
        """
        ...

    # -------------------------------------------------------------------------
    # Config - System configuration changes
    # -------------------------------------------------------------------------

    async def set_low_space_threshold(self, percent: float) -> None:
        """
        Set the low disk space threshold percentage.

        When a store's disk usage exceeds this threshold, PD will
        avoid scheduling new regions to it.

        Args:
            percent: Threshold as percentage (0-100).
        """
        ...

    async def set_region_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of region moves per scheduling cycle.

        Controls overall scheduling velocity. Higher values allow
        faster rebalancing but increase cluster load.

        Args:
            n: Maximum region moves per cycle (0 to disable).
        """
        ...

    # -------------------------------------------------------------------------
    # Action Discovery - Runtime action introspection
    # -------------------------------------------------------------------------

    def get_action_definitions(self) -> list["ActionDefinition"]:
        """
        Return definitions of all actions this subject supports.

        Used by ActionRegistry to discover available actions at runtime.
        Each definition includes the action name, parameter schema,
        description, and risk level.

        Returns:
            List of ActionDefinition objects describing available actions.
        """
        ...
