# Phase 17: Rate Limiter Service Foundation - Research

**Researched:** 2026-01-26
**Domain:** Distributed rate limiting with Redis, HTTP management APIs, Prometheus metrics
**Confidence:** HIGH

## Summary

This phase builds a custom distributed rate limiter service that will be monitored by the operator-ratelimiter package (Phase 19). The rate limiter is a demo service to prove the operator abstraction generalizes beyond TiKV - not a production-ready rate limiter product.

The standard approach for distributed rate limiting uses Redis sorted sets with atomic Lua scripts to implement sliding window counters. Each node is stateless, storing all rate limit state in Redis. The service exposes an HTTP management API for observability and Prometheus metrics for monitoring.

The implementation follows existing patterns in the codebase: a new `packages/ratelimiter-service` package following the operator-tikv structure, using FastAPI for HTTP endpoints, redis-py async client for Redis communication, and prometheus-fastapi-instrumentator for metrics.

**Primary recommendation:** Build a FastAPI service with sliding window counter via Redis Lua scripts, HTTP management API at `/api/*`, and Prometheus metrics at `/metrics`. Keep it simple - this is a demo service.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | latest | HTTP framework | Already used in ecosystem, async native, automatic OpenAPI |
| redis-py | 7.1.x | Redis async client | aioredis merged in, official Redis client, Lua script support |
| prometheus-fastapi-instrumentator | latest | Metrics | Auto-instruments FastAPI, easy custom metrics |
| uvicorn | latest | ASGI server | Standard FastAPI deployment |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.x | Request/response validation | Already in operator-core deps |
| httpx | 0.27+ | HTTP client (for testing) | Already in operator-core deps |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FastAPI | aiohttp | FastAPI has better auto-docs and validation |
| redis-py | aioredis | aioredis merged into redis-py 4.2+, use redis-py |
| prometheus-fastapi-instrumentator | aioprometheus | instrumentator is more popular, better FastAPI integration |

**Installation:**
```bash
# In packages/ratelimiter-service/pyproject.toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "redis>=5.0.0",
    "prometheus-fastapi-instrumentator>=7.0.0",
    "pydantic>=2.0.0",
]
```

## Architecture Patterns

### Recommended Project Structure
```
packages/ratelimiter-service/
├── pyproject.toml
├── src/
│   └── ratelimiter_service/
│       ├── __init__.py
│       ├── main.py              # FastAPI app, entry point
│       ├── config.py            # Environment config (redis URL, limits)
│       ├── limiter.py           # Rate limiter logic with Lua scripts
│       ├── api/
│       │   ├── __init__.py
│       │   ├── rate_limit.py    # POST /check - main rate limit endpoint
│       │   └── management.py    # GET /api/nodes, /api/counters, etc.
│       ├── redis_client.py      # Async Redis connection management
│       ├── metrics.py           # Custom Prometheus metrics
│       └── lua/
│           └── sliding_window.lua  # Lua script (embedded as string)
└── tests/
    ├── __init__.py
    ├── test_limiter.py
    └── test_api.py
```

### Pattern 1: Sliding Window Counter with Redis Sorted Sets
**What:** Use Redis sorted sets (ZSET) to track request timestamps, with Lua script for atomic operations.
**When to use:** When you need exact rate limiting under concurrent load without race conditions.
**Example:**
```lua
-- Sliding window rate limiter Lua script
-- KEYS[1] = rate limit key (e.g., "ratelimit:user:123")
-- ARGV[1] = current timestamp (milliseconds)
-- ARGV[2] = window size (milliseconds)
-- ARGV[3] = max requests

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local window_start = now - window

-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Count current requests in window
local count = redis.call('ZCARD', key)

if count >= max_requests then
    return {0, count, max_requests - count}  -- blocked, current count, remaining
end

-- Add current request with unique member (timestamp + random)
redis.call('ZADD', key, now, now .. '-' .. math.random(1000000))
redis.call('EXPIRE', key, math.ceil(window / 1000))

return {1, count + 1, max_requests - count - 1}  -- allowed, new count, remaining
```

