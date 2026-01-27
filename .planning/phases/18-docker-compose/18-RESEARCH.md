# Phase 18: Docker Compose Environment - Research

**Researched:** 2026-01-26
**Domain:** Docker Compose, Container Orchestration, Load Testing
**Confidence:** HIGH

## Summary

This phase creates a reproducible development environment for the rate limiter cluster using Docker Compose. The research confirms that Docker Compose v2's `depends_on` with `condition: service_healthy` provides the service ordering needed without wait-for-it scripts. Prometheus configuration can be embedded inline using Docker's `configs` feature, eliminating separate config files. The load generator should use `httpx` (already in the project stack) with `asyncio` for a lightweight, consistent approach.

The architecture is straightforward: single Redis instance for shared state, 3 rate limiter nodes (FastAPI/uvicorn), Prometheus scraping all nodes, and a load generator container. All services communicate over a single Docker network. Port mappings use environment variable substitution from `.env` for configurability.

**Primary recommendation:** Use Docker Compose v2 features (healthchecks, configs, depends_on conditions) with the existing project stack (Python 3.11, httpx) for a clean, maintainable development environment.

## Standard Stack

The established tools for this domain:

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| Docker Compose | v2.x | Container orchestration | Native healthcheck conditions, configs feature |
| python:3.11-slim-bookworm | 3.11 | Base image for FastAPI | Matches project requires-python, slim reduces image size |
| redis:7-alpine | 7.x | Shared state storage | Small image, production-stable, built-in healthcheck support |
| prom/prometheus | v2.50+ | Metrics collection | Official image, well-documented |
| httpx | >=0.27.0 | Load generator HTTP client | Already in project stack, async support |

### Supporting
| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| uvicorn | >=0.32.0 | ASGI server | Running FastAPI in containers |
| itertools.cycle | stdlib | Round-robin targeting | Load generator target selection |
| asyncio.Semaphore | stdlib | Rate limiting | Controlling concurrent requests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | Locust | Locust is heavyweight, has web UI; httpx is lightweight, already in stack |
| httpx | aiohttp | aiohttp is faster but adds new dependency; httpx consistency wins |
| Inline prometheus.yml | Separate file | Separate file requires volume mount; inline keeps everything in docker-compose.yml |
| python:slim-bookworm | python:alpine | Alpine uses musl libc, causes compatibility issues with some packages |

## Architecture Patterns

### Recommended Project Structure
```
packages/ratelimiter-service/
├── Dockerfile                 # Multi-stage build for FastAPI service
├── pyproject.toml            # Already exists
└── src/ratelimiter_service/  # Already exists
    └── main.py               # Has /health endpoint

docker/
├── docker-compose.yml        # Main compose file with all services
├── .env.example             # Template for port configuration
└── loadgen/
    ├── Dockerfile           # Load generator container
    └── loadgen.py           # httpx-based load generator script
```

