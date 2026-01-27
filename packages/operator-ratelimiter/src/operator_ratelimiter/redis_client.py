"""Redis client for direct state inspection."""

from dataclasses import dataclass

import redis.asyncio as redis


@dataclass
class RedisClient:
    """
    Redis client for inspecting rate limiter state.

    Provides direct access to Redis for state inspection and diagnostics.

    Attributes:
        redis: Pre-configured redis.asyncio.Redis client.

    Example:
        import redis.asyncio as redis

        async with redis.Redis.from_url("redis://localhost:6379") as r:
            client = RedisClient(redis=r)
            if await client.ping():
                counter_value = await client.get_counter_value("user:123")
    """

    redis: redis.Redis

    async def ping(self) -> bool:
        """
        Check Redis connectivity.

        Returns:
            True if Redis is reachable, False otherwise.

        Note:
            Catches ConnectionError and TimeoutError, returning False.
            Does not raise exceptions - safe for health checks.
        """
        try:
            await self.redis.ping()
            return True
        except (ConnectionError, TimeoutError):
            return False

    async def get_counter_value(self, key: str) -> int:
        """
        Get raw counter value from Redis sorted set.

        Args:
            key: The counter key (without 'ratelimit:' prefix).

        Returns:
            Number of entries in the sorted set (current count).

        Raises:
            redis.RedisError: On Redis errors.

        Note:
            Returns raw ZCARD count. Does not clean expired entries.
            For accurate counts, use RateLimiterClient.get_counters() instead.
        """
        prefixed_key = f"ratelimit:{key}"
        count = await self.redis.zcard(prefixed_key)
        return count

    async def get_all_counter_keys(self) -> list[str]:
        """
        Scan for all rate limit counter keys.

        Returns:
            List of counter keys (without 'ratelimit:' prefix, excluding :seq keys).

        Raises:
            redis.RedisError: On Redis errors.

        Note:
            Uses SCAN to avoid blocking Redis on large keysets.
            Filters out :seq sequence counter keys.
        """
        keys = []
        async for key in self.redis.scan_iter("ratelimit:*"):
            # Skip sequence counter keys
            if key.endswith(":seq"):
                continue

            # Strip prefix for display
            display_key = key.replace("ratelimit:", "", 1)
            keys.append(display_key)

        return keys
