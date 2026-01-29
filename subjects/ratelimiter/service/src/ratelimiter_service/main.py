"""FastAPI application for rate limiter service."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .redis_client import init_redis_pool, close_redis_pool, get_redis
from .api import rate_limit_router, management_router
from .node_registry import register_node, unregister_node, heartbeat_loop
from .metrics import set_node_up


# Background task handle
_heartbeat_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    global _heartbeat_task

    # Startup
    await init_redis_pool()

    # Register node and start heartbeat
    redis_client = await get_redis()
    await register_node(redis_client)
    _heartbeat_task = asyncio.create_task(heartbeat_loop(redis_client))
    set_node_up(True)

    yield

    # Shutdown
    set_node_up(False)

    # Stop heartbeat
    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass

    # Unregister node
    try:
        redis_client = await get_redis()
        await unregister_node(redis_client)
    except Exception:
        pass  # Best effort cleanup

    await close_redis_pool()


app = FastAPI(
    title="Rate Limiter Service",
    description="Distributed rate limiter with Redis backend for operator demo",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(rate_limit_router)
app.include_router(management_router)

# Setup Prometheus metrics
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "node_id": settings.node_id}


# Entry point for uvicorn
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ratelimiter_service.main:app",
        host="0.0.0.0",
        port=settings.node_port,
        reload=True,
    )
