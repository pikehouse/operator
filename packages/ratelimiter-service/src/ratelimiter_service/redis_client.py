"""Async Redis connection management.

Provides connection pool management for the FastAPI application lifecycle.
Use init_redis_pool() on startup and close_redis_pool() on shutdown.
"""

import redis.asyncio as redis

from .config import settings

_redis_pool: redis.ConnectionPool | None = None


async def init_redis_pool() -> None:
    """Initialize Redis connection pool. Call on app startup."""
    global _redis_pool
    _redis_pool = redis.ConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
    )


async def close_redis_pool() -> None:
    """Close Redis connection pool. Call on app shutdown."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


async def get_redis() -> redis.Redis:
    """Get Redis client from pool. Use as FastAPI dependency.

    Returns:
        redis.Redis: Async Redis client connected to the pool.

    Raises:
        RuntimeError: If pool not initialized (app not started).
    """
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialized")
    return redis.Redis(connection_pool=_redis_pool)
