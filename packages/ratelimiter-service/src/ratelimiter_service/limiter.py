"""
Sliding window rate limiter using Redis sorted sets and Lua scripts.

Uses a sorted set per key with timestamp scores. On each request:
1. ZREMRANGEBYSCORE to prune entries older than window
2. ZCARD to count requests in window
3. ZADD to record new request (if under limit)

Lua script ensures atomicity (no race between count and increment).
The :seq counter ensures unique members when multiple requests share a timestamp.
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis

# Lua script for atomic sliding window rate limiting
# KEYS[1] = rate limit key (e.g., "ratelimit:user:123")
# ARGV[1] = current timestamp (milliseconds)
# ARGV[2] = window size (milliseconds)
# ARGV[3] = max requests
# Returns: [allowed (0/1), current_count, remaining, retry_after_seconds]
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])

-- Clean expired entries (before window start)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

-- Get current count
local count = redis.call('ZCARD', key)

-- Check if over limit
if count >= max_requests then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if #oldest > 0 then
        retry_after = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
    end
    return {0, count, 0, retry_after}  -- blocked
end

-- Add request with unique member (timestamp:sequence)
local member = now .. ':' .. redis.call('INCR', key .. ':seq')
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)

return {1, count + 1, max_requests - count - 1, 0}  -- allowed
"""


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    remaining: int
    retry_after_seconds: int

    @classmethod
    def from_lua_result(cls, result: list) -> "RateLimitResult":
        """Create from Lua script return value."""
        return cls(
            allowed=bool(result[0]),
            current_count=int(result[1]),
            remaining=int(result[2]),
            retry_after_seconds=int(result[3]),
        )


class RateLimiter:
    """Sliding window rate limiter using Redis sorted sets."""

    def __init__(self, redis_client: "redis.Redis"):
        self._redis = redis_client
        self._script = redis_client.register_script(SLIDING_WINDOW_SCRIPT)

    async def check(
        self,
        key: str,
        limit: int | None = None,
        window_ms: int | None = None,
    ) -> RateLimitResult:
        """
        Check if request is allowed under rate limit.

        Args:
            key: Rate limit key (e.g., "user:123")
            limit: Max requests in window (uses config default if None)
            window_ms: Window size in milliseconds (uses config default if None)

        Returns:
            RateLimitResult with allowed status and metadata
        """
        from .config import settings

        limit = limit if limit is not None else settings.default_limit
        window_ms = window_ms if window_ms is not None else settings.default_window_ms

        now_ms = int(time.time() * 1000)
        prefixed_key = f"ratelimit:{key}"

        result = await self._script(
            keys=[prefixed_key],
            args=[now_ms, window_ms, limit],
        )
        return RateLimitResult.from_lua_result(result)

    async def get_counter(self, key: str, window_ms: int | None = None) -> int:
        """Get current count for a key without incrementing."""
        from .config import settings

        window_ms = window_ms if window_ms is not None else settings.default_window_ms
        now_ms = int(time.time() * 1000)
        window_start = now_ms - window_ms
        prefixed_key = f"ratelimit:{key}"

        # Remove expired and count
        await self._redis.zremrangebyscore(prefixed_key, "-inf", window_start)
        count = await self._redis.zcard(prefixed_key)
        return count

    async def reset_counter(self, key: str) -> bool:
        """Reset rate limit counter for a key."""
        prefixed_key = f"ratelimit:{key}"
        seq_key = f"{prefixed_key}:seq"
        deleted = await self._redis.delete(prefixed_key, seq_key)
        return deleted > 0

    async def update_limit(self, key: str, limit: int, window_ms: int | None = None) -> bool:
        """
        Update rate limit for a specific key.

        Stores per-key limit override in Redis. If window_ms is not provided,
        uses the default window size.

        Args:
            key: Rate limit key (e.g., "user:123")
            limit: New max requests in window
            window_ms: Window size in milliseconds (optional)

        Returns:
            True (operation always succeeds)
        """
        from .config import settings

        window_ms = window_ms if window_ms is not None else settings.default_window_ms
        limit_key = f"ratelimit:limit:{key}"

        # Store as hash with limit and window
        await self._redis.hset(limit_key, mapping={"limit": limit, "window_ms": window_ms})
        return True

    async def get_limit(self, key: str) -> tuple[int, int] | None:
        """
        Get stored limit for a key.

        Args:
            key: Rate limit key

        Returns:
            Tuple of (limit, window_ms) if custom limit exists, None otherwise
        """
        limit_key = f"ratelimit:limit:{key}"
        data = await self._redis.hgetall(limit_key)

        if not data:
            return None

        return (int(data["limit"]), int(data["window_ms"]))
