"""Management API endpoints for observability."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import redis.asyncio as redis

from ..redis_client import get_redis
from ..limiter import RateLimiter
from ..config import settings
from ..metrics import set_active_counters

management_router = APIRouter(prefix="/api", tags=["management"])


class NodeInfo(BaseModel):
    """Information about a rate limiter node."""

    id: str
    address: str
    state: str  # "Up" or "Down" (based on TTL)
    registered_at: datetime | None = None


class NodesResponse(BaseModel):
    """Response from /api/nodes."""

    nodes: list[NodeInfo]


class CounterInfo(BaseModel):
    """Information about a rate limit counter."""

    key: str
    count: int
    limit: int
    remaining: int


class CountersResponse(BaseModel):
    """Response from /api/counters."""

    counters: list[CounterInfo]


class LimitsResponse(BaseModel):
    """Response from /api/limits."""

    default_limit: int
    default_window_ms: int


class BlockedKeyInfo(BaseModel):
    """Information about a blocked key."""

    key: str
    current_count: int
    limit: int


class BlocksResponse(BaseModel):
    """Response from /api/blocks."""

    blocked: list[BlockedKeyInfo]


async def get_limiter(redis_client: redis.Redis = Depends(get_redis)) -> RateLimiter:
    """Dependency to get RateLimiter instance."""
    return RateLimiter(redis_client)


@management_router.get("/nodes", response_model=NodesResponse)
async def list_nodes(redis_client: redis.Redis = Depends(get_redis)) -> NodesResponse:
    """Return list of registered rate limiter nodes."""
    from ..node_registry import get_all_nodes

    nodes = await get_all_nodes(redis_client)
    return NodesResponse(nodes=nodes)


@management_router.get("/counters", response_model=CountersResponse)
async def get_counters(
    redis_client: redis.Redis = Depends(get_redis),
    limiter: RateLimiter = Depends(get_limiter),
) -> CountersResponse:
    """Return current rate limit counters from Redis."""
    counters = []

    # Scan for all ratelimit keys (excluding :seq keys)
    async for key in redis_client.scan_iter("ratelimit:*"):
        if key.endswith(":seq"):
            continue

        # Strip prefix for display
        display_key = key.replace("ratelimit:", "", 1)
        count = await limiter.get_counter(display_key)

        counters.append(
            CounterInfo(
                key=display_key,
                count=count,
                limit=settings.default_limit,
                remaining=max(0, settings.default_limit - count),
            )
        )

    # Update active counters metric
    set_active_counters(len(counters))

    return CountersResponse(counters=counters)


@management_router.get("/limits", response_model=LimitsResponse)
async def get_limits() -> LimitsResponse:
    """Return configured rate limits."""
    return LimitsResponse(
        default_limit=settings.default_limit,
        default_window_ms=settings.default_window_ms,
    )


@management_router.get("/blocks", response_model=BlocksResponse)
async def get_blocks(
    redis_client: redis.Redis = Depends(get_redis),
    limiter: RateLimiter = Depends(get_limiter),
) -> BlocksResponse:
    """Return keys that are currently at or over their limit."""
    blocked = []

    async for key in redis_client.scan_iter("ratelimit:*"):
        if key.endswith(":seq"):
            continue

        display_key = key.replace("ratelimit:", "", 1)
        count = await limiter.get_counter(display_key)

        if count >= settings.default_limit:
            blocked.append(
                BlockedKeyInfo(
                    key=display_key,
                    current_count=count,
                    limit=settings.default_limit,
                )
            )

    return BlocksResponse(blocked=blocked)
