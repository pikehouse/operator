"""Tests for the sliding window rate limiter."""

import asyncio

import pytest
import redis.asyncio as redis

from ratelimiter_service.limiter import RateLimiter, RateLimitResult


@pytest.fixture
async def redis_client():
    """Create Redis client for tests."""
    client = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
    yield client
    # Cleanup test keys
    async for key in client.scan_iter("ratelimit:test:*"):
        await client.delete(key)
    await client.aclose()


@pytest.fixture
async def limiter(redis_client):
    """Create RateLimiter instance."""
    return RateLimiter(redis_client)


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self, limiter):
        """Requests under limit should be allowed."""
        result = await limiter.check("test:user1", limit=10, window_ms=60000)
        assert result.allowed is True
        assert result.current_count == 1
        assert result.remaining == 9
        assert result.retry_after_seconds == 0

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self, limiter):
        """Requests at limit should be blocked."""
        key = "test:user2"
        limit = 3

        # Use up the limit
        for i in range(limit):
            result = await limiter.check(key, limit=limit, window_ms=60000)
            assert result.allowed is True, f"Request {i+1} should be allowed"

        # Next request should be blocked
        result = await limiter.check(key, limit=limit, window_ms=60000)
        assert result.allowed is False
        assert result.current_count == limit
        assert result.remaining == 0
        assert result.retry_after_seconds > 0

    @pytest.mark.asyncio
    async def test_get_counter(self, limiter):
        """get_counter should return current count without incrementing."""
        key = "test:user3"

        # Initially zero
        count = await limiter.get_counter(key)
        assert count == 0

        # Make some requests
        await limiter.check(key, limit=10, window_ms=60000)
        await limiter.check(key, limit=10, window_ms=60000)

        # Should be 2, not incrementing
        count = await limiter.get_counter(key)
        assert count == 2

        count = await limiter.get_counter(key)
        assert count == 2  # Still 2

    @pytest.mark.asyncio
    async def test_reset_counter(self, limiter):
        """reset_counter should clear rate limit state."""
        key = "test:user4"

        # Make some requests
        await limiter.check(key, limit=10, window_ms=60000)
        await limiter.check(key, limit=10, window_ms=60000)

        count = await limiter.get_counter(key)
        assert count == 2

        # Reset
        result = await limiter.reset_counter(key)
        assert result is True

        count = await limiter.get_counter(key)
        assert count == 0

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, limiter):
        """Rate limiter should be accurate under concurrent load."""
        key = "test:concurrent"
        limit = 10

        # Send 20 concurrent requests with limit of 10
        async def make_request():
            return await limiter.check(key, limit=limit, window_ms=60000)

        results = await asyncio.gather(*[make_request() for _ in range(20)])

        allowed = sum(1 for r in results if r.allowed)
        blocked = sum(1 for r in results if not r.allowed)

        # Exactly 10 should be allowed, 10 blocked
        assert allowed == limit, f"Expected {limit} allowed, got {allowed}"
        assert blocked == 10, f"Expected 10 blocked, got {blocked}"

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, limiter):
        """Different keys should have independent limits."""
        # Fill up user1's limit
        for _ in range(5):
            await limiter.check("test:user5a", limit=5, window_ms=60000)

        result = await limiter.check("test:user5a", limit=5, window_ms=60000)
        assert result.allowed is False

        # user2 should still be allowed
        result = await limiter.check("test:user5b", limit=5, window_ms=60000)
        assert result.allowed is True


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_from_lua_result(self):
        """Should correctly parse Lua script output."""
        # Allowed result
        result = RateLimitResult.from_lua_result([1, 5, 95, 0])
        assert result.allowed is True
        assert result.current_count == 5
        assert result.remaining == 95
        assert result.retry_after_seconds == 0

        # Blocked result
        result = RateLimitResult.from_lua_result([0, 100, 0, 45])
        assert result.allowed is False
        assert result.current_count == 100
        assert result.remaining == 0
        assert result.retry_after_seconds == 45
