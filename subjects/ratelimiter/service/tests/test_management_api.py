"""Integration tests for management API endpoints."""

import pytest
import redis.asyncio as redis
from fastapi.testclient import TestClient

from ratelimiter_service.main import app
from ratelimiter_service.limiter import RateLimiter


@pytest.fixture
async def redis_client():
    """Create Redis client for tests."""
    client = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    yield client
    # Cleanup test keys
    async for key in client.scan_iter("ratelimit:test:*"):
        await client.delete(key)
    async for key in client.scan_iter("ratelimit:limit:test:*"):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
async def limiter(redis_client):
    """Create RateLimiter instance."""
    return RateLimiter(redis_client)


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


class TestResetCounterEndpoint:
    """Tests for POST /api/counters/{key}/reset endpoint."""

    @pytest.mark.asyncio
    async def test_reset_counter_existing_key(self, client, limiter):
        """Reset should clear counter for existing key."""
        key = "test:reset1"

        # Create some counter data
        await limiter.check(key, limit=10, window_ms=60000)
        await limiter.check(key, limit=10, window_ms=60000)

        count = await limiter.get_counter(key)
        assert count == 2

        # Reset via API
        response = client.post(f"/api/counters/{key}/reset")
        assert response.status_code == 200

        data = response.json()
        assert data["key"] == key
        assert data["reset"] is True

        # Verify counter cleared
        count = await limiter.get_counter(key)
        assert count == 0

    @pytest.mark.asyncio
    async def test_reset_counter_nonexistent_key(self, client, limiter):
        """Reset should return success with reset=False for nonexistent key."""
        key = "test:nonexistent"

        # Reset key that doesn't exist
        response = client.post(f"/api/counters/{key}/reset")
        assert response.status_code == 200

        data = response.json()
        assert data["key"] == key
        assert data["reset"] is False


class TestUpdateLimitEndpoint:
    """Tests for PUT /api/limits/{key} endpoint."""

    @pytest.mark.asyncio
    async def test_update_limit_basic(self, client, limiter):
        """Update limit should store per-key limit."""
        key = "test:update1"

        # Update limit via API
        response = client.put(
            f"/api/limits/{key}",
            json={"limit": 50, "window_ms": 30000},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["key"] == key
        assert data["limit"] == 50
        assert data["window_ms"] == 30000
        assert data["updated"] is True

        # Verify stored in Redis
        stored = await limiter.get_limit(key)
        assert stored is not None
        assert stored[0] == 50  # limit
        assert stored[1] == 30000  # window_ms

    @pytest.mark.asyncio
    async def test_update_limit_default_window(self, client, limiter):
        """Update limit without window_ms should use default."""
        key = "test:update2"

        # Update limit without window_ms
        response = client.put(
            f"/api/limits/{key}",
            json={"limit": 100},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["key"] == key
        assert data["limit"] == 100
        assert data["window_ms"] == 60000  # Default from config
        assert data["updated"] is True

    @pytest.mark.asyncio
    async def test_update_limit_overwrites_previous(self, client, limiter):
        """Update limit should overwrite previous limit."""
        key = "test:update3"

        # Set initial limit
        await limiter.update_limit(key, 25, 15000)

        # Update to new limit
        response = client.put(
            f"/api/limits/{key}",
            json={"limit": 75, "window_ms": 45000},
        )
        assert response.status_code == 200

        # Verify new limit stored
        stored = await limiter.get_limit(key)
        assert stored is not None
        assert stored[0] == 75
        assert stored[1] == 45000


class TestIntegration:
    """Integration tests combining multiple operations."""

    @pytest.mark.asyncio
    async def test_reset_and_update_workflow(self, client, limiter):
        """Test workflow of updating limit, using it, and resetting."""
        key = "test:workflow"

        # Update limit to 5 requests
        response = client.put(
            f"/api/limits/{key}",
            json={"limit": 5},
        )
        assert response.status_code == 200

        # Verify limit stored
        stored = await limiter.get_limit(key)
        assert stored is not None
        assert stored[0] == 5

        # Make some requests
        await limiter.check(key, limit=5, window_ms=60000)
        await limiter.check(key, limit=5, window_ms=60000)
        await limiter.check(key, limit=5, window_ms=60000)

        count = await limiter.get_counter(key)
        assert count == 3

        # Reset counter
        response = client.post(f"/api/counters/{key}/reset")
        assert response.status_code == 200
        assert response.json()["reset"] is True

        # Verify counter cleared but limit still exists
        count = await limiter.get_counter(key)
        assert count == 0

        stored = await limiter.get_limit(key)
        assert stored is not None
        assert stored[0] == 5
