"""
TiKVSubject - TiKV implementation of the Subject Protocol.

This module provides TiKVSubject, the complete implementation of the
Subject Protocol defined in operator-core for TiKV distributed databases.

TiKVSubject:
- Implements all Subject Protocol observations using PDClient and PrometheusClient
- Implements core actions: transfer_leader, transfer_peer, drain_store
- Provides get_config() class method for capability registration
- Provides get_action_definitions() for Phase 12 ActionRegistry integration
- Uses injected HTTP clients per CONTEXT.md

Per CONTEXT.md decisions:
- TiKV is the primary subject (referenced as 'tikv')
- Fixed thresholds for latency alerting
- Conservative resource thresholds (70%+)
- Fire-and-forget action semantics (return on API success)
"""

from dataclasses import dataclass

from operator_core.config import Action, Observation, SLO, SubjectConfig
from operator_core.types import ClusterMetrics, Region, Store, StoreMetrics

from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient


# TiKV Subject configuration for capability registration
TIKV_CONFIG = SubjectConfig(
    name="tikv",
    actions=[
        Action(
            "transfer_leader",
            ["region_id", "to_store_id"],
            description="Transfer region leadership to another store",
        ),
        Action(
            "split_region",
            ["region_id"],
            description="Split a hot region into two smaller regions",
        ),
        Action(
            "set_leader_schedule_limit",
            ["n"],
            description="Set maximum leader transfers per scheduling cycle",
        ),
        Action(
            "set_replica_schedule_limit",
            ["n"],
            description="Set maximum replica moves per scheduling cycle",
        ),
        Action(
            "transfer_peer",
            ["region_id", "from_store_id", "to_store_id"],
            description="Move region replica from one store to another",
        ),
        Action(
            "drain_store",
            ["store_id"],
            description="Evacuate all leaders from a store",
        ),
        Action(
            "set_low_space_threshold",
            ["percent"],
            description="Set low disk space threshold percentage",
        ),
        Action(
            "set_region_schedule_limit",
            ["n"],
            description="Set maximum region moves per scheduling cycle",
        ),
    ],
    observations=[
        Observation(
            "get_stores",
            "list[Store]",
            description="List all TiKV stores in the cluster",
        ),
        Observation(
            "get_hot_write_regions",
            "list[Region]",
            description="Find regions with high write traffic",
        ),
        Observation(
            "get_store_metrics",
            "StoreMetrics",
            description="Get performance metrics for a specific store",
        ),
        Observation(
            "get_cluster_metrics",
            "ClusterMetrics",
            description="Get cluster-wide aggregated metrics",
        ),
    ],
    slos=[
        SLO(
            "write_latency_p99",
            target=100.0,
            unit="ms",
            grace_period_s=60,
            description="99th percentile write latency threshold",
        ),
        SLO(
            "disk_usage",
            target=70.0,
            unit="percent",
            grace_period_s=0,
            description="Maximum disk usage percentage per store",
        ),
        SLO(
            "store_availability",
            target=100.0,
            unit="percent",
            grace_period_s=0,
            description="All stores should be in Up state",
        ),
    ],
)


