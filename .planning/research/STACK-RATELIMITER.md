# Stack Research: Rate Limiter Subject

**Project:** Distributed Rate Limiter (Second Subject)
**Researched:** 2026-01-26
**Research Type:** Subsequent Milestone - Stack Additions Only

## Executive Summary

The rate limiter subject follows the existing operator-tikv pattern: a separate package (`operator-ratelimiter`) that implements the Subject Protocol from operator-core. The rate limiter service itself is a simple Python async service using the existing stack (httpx, Pydantic) plus redis-py for Redis communication. Docker Compose orchestrates multiple rate limiter instances sharing Redis state.

**Key decisions:**
- **Same language (Python)** - Matches operator-core, enables code sharing
- **redis-py with async** - Official library, absorbed aioredis, current standard
- **Sliding window counter** - Simple algorithm, good enough for demo
- **No new frameworks** - Keep it simple, reuse existing patterns

---

## Recommended Stack Additions

### Redis Client: redis-py 7.1.0

| Component | Package | Version | Purpose |
|-----------|---------|---------|---------|
| Redis async client | `redis` | `>=7.1.0` | Async Redis operations via `redis.asyncio` |
| Performance boost | `hiredis` | `>=3.1.0` | C-based response parser (optional, zero code changes) |

**Why redis-py:**
- Official Redis Python client from Redis Inc.
- Absorbed aioredis in v4.2.0 (aioredis last release Dec 2021, no longer maintained)
- Native asyncio support via `import redis.asyncio as redis`
- Built-in connection pooling
- Supports Redis 7.2, 7.4, 8.0, 8.2