### Pattern 2: Stateless Nodes with Shared Redis State
**What:** Each rate limiter node is stateless; all state lives in Redis.
**When to use:** Always for distributed rate limiting - enables horizontal scaling.
**Example:**
```python
# Node doesn't store state - Redis is the source of truth
from dataclasses import dataclass
import redis.asyncio as redis

@dataclass
class RateLimiterNode:
    node_id: str
    redis_client: redis.Redis

    async def check_rate_limit(self, key: str, limit: int, window_ms: int) -> bool:
        """Check rate limit - all state in Redis."""
        result = await self.redis_client.evalsha(
            self._script_sha,
            1,  # num keys
            key,
            int(time.time() * 1000),  # current time ms
            window_ms,
            limit,
        )
        return result[0] == 1  # 1 = allowed, 0 = blocked
```

### Pattern 3: HTTP Management API for Observability
**What:** Expose internal state via HTTP for the operator to observe.
**When to use:** Required for operator integration - operator-ratelimiter will poll these endpoints.
**Example:**
```python
from fastapi import FastAPI, APIRouter

management_router = APIRouter(prefix="/api")

@management_router.get("/nodes")
async def list_nodes():
    """Return list of known nodes (self + discovered via Redis)."""
    return {"nodes": [{"id": node_id, "address": f"{host}:{port}", "state": "Up"}]}

@management_router.get("/counters")
async def get_counters():
    """Return current rate limit counters from Redis."""
    # Scan Redis for ratelimit:* keys and return counts
    return {"counters": {"user:123": 45, "user:456": 12}}

@management_router.get("/limits")
async def get_limits():
    """Return configured rate limits."""
    return {"default_limit": 100, "window_ms": 60000}

@management_router.get("/blocks")
async def get_blocks():
    """Return currently blocked keys."""
    return {"blocked": ["user:789"]}
```

### Pattern 4: Node Discovery via Redis
**What:** Nodes register themselves in Redis with TTL for health tracking.
**When to use:** When running multiple nodes that need to know about each other.
**Example:**
```python
async def register_node(redis_client, node_id: str, address: str, ttl: int = 30):
    """Register node in Redis with TTL for heartbeat."""
    key = f"ratelimiter:nodes:{node_id}"
    await redis_client.hset(key, mapping={
        "address": address,
        "registered_at": datetime.now().isoformat(),
    })
    await redis_client.expire(key, ttl)

async def get_all_nodes(redis_client) -> list[dict]:
    """Discover all registered nodes."""
    nodes = []
    async for key in redis_client.scan_iter("ratelimiter:nodes:*"):
        data = await redis_client.hgetall(key)
        node_id = key.decode().split(":")[-1]
        nodes.append({"id": node_id, "address": data[b"address"].decode()})
    return nodes
```

### Anti-Patterns to Avoid
- **Read-then-write without atomicity:** Never do GET count, check limit, then INCR in separate operations - race conditions will allow overruns
- **Storing state in node memory:** State must live in Redis for distributed coordination
- **Using fixed window counters:** They have burst problems at window boundaries; use sliding window
- **Synchronous Redis calls:** Use async client for all Redis operations in FastAPI
- **Hardcoded time:** Pass time as argument to Lua scripts to handle clock drift

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limit algorithm | Custom counter logic | Sliding window with Lua | Race conditions, edge cases at boundaries |
| Prometheus metrics | Manual metric collection | prometheus-fastapi-instrumentator | Auto-handles multiprocess, ASGI integration |
| Redis connection pool | Manual connection management | redis.ConnectionPool | Handles reconnection, pooling, timeouts |
| Script caching | Manual EVALSHA handling | redis.register_script() | Auto-handles NOSCRIPT errors, caching |
| JSON serialization | Manual dict building | Pydantic models | Validation, auto-documentation |

**Key insight:** The Lua script atomicity is critical. Without it, concurrent requests can bypass rate limits due to read-modify-write race conditions. Redis's single-threaded execution guarantees the Lua script runs atomically.

## Common Pitfalls

