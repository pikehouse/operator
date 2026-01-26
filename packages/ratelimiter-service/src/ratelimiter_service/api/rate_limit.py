"""Rate limit check endpoint."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
import redis.asyncio as redis

from ..redis_client import get_redis
from ..limiter import RateLimiter
from ..config import settings
from ..metrics import record_rate_limit_check, CHECK_LATENCY

rate_limit_router = APIRouter(tags=["rate-limit"])


class RateLimitRequest(BaseModel):
    """Request body for rate limit check."""

    key: str
    limit: int | None = None
    window_ms: int | None = None


class RateLimitResponse(BaseModel):
    """Response from rate limit check."""

    allowed: bool
    current_count: int
    remaining: int
    retry_after_seconds: int


async def get_limiter(redis_client: redis.Redis = Depends(get_redis)) -> RateLimiter:
    """Dependency to get RateLimiter instance."""
    return RateLimiter(redis_client)


@CHECK_LATENCY.time()
@rate_limit_router.post("/check", response_model=RateLimitResponse)
async def check_rate_limit(
    request: RateLimitRequest,
    response: Response,
    limiter: RateLimiter = Depends(get_limiter),
) -> RateLimitResponse:
    """
    Check if a request is allowed under rate limits.

    Returns rate limit decision with standard headers:
    - X-RateLimit-Limit: Max requests allowed
    - X-RateLimit-Remaining: Requests remaining in window
    - X-RateLimit-Reset: Seconds until limit resets (if blocked)
    """
    result = await limiter.check(
        key=request.key,
        limit=request.limit,
        window_ms=request.window_ms,
    )

    # Record metric
    record_rate_limit_check("allowed" if result.allowed else "blocked")

    # Set rate limit headers
    limit = request.limit if request.limit is not None else settings.default_limit
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    if not result.allowed:
        response.headers["X-RateLimit-Reset"] = str(result.retry_after_seconds)
        response.status_code = 429

    return RateLimitResponse(
        allowed=result.allowed,
        current_count=result.current_count,
        remaining=result.remaining,
        retry_after_seconds=result.retry_after_seconds,
    )
