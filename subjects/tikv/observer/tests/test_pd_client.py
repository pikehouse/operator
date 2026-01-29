"""
Tests for PD API client.

These tests verify the PDClient correctly:
- Fetches and parses store information from PD API
- Fetches and parses region information from PD API
- Converts PD int IDs to string StoreIds (per RESEARCH.md Pitfall 3)
- Raises on HTTP errors (fail loudly per CONTEXT.md)
"""

import pytest
import httpx
from httpx import Response, Request

from operator_core.types import Store, Region
from tikv_observer.pd_client import PDClient


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport for testing HTTP responses."""

    def __init__(self, responses: dict[str, dict]):
        """
        Initialize with mapping of paths to response data.

        Args:
            responses: Dict mapping URL paths to response data.
                       Each value should have 'status_code' and 'json' keys.
        """
        self._responses = responses

    async def handle_async_request(self, request: Request) -> Response:
        """Handle an async request by returning mocked response."""
        path = request.url.path
        if path in self._responses:
            resp_data = self._responses[path]
            return Response(
                status_code=resp_data.get("status_code", 200),
                json=resp_data.get("json", {}),
                request=request,
            )
        # Return 404 for unknown paths
        return Response(status_code=404, request=request)


@pytest.fixture
def stores_response():
    """Sample PD API response for /pd/api/v1/stores."""
    return {
        "count": 3,
        "stores": [
            {
                "store": {
                    "id": 1,
                    "address": "tikv-0:20160",
                    "state_name": "Up",
                    "version": "8.1.0",
                },
                "status": {
                    "capacity": "100GiB",
                    "available": "80GiB",
                    "leader_count": 100,
                    "region_count": 300,
                },
            },
            {
                "store": {
                    "id": 2,
                    "address": "tikv-1:20160",
                    "state_name": "Up",
                    "version": "8.1.0",
                },
                "status": {
                    "capacity": "100GiB",
                    "available": "70GiB",
                    "leader_count": 95,
                    "region_count": 298,
                },
            },
            {
                "store": {
                    "id": 3,
                    "address": "tikv-2:20160",
                    "state_name": "Down",
                    "version": "8.1.0",
                },
                "status": {
                    "capacity": "100GiB",
                    "available": "90GiB",
                    "leader_count": 0,
                    "region_count": 302,
                },
            },
        ],
    }


@pytest.fixture
def empty_stores_response():
    """Sample PD API response with no stores."""
    return {"count": 0, "stores": []}


@pytest.fixture
def regions_response():
    """Sample PD API response for /pd/api/v1/regions."""
    return {
        "count": 2,
        "regions": [
            {
                "id": 100,
                "leader": {"id": 1001, "store_id": 1},
                "peers": [
                    {"id": 1001, "store_id": 1},
                    {"id": 1002, "store_id": 2},
                    {"id": 1003, "store_id": 3},
                ],
            },
            {
                "id": 200,
                "leader": {"id": 2001, "store_id": 2},
                "peers": [
                    {"id": 2001, "store_id": 2},
                    {"id": 2002, "store_id": 3},
                    {"id": 2003, "store_id": 1},
                ],
            },
        ],
    }


@pytest.fixture
def regions_with_empty_leader_response():
    """
    Sample PD API response with regions that have no elected leader.

    This happens during leader election or when a region is being transferred.
    The API returns an empty leader object {} instead of null.
    """
    return {
        "count": 3,
        "regions": [
            {
                "id": 100,
                "leader": {"id": 1001, "store_id": 1},
                "peers": [
                    {"id": 1001, "store_id": 1},
                    {"id": 1002, "store_id": 2},
                ],
            },
            {
                # Region with empty leader object (no leader elected)
                "id": 200,
                "leader": {},
                "peers": [
                    {"id": 2001, "store_id": 2},
                    {"id": 2002, "store_id": 3},
                ],
            },
            {
                # Region with null leader
                "id": 300,
                "leader": None,
                "peers": [
                    {"id": 3001, "store_id": 1},
                ],
            },
        ],
    }


@pytest.fixture
def single_region_response():
    """Sample PD API response for /pd/api/v1/region/id/{id}."""
    return {
        "id": 100,
        "leader": {"id": 1001, "store_id": 1},
        "peers": [
            {"id": 1001, "store_id": 1},
            {"id": 1002, "store_id": 2},
            {"id": 1003, "store_id": 3},
        ],
    }


class TestGetStores:
    """Tests for PDClient.get_stores() method."""

    @pytest.mark.asyncio
    async def test_get_stores_returns_list_of_stores(self, stores_response):
        """get_stores should return list[Store] with correct fields."""
        transport = MockTransport({
            "/pd/api/v1/stores": {"json": stores_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            stores = await client.get_stores()

        assert len(stores) == 3
        assert all(isinstance(s, Store) for s in stores)

        # Check first store
        assert stores[0].id == "1"  # Int converted to string
        assert stores[0].address == "tikv-0:20160"
        assert stores[0].state == "Up"

        # Check third store (Down state)
        assert stores[2].id == "3"
        assert stores[2].state == "Down"

    @pytest.mark.asyncio
    async def test_get_stores_converts_int_ids_to_strings(self, stores_response):
        """Store IDs should be converted from int to string per RESEARCH.md Pitfall 3."""
        transport = MockTransport({
            "/pd/api/v1/stores": {"json": stores_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            stores = await client.get_stores()

        # All IDs should be strings, not ints
        for store in stores:
            assert isinstance(store.id, str)

    @pytest.mark.asyncio
    async def test_get_stores_empty_returns_empty_list(self, empty_stores_response):
        """get_stores with no stores should return empty list."""
        transport = MockTransport({
            "/pd/api/v1/stores": {"json": empty_stores_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            stores = await client.get_stores()

        assert stores == []

    @pytest.mark.asyncio
    async def test_get_stores_http_error_raises(self):
        """get_stores should raise httpx.HTTPStatusError on HTTP errors."""
        transport = MockTransport({
            "/pd/api/v1/stores": {"status_code": 500, "json": {"error": "Internal error"}}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_stores()


class TestGetRegions:
    """Tests for PDClient.get_regions() method."""

    @pytest.mark.asyncio
    async def test_get_regions_returns_list_of_regions(self, regions_response):
        """get_regions should return list[Region] with leader and peers."""
        transport = MockTransport({
            "/pd/api/v1/regions": {"json": regions_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            regions = await client.get_regions()

        assert len(regions) == 2
        assert all(isinstance(r, Region) for r in regions)

        # Check first region
        assert regions[0].id == 100
        assert regions[0].leader_store_id == "1"  # Int converted to string
        assert regions[0].peer_store_ids == ["1", "2", "3"]  # All strings

    @pytest.mark.asyncio
    async def test_get_regions_converts_store_ids_to_strings(self, regions_response):
        """Peer store IDs should be converted from int to string."""
        transport = MockTransport({
            "/pd/api/v1/regions": {"json": regions_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            regions = await client.get_regions()

        for region in regions:
            assert isinstance(region.leader_store_id, str)
            for peer_id in region.peer_store_ids:
                assert isinstance(peer_id, str)

    @pytest.mark.asyncio
    async def test_get_regions_handles_empty_leader(
        self, regions_with_empty_leader_response
    ):
        """
        get_regions should handle regions with no elected leader.

        PD API returns empty leader object {} during leader election.
        These regions should have empty string leader_store_id.
        """
        transport = MockTransport({
            "/pd/api/v1/regions": {"json": regions_with_empty_leader_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            regions = await client.get_regions()

        assert len(regions) == 3

        # First region has normal leader
        assert regions[0].id == 100
        assert regions[0].leader_store_id == "1"

        # Second region has empty leader object {}
        assert regions[1].id == 200
        assert regions[1].leader_store_id == ""  # Empty string when no leader

        # Third region has null leader
        assert regions[2].id == 300
        assert regions[2].leader_store_id == ""  # Empty string when null leader


class TestGetRegion:
    """Tests for PDClient.get_region() method."""

    @pytest.mark.asyncio
    async def test_get_region_returns_single_region(self, single_region_response):
        """get_region should return a single Region with correct data."""
        transport = MockTransport({
            "/pd/api/v1/region/id/100": {"json": single_region_response}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            region = await client.get_region(100)

        assert isinstance(region, Region)
        assert region.id == 100
        assert region.leader_store_id == "1"
        assert region.peer_store_ids == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_get_region_http_error_raises(self):
        """get_region should raise httpx.HTTPStatusError on HTTP errors."""
        transport = MockTransport({
            "/pd/api/v1/region/id/999": {"status_code": 404, "json": {"error": "Region not found"}}
        })
        async with httpx.AsyncClient(
            transport=transport, base_url="http://pd:2379"
        ) as http:
            client = PDClient(http=http)
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_region(999)