### Pitfall 1: Race Conditions in Rate Limiting
**What goes wrong:** Multiple requests read the same counter value, both pass the check, both increment - allows more requests than the limit.
**Why it happens:** Using separate read and write operations instead of atomic Lua script.
**How to avoid:** Always use Lua scripts for rate limit checks. The script reads count, checks limit, and increments in one atomic operation.
**Warning signs:** Rate limit consistently allows more requests than configured under high concurrency.

### Pitfall 2: Clock Drift Between Nodes
**What goes wrong:** Nodes have different system times, causing inconsistent window calculations.
**Why it happens:** Each node uses its own system clock for timestamps.
**How to avoid:** Pass timestamp as argument to Lua script (from client), or use Redis TIME command inside the script.
**Warning signs:** Requests allowed/denied inconsistently when load balancer routes to different nodes.

### Pitfall 3: Memory Leak from Expired Keys
**What goes wrong:** Redis memory grows unbounded over time.
**Why it happens:** Sorted set members not cleaned up, or EXPIRE not set correctly.
**How to avoid:** Always ZREMRANGEBYSCORE before ZADD to clean old entries, and set EXPIRE on the key.
**Warning signs:** Redis memory usage grows continuously even with constant traffic.

### Pitfall 4: CROSSSLOT Errors in Redis Cluster
**What goes wrong:** Lua script fails with "CROSSSLOT Keys in request don't hash to the same slot" error.
**Why it happens:** Script accesses keys that hash to different Redis cluster slots.
**How to avoid:** Use hash tags in keys: `{user:123}:ratelimit` ensures same slot. For this demo with single Redis, not an issue.
**Warning signs:** Script works in dev (single Redis) but fails in cluster mode.

### Pitfall 5: Blocking Redis Operations
**What goes wrong:** FastAPI becomes unresponsive under load.
**Why it happens:** Using synchronous Redis client instead of async.
**How to avoid:** Always use `redis.asyncio` client with `await` for all operations.
**Warning signs:** High latency, low throughput despite Redis being fast.

### Pitfall 6: Lost Metrics in Multiprocess Deployment
**What goes wrong:** Prometheus metrics are incorrect or missing when running multiple workers.
**Why it happens:** Each worker process has its own metrics registry.
**How to avoid:** prometheus-fastapi-instrumentator handles this. For custom metrics, use `multiprocess.MultiProcessCollector`.
**Warning signs:** Metrics show lower counts than expected, or vary wildly between scrapes.

## Code Examples

Verified patterns from research:

### Sliding Window Rate Limiter Lua Script
```lua
-- Source: Verified pattern from multiple sources
-- Keys: KEYS[1] = rate limit key
-- Args: ARGV[1] = now_ms, ARGV[2] = window_ms, ARGV[3] = max_requests

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

-- Add request with unique member
local member = now .. ':' .. redis.call('INCR', key .. ':seq')
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)

return {1, count + 1, max_requests - count - 1, 0}  -- allowed
```

### Async Redis Script Registration
```python
# Source: redis-py documentation
import redis.asyncio as redis

SLIDING_WINDOW_SCRIPT = """
-- Lua script content here
"""

class RateLimiter:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._script = self.redis.register_script(SLIDING_WINDOW_SCRIPT)

    async def check(self, key: str, limit: int, window_ms: int) -> tuple[bool, int, int]:
        """Check rate limit. Returns (allowed, current_count, remaining)."""
        now_ms = int(time.time() * 1000)
        result = await self._script(
            keys=[key],
            args=[now_ms, window_ms, limit],
        )
        return bool(result[0]), result[1], result[2]
```

### FastAPI Application Setup
```python
# Source: prometheus-fastapi-instrumentator docs
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram

app = FastAPI(title="Rate Limiter Service")

# Custom metrics for rate limiter
REQUESTS_CHECKED = Counter(
    "ratelimiter_requests_checked_total",
    "Total rate limit checks",
    ["result"],  # "allowed" or "blocked"
)

CHECK_LATENCY = Histogram(
    "ratelimiter_check_duration_seconds",
    "Rate limit check latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1],
)

# Auto-instrument FastAPI
Instrumentator().instrument(app).expose(app)
```