**Verified:** [PyPI redis page](https://pypi.org/project/redis/) - v7.1.0 released Nov 19, 2025, requires Python 3.10+

**Usage pattern:**
```python
import redis.asyncio as redis

# Create client with connection pool
client = redis.Redis(host="redis", port=6379, decode_responses=True)

# Operations
await client.incr("key")
await client.expire("key", 60)

# Cleanup
await client.aclose()
```

### Redis Server: Docker Image

| Component | Image | Tag | Purpose |
|-----------|-------|-----|---------|
| Redis server | `redis` | `7.4-alpine` | Distributed state storage |

**Why redis:7.4-alpine:**
- Alpine variant keeps image small (~30MB)
- Version lock (7.4) prevents breaking changes from Redis 8.x
- Redis 7.4 is stable, well-documented, dual-licensed (RSALv2/SSPLv1)
- Matches common production patterns

**Verified:** [Docker Hub redis](https://hub.docker.com/_/redis) - 7.4-alpine available

### No New Frameworks for Rate Limiter Service

The rate limiter service does NOT need FastAPI, Flask, or any web framework.

**Why:**
- The rate limiter is an internal service, not a REST API
- Communication happens via Redis (shared state) and optional HTTP health checks
- Operator queries rate limiter state, not rate limiter's HTTP API
- Keep complexity minimal - this is a demo proving the abstraction

---

## Rate Limiter Implementation

### Service Architecture

```
+----------------+     +----------------+     +----------------+
| Rate Limiter 1 |     | Rate Limiter 2 |     | Rate Limiter 3 |
| (Python async) |     | (Python async) |     | (Python async) |
+-------+--------+     +-------+--------+     +-------+--------+
        |                      |                      |
        +----------+-----------+----------------------+
                   |
            +------v------+
            |    Redis    |
            | (7.4-alpine)|
            +-------------+
```

### Recommended Algorithm: Sliding Window Counter

**Why sliding window counter:**
- Simpler than sliding window log (no timestamp storage per request)
- More accurate than fixed window (smooths bucket boundaries)
- Memory efficient (one counter per sub-interval, not per request)
- Easy to implement with Redis INCR + EXPIRE

**Implementation pattern:**
```python
async def is_rate_limited(client_id: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding window counter using Redis hash.

    Divide window into 1-second sub-intervals.
    Count requests in current window by summing sub-interval counts.
    """
    now = int(time.time())
    window_key = f"ratelimit:{client_id}"
    sub_interval = str(now)

    async with redis_client.pipeline() as pipe:
        # Increment current sub-interval
        pipe.hincrby(window_key, sub_interval, 1)
        # Set expiry on entire hash
        pipe.expire(window_key, window_seconds + 1)
        # Get all sub-interval counts
        pipe.hgetall(window_key)
        results = await pipe.execute()

    counts = results[2]
    # Sum counts within window
    total = sum(
        int(count) for ts, count in counts.items()
        if now - int(ts) < window_seconds
    )

    return total > limit
```

### Rate Limiter Service Structure

```
packages/operator-ratelimiter/
  src/operator_ratelimiter/
    __init__.py
    service.py        # Rate limiter async service
    redis_client.py   # Redis connection management
    subject.py        # Subject Protocol implementation
    types.py          # Pydantic models for metrics
  pyproject.toml
```

### pyproject.toml for operator-ratelimiter

```toml
[project]
name = "operator-ratelimiter"
version = "0.1.0"
description = "Distributed rate limiter subject for the AI-powered operator"
requires-python = ">=3.11"
dependencies = [
    "operator-core",
    "redis>=7.1.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
fast = [
    "hiredis>=3.1.0",  # C parser for better performance
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/operator_ratelimiter"]
```

---

## Redis Setup

### Docker Compose Configuration

```yaml
services:
  redis:
    image: redis:7.4-alpine
    restart: unless-stopped
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes --maxmemory 100mb --maxmemory-policy allkeys-lru
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3

  ratelimiter-1:
    build: ./packages/operator-ratelimiter
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ID=node-1
    depends_on:
      redis:
        condition: service_healthy

  ratelimiter-2:
    build: ./packages/operator-ratelimiter
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ID=node-2
    depends_on:
      redis:
        condition: service_healthy

  ratelimiter-3:
    build: ./packages/operator-ratelimiter
    environment:
      - REDIS_URL=redis://redis:6379
      - NODE_ID=node-3
    depends_on:
      redis:
        condition: service_healthy

volumes:
  redis-data:
```

### Redis Configuration Notes

| Setting | Value | Why |
|---------|-------|-----|
| `appendonly yes` | Enable AOF | Persist state, recover on restart |
| `maxmemory 100mb` | Memory limit | Demo doesn't need much |
| `maxmemory-policy allkeys-lru` | Eviction | Evict old keys when full |

**No password for demo** - This is intentional simplicity. Production would use `--requirepass`.

---

## Integration with Operator

### Subject Protocol Implementation

The rate limiter subject implements the Subject Protocol from operator-core:

```python
# operator_ratelimiter/subject.py
from dataclasses import dataclass
from operator_core.subject import Subject
from operator_core.types import Store, StoreMetrics, ClusterMetrics, Region

@dataclass
class RateLimiterSubject:
    """Rate limiter implementation of Subject Protocol."""

    redis_client: redis.Redis

    # Observations
    async def get_stores(self) -> list[Store]:
        """Return rate limiter nodes as 'stores'."""
        ...

    async def get_store_metrics(self, store_id: str) -> StoreMetrics:
        """Return rate metrics for a specific node."""
        ...

    async def get_cluster_metrics(self) -> ClusterMetrics:
        """Return aggregate rate limiting metrics."""
        ...

    # Actions
    async def set_rate_limit(self, client_id: str, limit: int) -> None:
        """Adjust rate limit for a client."""
        ...

    async def reset_client(self, client_id: str) -> None:
        """Reset rate limit counters for a client."""
        ...
```

### Metric Mapping

Rate limiter concepts map to existing operator-core types:

| Rate Limiter Concept | Operator Type | Notes |
|---------------------|---------------|-------|
| Rate limiter node | `Store` | Each limiter instance is a "store" |
| Request rate | `StoreMetrics.qps` | Requests per second |
| Rejection rate | `StoreMetrics.latency_p99` | Reuse field for rejection % |
| Node count | `ClusterMetrics.store_count` | Number of limiter instances |
| Rate distribution | `ClusterMetrics.leader_count` | Reuse for rate distribution |

### Anomaly Types for AI Diagnosis

Rate limiter anomalies the operator can detect:

| Anomaly | Detection | Symptoms |
|---------|-----------|----------|
| Rate spike | Request rate > threshold | High QPS across nodes |
| Uneven distribution | Variance in per-node rates | One node handling disproportionate traffic |
| Redis latency | Slow Redis responses | All nodes show degraded performance |
| Limit breach | Clients exceeding limits | High rejection rate |

---

## What NOT to Add

### Do NOT Add These Technologies

| Technology | Why Not |
|------------|---------|
| **FastAPI/Flask** | Rate limiter is not a REST API; operator queries Redis directly |
| **Celery/RQ** | No background job needs; rate limiting is synchronous |
| **Redis Cluster** | Single Redis is sufficient for demo; clustering adds complexity |
| **Lua scripting** | INCR + EXPIRE is atomic enough; Lua is overkill for demo |
| **Rate limiting libraries** (limits, slowapi, etc.) | We're building the limiter, not using one |
| **Prometheus client** | Reuse existing operator-core Prometheus integration |
| **New testing frameworks** | Use existing pytest setup |

### Why Minimal Stack

This milestone proves the Subject Protocol abstraction works with different systems. The rate limiter should be:
- **Simple enough to understand** in minutes
- **Complex enough to demonstrate** distributed coordination
- **Different enough from TiKV** to prove abstraction value

Adding frameworks would obscure the demonstration.

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| redis-py choice | HIGH | Official library, verified on PyPI, absorbed aioredis |
| Redis 7.4 Docker | HIGH | Verified on Docker Hub, stable version |
| Sliding window counter | HIGH | Standard algorithm, well-documented pattern |
| Subject Protocol integration | HIGH | Follows existing operator-tikv pattern |
| No-framework approach | MEDIUM | Simpler but may need HTTP health endpoints later |

---

## Sources

### Official Documentation (HIGH confidence)
- [redis-py on PyPI](https://pypi.org/project/redis/) - Version 7.1.0, Python 3.10+ support
- [redis-py async examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - Connection pooling, pipeline usage
- [Redis Docker Hub](https://hub.docker.com/_/redis) - Official image, version tags

### Redis Rate Limiting Patterns (MEDIUM confidence)
- [Redis rate limiting guide](https://redis.io/learn/howtos/ratelimiting) - Official Redis documentation
- [Sliding window counter explanation](https://medium.com/redis-with-raphael-de-lio/sliding-window-counter-rate-limiter-redis-java-1ba8901c02e5) - Algorithm details
- [Redis rate limiting overview](https://redis.io/glossary/rate-limiting/) - Algorithm comparison

### Redis Client Consolidation (HIGH confidence)
- [aioredis merger FAQ](https://redis.io/faq/doc/26366kjrif/what-is-the-difference-between-aioredis-v2-0-and-redis-py-asyncio) - Official Redis statement on merger