### Pattern 1: Docker Compose with Healthcheck Conditions
**What:** Use `depends_on` with `condition: service_healthy` to ensure proper startup order
**When to use:** Always - ensures Redis is ready before rate limiters start
**Source:** [Docker Compose Startup Order](https://docs.docker.com/compose/how-tos/startup-order/)

```yaml
services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3
      start_period: 5s

  ratelimiter-1:
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s
```

### Pattern 2: Inline Prometheus Configuration
**What:** Use Docker configs feature to embed prometheus.yml in docker-compose.yml
**When to use:** Dev environments where single-file simplicity is valued
**Source:** [Prometheus Docker Compose Setup](https://spacelift.io/blog/prometheus-docker-compose)

```yaml
configs:
  prometheus_config:
    content: |
      global:
        scrape_interval: 15s
      scrape_configs:
        - job_name: 'ratelimiter'
          static_configs:
            - targets:
              - ratelimiter-1:8000
              - ratelimiter-2:8000
              - ratelimiter-3:8000

services:
  prometheus:
    image: prom/prometheus:v2.50.0
    configs:
      - source: prometheus_config
        target: /etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
```

### Pattern 3: Environment Variable Port Mapping
**What:** Use .env file for configurable port mappings
**When to use:** Always - allows users to avoid port conflicts
**Source:** [Docker Compose Environment Variables](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)

```yaml
# docker-compose.yml
services:
  ratelimiter-1:
    ports:
      - "${RATELIMITER_1_PORT:-8001}:8000"
  prometheus:
    ports:
      - "${PROMETHEUS_PORT:-9090}:9090"

# .env
RATELIMITER_1_PORT=8001
RATELIMITER_2_PORT=8002
RATELIMITER_3_PORT=8003
PROMETHEUS_PORT=9090
```

### Pattern 4: Lightweight Python Dockerfile
**What:** Single-stage Dockerfile for FastAPI with proper layer caching
**When to use:** Dev environments where rebuild time matters more than image size
**Source:** [FastAPI Docker Deployment](https://fastapi.tiangolo.com/deployment/docker/)

```dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/

# Use exec form for graceful shutdown
CMD ["uvicorn", "ratelimiter_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Anti-Patterns to Avoid
- **Shell form CMD:** `CMD uvicorn ...` prevents graceful shutdown; use exec form `CMD ["uvicorn", ...]`
- **restart: always in dev:** Hides failures; use `restart: "no"` to see errors immediately
- **Missing start_period:** Services marked unhealthy during startup; always set start_period
- **Hardcoded ports:** Causes conflicts; use .env for all host port mappings

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service startup ordering | Sleep loops, wait-for-it scripts | depends_on + condition: service_healthy | Native Docker feature, reliable |
| Redis readiness check | TCP connection test | redis-cli ping healthcheck | Verifies Redis is actually ready, not just port open |
| HTTP healthcheck | Custom curl scripts | FastAPI /health endpoint + curl healthcheck | Consistent, testable |
| Rate limiting in load gen | Manual timing code | asyncio.Semaphore + asyncio.sleep | Proven pattern, handles concurrency |
| Round-robin targeting | Custom index tracking | itertools.cycle | Stdlib, correct, simple |

**Key insight:** Docker Compose v2 has mature dependency management. All wait-for-it patterns are now unnecessary with proper healthchecks.

## Common Pitfalls

### Pitfall 1: Missing curl in Python slim images
**What goes wrong:** Healthcheck fails with "curl: not found"
**Why it happens:** python:slim-bookworm doesn't include curl
**How to avoid:** Install curl in Dockerfile: `apt-get install -y --no-install-recommends curl`
**Warning signs:** Container immediately marked unhealthy

### Pitfall 2: Healthcheck without start_period
**What goes wrong:** Container marked unhealthy before app fully starts
**Why it happens:** Healthcheck runs immediately, FastAPI still loading
**How to avoid:** Set `start_period: 10s` for application containers
**Warning signs:** Containers restart loop on slow startup

### Pitfall 3: Redis PONG check not validated
**What goes wrong:** Healthcheck passes even when Redis returns error
**Why it happens:** Using `CMD redis-cli ping` without checking output
**How to avoid:** Use `["CMD-SHELL", "redis-cli ping | grep PONG"]` or trust basic ping (usually sufficient)
**Warning signs:** Services start before Redis ready (rare)

### Pitfall 4: Load generator overwhelms single-threaded async
**What goes wrong:** Load generator starves itself, low actual RPS
**Why it happens:** Not limiting concurrent connections
**How to avoid:** Use `httpx.Limits(max_connections=100)` and `asyncio.Semaphore` for rate limiting
**Warning signs:** Lower RPS than configured, high latency

### Pitfall 5: Prometheus can't reach containers by name
**What goes wrong:** Prometheus shows targets as DOWN
**Why it happens:** Services not on same network, or wrong hostname
**How to avoid:** All services on same Docker network, use service names as hostnames
**Warning signs:** "connection refused" in Prometheus logs

### Pitfall 6: Environment variables not substituted in ports
**What goes wrong:** Literal `${VAR}` in port mapping instead of value
**Why it happens:** Variable not defined, no default
**How to avoid:** Use `${VAR:-default}` syntax for fallback values
**Warning signs:** Docker Compose parse error or unexpected port

## Code Examples

Verified patterns from official sources:

### Complete docker-compose.yml Structure
```yaml
# Source: Docker Compose documentation + Prometheus guides
configs:
  prometheus_config:
    content: |
      global:
        scrape_interval: 15s
        evaluation_interval: 15s
      scrape_configs:
        - job_name: 'ratelimiter'
          static_configs:
            - targets:
              - ratelimiter-1:8000
              - ratelimiter-2:8000
              - ratelimiter-3:8000

services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 3
      start_period: 5s
    networks:
      - ratelimiter

  ratelimiter-1:
    build:
      context: ./packages/ratelimiter-service
    environment:
      - RATELIMITER_REDIS_URL=redis://redis:6379
      - RATELIMITER_NODE_ID=node-1
      - RATELIMITER_NODE_HOST=ratelimiter-1
      - RATELIMITER_NODE_PORT=8000
    ports:
      - "${RATELIMITER_1_PORT:-8001}:8000"
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: "no"
    networks:
      - ratelimiter

  # ratelimiter-2 and ratelimiter-3 follow same pattern...

  prometheus:
    image: prom/prometheus:v2.50.0
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    configs:
      - source: prometheus_config
        target: /etc/prometheus/prometheus.yml
    ports:
      - "${PROMETHEUS_PORT:-9090}:9090"
    depends_on:
      ratelimiter-1:
        condition: service_healthy
      ratelimiter-2:
        condition: service_healthy
      ratelimiter-3:
        condition: service_healthy
    networks:
      - ratelimiter

  loadgen:
    build:
      context: ./docker/loadgen
    environment:
      - TARGETS=http://ratelimiter-1:8000,http://ratelimiter-2:8000,http://ratelimiter-3:8000
      - RPS=10
      - DURATION=60
    depends_on:
      ratelimiter-1:
        condition: service_healthy
      ratelimiter-2:
        condition: service_healthy
      ratelimiter-3:
        condition: service_healthy
    networks:
      - ratelimiter

networks:
  ratelimiter:
    driver: bridge
```

### Load Generator Script Pattern
```python
# Source: httpx async documentation + asyncio patterns
import asyncio
import itertools
import os
import time
from dataclasses import dataclass

import httpx


@dataclass
class Stats:
    requests: int = 0
    success: int = 0
    failed: int = 0
    start_time: float = 0

    def report(self):
        elapsed = time.time() - self.start_time
        rps = self.requests / elapsed if elapsed > 0 else 0
        print(f"Requests: {self.requests} | Success: {self.success} | "
              f"Failed: {self.failed} | RPS: {rps:.1f}")


async def load_generator(
    targets: list[str],
    rps: float,
    duration: int,
    stats: Stats,
):
    """Generate load against targets in round-robin fashion."""
    target_cycle = itertools.cycle(targets)
    interval = 1.0 / rps
    semaphore = asyncio.Semaphore(100)  # Max concurrent requests

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=100),
        timeout=httpx.Timeout(10.0),
    ) as client:
        end_time = time.time() + duration

        async def make_request(target: str):
            async with semaphore:
                try:
                    # Example: check rate limit for a test key
                    resp = await client.get(f"{target}/rate-limit/test-key")
                    stats.requests += 1
                    if resp.status_code in (200, 429):  # OK or rate limited
                        stats.success += 1
                    else:
                        stats.failed += 1
                except Exception:
                    stats.requests += 1
                    stats.failed += 1

        tasks = []
        while time.time() < end_time:
            target = next(target_cycle)
            tasks.append(asyncio.create_task(make_request(target)))
            await asyncio.sleep(interval)

            # Periodic stats report
            if stats.requests % 100 == 0:
                stats.report()

        # Wait for remaining requests
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    targets = os.environ.get("TARGETS", "http://localhost:8000").split(",")
    rps = float(os.environ.get("RPS", "10"))
    duration = int(os.environ.get("DURATION", "60"))

    stats = Stats(start_time=time.time())
    print(f"Starting load test: {rps} RPS for {duration}s against {targets}")

    await load_generator(targets, rps, duration, stats)

    print("\n=== Final Results ===")
    stats.report()


if __name__ == "__main__":
    asyncio.run(main())
```

### Dockerfile for Rate Limiter Service
```dockerfile
# Source: FastAPI Docker documentation
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install curl for healthcheck (required in slim image)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer caching
COPY pyproject.toml .

# Install the package
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Use exec form for proper signal handling
CMD ["uvicorn", "ratelimiter_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Load Generator Dockerfile
```dockerfile
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install httpx
RUN pip install --no-cache-dir httpx>=0.27.0

COPY loadgen.py .

CMD ["python", "loadgen.py"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| wait-for-it.sh scripts | depends_on with condition | Docker Compose v2 | No external scripts needed |
| links: directive | networks + service names | Docker Compose v3 | Cleaner networking |
| version: "3.x" | No version field | Compose v2.x | Version field deprecated |
| Separate prometheus.yml | configs with content | Compose v2.17+ | Single-file deployment |

**Deprecated/outdated:**
- `version:` field in docker-compose.yml - no longer required, ignored by Compose v2
- `links:` directive - replaced by networks, only for legacy compatibility
- wait-for-it, dockerize scripts - replaced by healthcheck conditions

## Open Questions

Things that couldn't be fully resolved:

1. **Prometheus scrape interval optimization**
   - What we know: 15s is standard default, 5-10s for higher resolution
   - What's unclear: Optimal interval for demo visibility vs resource usage
   - Recommendation: Start with 15s (standard), user can configure lower if needed

2. **Load generator burst pattern implementation**
   - What we know: Context mentions "burst spikes + gradual ramp-up" patterns
   - What's unclear: Specific burst ratios and ramp profiles desired
   - Recommendation: Implement configurable burst (2x-5x baseline for 5-10s) via environment variables

## Sources

### Primary (HIGH confidence)
- [Docker Compose Startup Order](https://docs.docker.com/compose/how-tos/startup-order/) - depends_on conditions
- [Docker Compose Services Reference](https://docs.docker.com/reference/compose-file/services/) - healthcheck syntax
- [FastAPI Docker Deployment](https://fastapi.tiangolo.com/deployment/docker/) - Dockerfile patterns

### Secondary (MEDIUM confidence)
- [Prometheus Docker Compose Setup](https://spacelift.io/blog/prometheus-docker-compose) - configs feature
- [Last9 Docker Compose Health Checks](https://last9.io/blog/docker-compose-health-checks/) - healthcheck best practices
- [Redis Docker Healthcheck](https://www.baeldung.com/ops/redis-server-docker-image-health) - redis-cli ping pattern

### Tertiary (LOW confidence)
- [Python Docker Image Best Practices](https://pythonspeed.com/articles/base-image-python-docker-images/) - base image selection (general guidance)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Using official Docker, Redis, Prometheus images with documented patterns
- Architecture: HIGH - All patterns from official Docker Compose and FastAPI documentation
- Pitfalls: HIGH - Common issues documented across multiple sources

**Research date:** 2026-01-26
**Valid until:** 60 days (Docker Compose patterns are stable)