@dataclass
class TiKVSubject:
    """
    TiKV implementation of the Subject Protocol.

    Provides observations about TiKV cluster state through PD API and
    Prometheus metrics. Implements action methods for leader transfer,
    peer transfer, and store drain operations.

    Attributes:
        pd: PDClient for cluster state queries and action execution
        prom: PrometheusClient for performance metrics

    Example:
        async with httpx.AsyncClient(base_url="http://pd:2379") as pd_http:
            async with httpx.AsyncClient(base_url="http://prometheus:9090") as prom_http:
                subject = TiKVSubject(
                    pd=PDClient(http=pd_http),
                    prom=PrometheusClient(http=prom_http),
                )
                stores = await subject.get_stores()
                for store in stores:
                    metrics = await subject.get_store_metrics(store.id)
                    print(f"Store {store.id}: {metrics.qps} QPS")
    """

    pd: PDClient
    prom: PrometheusClient

    @classmethod
    def get_config(cls) -> SubjectConfig:
        """
        Return TiKV subject configuration for capability registration.

        This config describes what actions and observations the TiKV subject
        supports, enabling the operator core to understand capabilities
        and monitor SLO compliance.

        Returns:
            SubjectConfig with TiKV-specific actions, observations, and SLOs.
        """
        return TIKV_CONFIG

    # -------------------------------------------------------------------------
    # Observations - Read-only queries about system state
    # -------------------------------------------------------------------------

    async def get_stores(self) -> list[Store]:
        """
        Get all stores in the TiKV cluster.

        Delegates to PDClient to query PD API for store information.

        Returns:
            List of Store objects representing all TiKV nodes.
        """
        return await self.pd.get_stores()

    async def get_hot_write_regions(self) -> list[Region]:
        """
        Get regions with high write traffic.

        Currently returns all regions. Future implementation will filter
        by write QPS from Prometheus metrics.

        Returns:
            List of Region objects (currently all regions).
        """
        # TODO: Filter by write QPS when hotspot detection is implemented
        return await self.pd.get_regions()

    async def get_store_metrics(self, store_id: str) -> StoreMetrics:
        """
        Get performance metrics for a specific store.

        Combines data from PD (store address) and Prometheus (metrics)
        to build a complete StoreMetrics object.

        Args:
            store_id: The unique identifier of the store.

        Returns:
            StoreMetrics containing QPS, latency, disk, CPU, and Raft lag.

        Raises:
            ValueError: If store_id is not found in the cluster.
        """
        # Get store address from PD
        stores = await self.pd.get_stores()
        store = next((s for s in stores if s.id == store_id), None)
        if store is None:
            raise ValueError(f"Store {store_id} not found")

        # Get metrics from Prometheus using store address
        return await self.prom.get_store_metrics(
            store_id=store_id,
            store_address=store.address,
        )

    async def get_cluster_metrics(self) -> ClusterMetrics:
        """
        Get cluster-wide aggregated metrics.

        Queries PD for store and region counts, and calculates
        leader distribution across stores.

        Returns:
            ClusterMetrics containing store count, region count,
            and leader distribution.
        """
        stores = await self.pd.get_stores()
        regions = await self.pd.get_regions()

        # Calculate leader count per store
        leader_count: dict[str, int] = {}
        for store in stores:
            leader_count[store.id] = 0

        for region in regions:
            if region.leader_store_id:
                leader_count[region.leader_store_id] = (
                    leader_count.get(region.leader_store_id, 0) + 1
                )

        return ClusterMetrics(
            store_count=len(stores),
            region_count=len(regions),
            leader_count=leader_count,
        )

    # -------------------------------------------------------------------------
    # Actions - Operations that modify system state
    # -------------------------------------------------------------------------

    async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
        """
        Transfer region leadership to another store.

        Fire-and-forget: returns when PD API accepts the request.
        Does not wait for actual leader transfer completion.

        Args:
            region_id: The region whose leader should be transferred.
            to_store_id: The destination store ID for leadership.

        Raises:
            httpx.HTTPStatusError: On PD API errors (4xx, 5xx).
        """
        await self.pd.add_transfer_leader_operator(region_id, int(to_store_id))

    async def transfer_peer(
        self, region_id: int, from_store_id: str, to_store_id: str
    ) -> None:
        """
        Move region replica from one store to another.

        Fire-and-forget: returns when PD API accepts the request.
        Does not wait for actual replica transfer completion.

        Args:
            region_id: The region whose replica should be moved.
            from_store_id: The source store ID holding the replica.
            to_store_id: The destination store ID for the replica.

        Raises:
            httpx.HTTPStatusError: On PD API errors (4xx, 5xx).
        """
        await self.pd.add_transfer_peer_operator(
            region_id, int(from_store_id), int(to_store_id)
        )

    async def split_region(self, region_id: int) -> None:
        """
        Split a region into two smaller regions.

        Note:
            Action implementation deferred to Phase 5.

        Raises:
            NotImplementedError: Always - action not yet implemented.
        """
        raise NotImplementedError("Actions deferred to Phase 5")

    async def set_leader_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of leader transfers per scheduling cycle.

        Note:
            Action implementation deferred to Phase 5.

        Raises:
            NotImplementedError: Always - action not yet implemented.
        """
        raise NotImplementedError("Actions deferred to Phase 5")

    async def set_replica_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of replica moves per scheduling cycle.

        Note:
            Action implementation deferred to Phase 5.

        Raises:
            NotImplementedError: Always - action not yet implemented.
        """
        raise NotImplementedError("Actions deferred to Phase 5")

    async def drain_store(self, store_id: str) -> None:
        """
        Evacuate all leaders from a store.

        Creates an evict-leader-scheduler that continuously moves leaders
        away from the specified store until the scheduler is removed.

        Fire-and-forget: returns when PD API accepts the request.
        Does not wait for actual leader evacuation completion.

        Args:
            store_id: The store ID to drain leaders from.

        Raises:
            httpx.HTTPStatusError: On PD API errors (4xx, 5xx).

        Note:
            This is a persistent scheduler - leaders are continuously
            evicted until the scheduler is removed via PD API.
        """
        await self.pd.add_evict_leader_scheduler(int(store_id))

    async def set_low_space_threshold(self, percent: float) -> None:
        """
        Set the low disk space threshold percentage.

        Note:
            Action implementation deferred to Phase 5.

        Raises:
            NotImplementedError: Always - action not yet implemented.
        """
        raise NotImplementedError("Actions deferred to Phase 5")

    async def set_region_schedule_limit(self, n: int) -> None:
        """
        Set the maximum number of region moves per scheduling cycle.

        Note:
            Action implementation deferred to Phase 5.

        Raises:
            NotImplementedError: Always - action not yet implemented.
        """
        raise NotImplementedError("Actions deferred to Phase 5")
