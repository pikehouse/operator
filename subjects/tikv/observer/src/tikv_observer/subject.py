"""
TiKVSubject - TiKV implementation of the Subject Protocol.

This module provides TiKVSubject, the complete implementation of the
SubjectProtocol defined in operator-protocols for TiKV distributed databases.

TiKVSubject:
- Implements SubjectProtocol with observe() method returning dict[str, Any]
- Uses injected HTTP clients per CONTEXT.md

Per CONTEXT.md decisions:
- TiKV is the primary subject (referenced as 'tikv')
- Fixed thresholds for latency alerting
- Conservative resource thresholds (70%+)
"""

from dataclasses import dataclass
from typing import Any

from operator_core.types import Region
from operator_protocols.types import ClusterMetrics, Store, StoreMetrics

from tikv_observer.pd_client import PDClient
from tikv_observer.prom_client import PrometheusClient


@dataclass
class TiKVSubject:
    """
    TiKV implementation of the Subject Protocol.

    Provides observations about TiKV cluster state through PD API and
    Prometheus metrics.

    Attributes:
        pd: PDClient for cluster state queries
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

    # -------------------------------------------------------------------------
    # SubjectProtocol.observe() - Generic observation interface
    # -------------------------------------------------------------------------

    async def observe(self) -> dict[str, Any]:
        """
        Gather current TiKV cluster observations.

        Implements SubjectProtocol.observe() by collecting store states,
        cluster metrics, and per-store metrics into a unified observation dict.

        Returns:
            Dictionary with the following structure:
            {
                "stores": [{"id": str, "address": str, "state": str}, ...],
                "cluster_metrics": {
                    "store_count": int,
                    "region_count": int,
                    "leader_count": {store_id: int, ...}
                },
                "store_metrics": {
                    store_id: {
                        "qps": float,
                        "latency_p99_ms": float,
                        "disk_used_bytes": int,
                        "disk_total_bytes": int,
                        "cpu_percent": float,
                        "raft_lag": int
                    }, ...
                }
            }

        Note:
            Store metrics are only collected for stores in "Up" state.
            Failed metric collection is silently skipped to avoid
            blocking the entire observation.
        """
        # Get store states
        stores = await self.pd.get_stores()

        # Get cluster-level metrics
        cluster_metrics = await self.get_cluster_metrics()

        # Get per-store metrics for up stores
        store_metrics: dict[str, dict[str, Any]] = {}
        for store in stores:
            if store.state == "Up":
                try:
                    metrics = await self.get_store_metrics(store.id)
                    store_metrics[store.id] = {
                        "qps": metrics.qps,
                        "latency_p99_ms": metrics.latency_p99_ms,
                        "disk_used_bytes": metrics.disk_used_bytes,
                        "disk_total_bytes": metrics.disk_total_bytes,
                        "cpu_percent": metrics.cpu_percent,
                        "raft_lag": metrics.raft_lag,
                    }
                except Exception:
                    # Skip failed metrics - don't block observation
                    pass

        return {
            "stores": [
                {"id": s.id, "address": s.address, "state": s.state} for s in stores
            ],
            "cluster_metrics": {
                "store_count": cluster_metrics.store_count,
                "region_count": cluster_metrics.region_count,
                "leader_count": cluster_metrics.leader_count,
            },
            "store_metrics": store_metrics,
        }

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
