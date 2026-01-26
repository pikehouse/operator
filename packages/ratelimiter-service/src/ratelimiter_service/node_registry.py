"""Node registration and discovery via Redis."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis

from .config import settings


async def register_node(redis_client: "redis.Redis") -> None:
    """Register this node in Redis with TTL for heartbeat."""
    key = f"ratelimiter:nodes:{settings.node_id}"
    await redis_client.hset(
        key,
        mapping={
            "address": f"{settings.node_host}:{settings.node_port}",
            "registered_at": datetime.now().isoformat(),
        },
    )
    await redis_client.expire(key, settings.node_ttl_seconds)


async def unregister_node(redis_client: "redis.Redis") -> None:
    """Unregister this node from Redis."""
    key = f"ratelimiter:nodes:{settings.node_id}"
    await redis_client.delete(key)


async def heartbeat_loop(redis_client: "redis.Redis") -> None:
    """Background task to maintain node registration."""
    while True:
        try:
            await register_node(redis_client)
            await asyncio.sleep(settings.node_heartbeat_seconds)
        except asyncio.CancelledError:
            break
        except Exception:
            # Log error but continue heartbeat
            await asyncio.sleep(settings.node_heartbeat_seconds)


async def get_all_nodes(redis_client: "redis.Redis") -> list:
    """Discover all registered nodes from Redis."""
    from .api.management import NodeInfo

    nodes = []
    async for key in redis_client.scan_iter("ratelimiter:nodes:*"):
        data = await redis_client.hgetall(key)
        if not data:
            continue

        node_id = key.split(":")[-1]
        registered_at = None
        if "registered_at" in data:
            try:
                registered_at = datetime.fromisoformat(data["registered_at"])
            except (ValueError, TypeError):
                pass

        nodes.append(
            NodeInfo(
                id=node_id,
                address=data.get("address", "unknown"),
                state="Up",  # If key exists with TTL, node is up
                registered_at=registered_at,
            )
        )

    return nodes