### Management API Response Models
```python
# Source: Pydantic patterns from existing codebase
from pydantic import BaseModel
from datetime import datetime

class NodeInfo(BaseModel):
    id: str
    address: str
    state: str  # "Up", "Down"
    registered_at: datetime

class NodesResponse(BaseModel):
    nodes: list[NodeInfo]

class CounterInfo(BaseModel):
    key: str
    count: int
    limit: int
    remaining: int
    window_ms: int

class CountersResponse(BaseModel):
    counters: list[CounterInfo]

class LimitsConfig(BaseModel):
    default_limit: int
    default_window_ms: int
    per_key_limits: dict[str, int]

class BlockedKey(BaseModel):
    key: str
    blocked_until: datetime
    reason: str

class BlocksResponse(BaseModel):
    blocked: list[BlockedKey]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| aioredis separate package | redis-py includes async (7.x) | 2023 (v4.2+) | Use `redis.asyncio` import |
| Fixed window counters | Sliding window counters | N/A | Better accuracy, no burst at boundaries |
| Manual metric setup | prometheus-fastapi-instrumentator | N/A | Auto-handles multiprocess, ASGI |
| Synchronous Redis | Async Redis required | N/A | FastAPI is async-native |

**Deprecated/outdated:**
- aioredis: Merged into redis-py, use `import redis.asyncio as redis`
- Separate Prometheus setup: Use instrumentator for FastAPI

## Open Questions

Things that couldn't be fully resolved:

1. **Node registration approach**
   - What we know: Nodes can register in Redis with TTL for heartbeat
   - What's unclear: Exact TTL value for node registration (10s? 30s?)
   - Recommendation: Use 30s TTL, heartbeat every 10s. Configurable via environment variable.

2. **Rate limit key format**
   - What we know: Keys should include identifier (user, IP, API key)
   - What's unclear: Exact key format for the demo
   - Recommendation: Use `ratelimit:{identifier}` format. For demo, use simple string keys like `user:1`, `user:2`.

3. **Default rate limits for demo**
   - What we know: Need configurable limits
   - What's unclear: What values demonstrate the system well
   - Recommendation: Default 100 requests per 60 seconds. Low enough to trigger limits in demo, high enough to show normal operation.

## Sources

### Primary (HIGH confidence)
- [redis-py 7.1.0 Lua scripting docs](https://redis.readthedocs.io/en/stable/lua_scripting.html) - Script registration, EVALSHA handling
- [redis-py asyncio examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - Async connection patterns
- [prometheus-fastapi-instrumentator GitHub](https://github.com/trallnag/prometheus-fastapi-instrumentator) - FastAPI metrics integration
- [Redis.io rate limiting tutorial](https://redis.io/learn/develop/dotnet/aspnetcore/rate-limiting/sliding-window) - Sliding window algorithm

### Secondary (MEDIUM confidence)
- [Grab Engineering: Sliding window rate limits](https://engineering.grab.com/frequency-capping) - Production patterns at scale
- [RDiachenko: Sliding window algorithm](https://rdiachenko.com/posts/arch/rate-limiting/sliding-window-algorithm/) - Algorithm details and formula
- [Halodoc: Redis and Lua rate limiter](https://blogs.halodoc.io/taming-the-traffic-redis-and-lua-powered-sliding-window-rate-limiter-in-action/) - Implementation patterns
- [Games24x7: Distributed rate limiting](https://medium.com/@Games24x7Tech/distributed-rate-limiting-using-redis-and-lua-8e668d525ab8) - Race condition handling

### Tertiary (LOW confidence)
- [GitHub Gist: Sliding window Lua script](https://gist.github.com/atomaras/925a13f07c24df7f15dcc4fb7bc89c81) - Example Lua script with remaining tokens
- [PyPI: redis-rate-limiters](https://pypi.org/project/redis-rate-limiters/) - Alternative library (considered but not using)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - redis-py and FastAPI are well-documented, widely used
- Architecture: HIGH - Sliding window with Lua is the standard pattern
- Pitfalls: HIGH - Race conditions and atomicity are well-documented problems

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - stable domain)
