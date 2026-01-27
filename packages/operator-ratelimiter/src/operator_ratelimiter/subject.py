"""
RateLimiterSubject - Rate Limiter implementation of the Subject Protocol.

This module provides RateLimiterSubject, the complete implementation of the
SubjectProtocol defined in operator-protocols for rate limiter services.

RateLimiterSubject:
- Implements SubjectProtocol with observe() method returning dict[str, Any]
- Implements action methods: reset_counter, update_limit
- Provides get_action_definitions() for ActionRegistry integration
- Uses injected HTTP clients for RateLimiter, Redis, and Prometheus APIs

Pattern mirrors TiKVSubject for consistency across subjects.
"""

from dataclasses import dataclass
from typing import Any

from operator_core.actions.registry import ActionDefinition, ParamDef

from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient


@dataclass
class RateLimiterSubject:
    """
    Rate Limiter implementation of the Subject Protocol.

    Provides observations about rate limiter cluster state through the
    management API, Redis, and Prometheus metrics. Implements action
    methods for counter reset and limit updates.

    Attributes:
        ratelimiter: RateLimiterClient for management API queries and actions
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

    def get_action_definitions(self) -> list[ActionDefinition]:
        """
        Return definitions of all actions this subject supports.

        Used by ActionRegistry to discover available actions at runtime.
        Provides parameter schemas, risk levels, and descriptions for
        each action.

        Returns:
            List of ActionDefinition objects for all implemented actions.
        """
        return [
            ActionDefinition(
                name="reset_counter",
                description="Reset a rate limit counter to zero",
                parameters={
                    "key": ParamDef(
                        type="str",
                        description="The counter key to reset",
                        required=True,
                    ),
                },
                risk_level="medium",
                requires_approval=False,
            ),
            ActionDefinition(
                name="update_limit",
                description="Update the rate limit for a key",
                parameters={
                    "key": ParamDef(
                        type="str",
                        description="The counter key to update",
                        required=True,
                    ),
                    "new_limit": ParamDef(
                        type="int",
                        description="New rate limit value",
                        required=True,
                    ),
                },
                risk_level="high",
                requires_approval=False,
            ),
        ]

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

    # -------------------------------------------------------------------------
    # Actions - Operations that modify system state
    # -------------------------------------------------------------------------

    async def reset_counter(self, key: str) -> None:
        """
        Reset a rate limit counter to zero.

        Fire-and-forget: returns when management API accepts the request.
        Does not wait for actual counter reset confirmation.

        Args:
            key: The counter key to reset.

        Raises:
            httpx.HTTPStatusError: On API errors (4xx, 5xx).
        """
        await self.ratelimiter.reset_counter(key)

    async def update_limit(self, key: str, new_limit: int) -> None:
        """
        Update the rate limit for a key.

        Fire-and-forget: returns when management API accepts the request.
        Does not wait for actual limit update confirmation.

        Args:
            key: The counter key to update.
            new_limit: New rate limit value.

        Raises:
            httpx.HTTPStatusError: On API errors (4xx, 5xx).

        Note:
            Window size is not specified, so service default is used.
        """
        await self.ratelimiter.update_limit(key, new_limit)
