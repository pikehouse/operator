"""
RateLimiterSubject - Rate Limiter implementation of the Subject Protocol.

This module provides RateLimiterSubject, the complete implementation of the
SubjectProtocol defined in operator-protocols for rate limiter services.

RateLimiterSubject:
- Implements SubjectProtocol with observe() method returning dict[str, Any]
- Uses injected HTTP clients for RateLimiter, Redis, and Prometheus APIs

Pattern mirrors TiKVSubject for consistency across subjects.
"""

from dataclasses import dataclass
from typing import Any

from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient


@dataclass
class RateLimiterSubject:
    """
    Rate Limiter implementation of the Subject Protocol.

    Provides observations about rate limiter cluster state through the
    management API, Redis, and Prometheus metrics.

    Attributes:
        ratelimiter: RateLimiterClient for management API queries
        redis: RedisClient for direct Redis state inspection
        prom: PrometheusClient for performance metrics

    Example:
        async with httpx.AsyncClient(base_url="http://ratelimiter:8000") as rl_http:
            async with httpx.AsyncClient(base_url="http://prometheus:9090") as prom_http:
                async with redis.Redis.from_url("redis://localhost:6379") as r:
                    subject = RateLimiterSubject(
                        ratelimiter=RateLimiterClient(http=rl_http),
                        redis=RedisClient(redis=r),
                        prom=PrometheusClient(http=prom_http),
                    )
                    observation = await subject.observe()
                    print(f"Nodes: {len(observation['nodes'])}")
    """

    ratelimiter: RateLimiterClient
    redis: RedisClient
    prom: PrometheusClient

    # -------------------------------------------------------------------------
    # SubjectProtocol.observe() - Generic observation interface
    # -------------------------------------------------------------------------

    async def observe(self) -> dict[str, Any]:
        """
        Gather current rate limiter cluster observations.

        Implements SubjectProtocol.observe() by collecting node states,
        counters, Redis connectivity, and per-node metrics into a unified
        observation dict.

        Returns:
            Dictionary with the following structure:
            {
                "nodes": [{"id": str, "address": str, "state": str}, ...],
                "counters": [{"key": str, "count": int, "limit": int, "remaining": int}, ...],
                "node_metrics": {
                    node_id: {
                        "latency_p99_ms": float
                    }, ...
                },
                "redis_connected": bool
            }

        Note:
            Node metrics are only collected for nodes in "Up" state.
            Failed metric collection is silently skipped to avoid
            blocking the entire observation.
        """
        # Get node states
        nodes = await self.ratelimiter.get_nodes()

        # Get active counters
        counters = await self.ratelimiter.get_counters()

        # Check Redis connectivity
        redis_connected = await self.redis.ping()

        # Get per-node metrics for Up nodes
        node_metrics: dict[str, dict[str, Any]] = {}
        for node in nodes:
            if node.state == "Up":
                try:
                    latency_p99 = await self.prom.get_node_latency_p99(node.id)
                    node_metrics[node.id] = {
                        "latency_p99_ms": latency_p99,
                    }
                except Exception:
                    # Skip failed metrics - don't block observation
                    pass

        return {
            "nodes": [
                {"id": n.id, "address": n.address, "state": n.state} for n in nodes
            ],
            "counters": [
                {
                    "key": c.key,
                    "count": c.count,
                    "limit": c.limit,
                    "remaining": c.remaining,
                }
                for c in counters
            ],
            "node_metrics": node_metrics,
            "redis_connected": redis_connected,
        }
