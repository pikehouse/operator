"""
PD API client for TiKV cluster state observation.

This module provides the PDClient class for querying the Placement Driver (PD)
HTTP API to observe TiKV cluster state including stores, regions, and topology.

PDClient receives an injected httpx.AsyncClient with base_url set to the PD server.
All methods are async and fail loudly on HTTP errors per CONTEXT.md.

PD API Documentation:
- https://tikv.org/docs/6.5/deploy/monitor/api/
- https://docs.pingcap.com/tidb/stable/tidb-monitoring-api/
"""

from dataclasses import dataclass

import httpx

from operator_core.types import Region, RegionId, Store
from operator_tikv.types import (
    PDRegionResponse,
    PDRegionsResponse,
    PDStoresResponse,
)


@dataclass
class PDClient:
    """
    PD API client with injected httpx client.

    Queries the Placement Driver HTTP API for cluster state information.
    Converts PD API response types to operator-core types.

    Attributes:
        http: Pre-configured httpx.AsyncClient with base_url set to PD server.

    Example:
        async with httpx.AsyncClient(base_url="http://pd:2379") as http:
            client = PDClient(http=http)
            stores = await client.get_stores()
            for store in stores:
                print(f"Store {store.id} at {store.address}: {store.state}")
    """

    http: httpx.AsyncClient

    async def get_stores(self) -> list[Store]:
        """
        Get all stores in the TiKV cluster.

        Calls GET /pd/api/v1/stores and converts the response to a list
        of operator-core Store objects.

        Returns:
            List of Store objects representing TiKV nodes.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.

        Note:
            Store IDs are converted from int (PD API) to str (operator-core)
            per RESEARCH.md Pitfall 3.
        """
        response = await self.http.get("/pd/api/v1/stores")
        response.raise_for_status()

        data = PDStoresResponse.model_validate(response.json())

        return [
            Store(
                id=str(item.store.id),  # Convert int to str per Pitfall 3
                address=item.store.address,
                state=item.store.state_name,
            )
            for item in data.stores
        ]

    async def get_regions(self) -> list[Region]:
        """
        Get all regions in the TiKV cluster.

        Calls GET /pd/api/v1/regions and converts the response to a list
        of operator-core Region objects.

        Returns:
            List of Region objects representing key ranges.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.

        Note:
            Store IDs in leader and peers are converted from int to str
            per RESEARCH.md Pitfall 3.
        """
        response = await self.http.get("/pd/api/v1/regions")
        response.raise_for_status()

        data = PDRegionsResponse.model_validate(response.json())

        return [self._region_from_pd(r) for r in data.regions]

    async def get_region(self, region_id: RegionId) -> Region:
        """
        Get a specific region by ID.

        Calls GET /pd/api/v1/region/id/{id} and converts the response to
        an operator-core Region object.

        Args:
            region_id: The ID of the region to retrieve.

        Returns:
            Region object with leader and peer information.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).
            pydantic.ValidationError: On malformed response data.

        Note:
            Store IDs in leader and peers are converted from int to str
            per RESEARCH.md Pitfall 3.
        """
        response = await self.http.get(f"/pd/api/v1/region/id/{region_id}")
        response.raise_for_status()

        data = PDRegionResponse.model_validate(response.json())

        return self._region_from_pd(data)

    def _region_from_pd(self, pd_region: PDRegionResponse) -> Region:
        """
        Convert a PD API region response to an operator-core Region.

        Handles the conversion of store IDs from int (PD API) to str
        (operator-core StoreId type alias).

        Args:
            pd_region: PDRegionResponse from PD API.

        Returns:
            Region object with string store IDs.
        """
        # Leader store ID - empty string if no leader or leader has no store_id
        # PD API returns {} for regions with no elected leader
        leader = pd_region.leader
        if leader and leader.store_id is not None:
            leader_id = str(leader.store_id)
        else:
            leader_id = ""

        # Peer store IDs - all stores holding replicas (including leader)
        peer_ids = [str(p.store_id) for p in pd_region.peers]

        return Region(
            id=pd_region.id,
            leader_store_id=leader_id,
            peer_store_ids=peer_ids,
        )

    # -------------------------------------------------------------------------
    # Operator/Scheduler Methods - POST operations for scheduling actions
    # -------------------------------------------------------------------------

    async def add_transfer_leader_operator(
        self, region_id: int, to_store_id: int
    ) -> None:
        """
        Add transfer-leader operator via PD API.

        Posts a transfer-leader operator request to PD, which schedules
        the region's leadership to move to the specified store.

        Args:
            region_id: The region whose leader should be transferred.
            to_store_id: The destination store ID for leadership.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).

        Note:
            Fire-and-forget: Returns when PD accepts the request.
            Does not wait for actual transfer completion.
        """
        response = await self.http.post(
            "/pd/api/v1/operators",
            json={
                "name": "transfer-leader",
                "region_id": region_id,
                "store_id": to_store_id,
            },
        )
        response.raise_for_status()

    async def add_transfer_peer_operator(
        self, region_id: int, from_store_id: int, to_store_id: int
    ) -> None:
        """
        Add transfer-peer operator via PD API.

        Posts a transfer-peer operator request to PD, which schedules
        the region's replica to move from one store to another.

        Args:
            region_id: The region whose replica should be moved.
            from_store_id: The source store ID holding the replica.
            to_store_id: The destination store ID for the replica.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).

        Note:
            Fire-and-forget: Returns when PD accepts the request.
            Does not wait for actual transfer completion.
        """
        response = await self.http.post(
            "/pd/api/v1/operators",
            json={
                "name": "transfer-peer",
                "region_id": region_id,
                "from_store_id": from_store_id,
                "to_store_id": to_store_id,
            },
        )
        response.raise_for_status()

    async def add_evict_leader_scheduler(self, store_id: int) -> None:
        """
        Add evict-leader-scheduler via PD API.

        Posts an evict-leader-scheduler request to PD, which continuously
        moves all region leaders away from the specified store.

        Args:
            store_id: The store ID to drain leaders from.

        Raises:
            httpx.HTTPStatusError: On HTTP errors (4xx, 5xx responses).

        Note:
            This is a persistent scheduler - leaders are continuously
            evicted until the scheduler is removed via DELETE.
        """
        response = await self.http.post(
            "/pd/api/v1/schedulers",
            json={
                "name": "evict-leader-scheduler",
                "store_id": store_id,
            },
        )
        response.raise_for_status()
