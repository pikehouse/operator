"""
Factory function for creating RateLimiter subject and checker instances.

This module provides a factory function for CLI integration, allowing
the operator-core CLI to create RateLimiter-specific instances without
direct imports from operator-ratelimiter.
"""

import httpx
import redis.asyncio as redis

from operator_ratelimiter.invariants import RateLimiterInvariantChecker
from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient
from operator_ratelimiter.subject import RateLimiterSubject


def create_ratelimiter_subject_and_checker(
    ratelimiter_url: str,
    redis_url: str,
    prometheus_url: str,
    rl_http: httpx.AsyncClient | None = None,
    redis_client: redis.Redis | None = None,
    prom_http: httpx.AsyncClient | None = None,
) -> tuple[RateLimiterSubject, RateLimiterInvariantChecker]:
    """
    Create a RateLimiter subject and checker pair.

    Factory function for creating RateLimiterSubject and RateLimiterInvariantChecker
    instances with pre-configured HTTP and Redis clients. Used by CLI to create
    subject/checker pairs without direct imports.

    Args:
        ratelimiter_url: Rate limiter management API endpoint URL (e.g., "http://ratelimiter:8000")
        redis_url: Redis connection URL (e.g., "redis://localhost:6379")
        prometheus_url: Prometheus API URL (e.g., "http://prometheus:9090")
        rl_http: Optional pre-configured httpx client for rate limiter API.
            If None, a new client is created with 10s timeout.
        redis_client: Optional pre-configured redis.asyncio.Redis client.
            If None, a new client is created from redis_url with decode_responses=True.
        prom_http: Optional pre-configured httpx client for Prometheus.
            If None, a new client is created with 10s timeout.

    Returns:
        Tuple of (RateLimiterSubject, RateLimiterInvariantChecker) instances ready for use.

    Example:
        subject, checker = create_ratelimiter_subject_and_checker(
            ratelimiter_url="http://ratelimiter:8000",
            redis_url="redis://localhost:6379",
            prometheus_url="http://prometheus:9090",
        )

        # Use with generic protocols
        observation = await subject.observe()
        violations = checker.check(observation)
    """
    if rl_http is None:
        rl_http = httpx.AsyncClient(base_url=ratelimiter_url, timeout=10.0)
    if redis_client is None:
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
    if prom_http is None:
        prom_http = httpx.AsyncClient(base_url=prometheus_url, timeout=10.0)

    subject = RateLimiterSubject(
        ratelimiter=RateLimiterClient(http=rl_http),
        redis=RedisClient(redis=redis_client),
        prom=PrometheusClient(http=prom_http),
    )
    checker = RateLimiterInvariantChecker()

    return subject, checker
