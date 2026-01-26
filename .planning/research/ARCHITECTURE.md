# Architecture Research: Rate Limiter Subject Integration

**Project:** Operator v2.1 Rate Limiter Subject
**Researched:** 2026-01-26
**Confidence:** HIGH (verified with existing codebase, established patterns)

## Executive Summary

The rate limiter subject integrates with the existing operator architecture by following the established Subject Protocol pattern from `operator-tikv`. The integration requires a new `operator-ratelimiter` package implementing the same interfaces (Subject, get_action_definitions, SubjectConfig), with a custom rate limiter service exposing HTTP APIs for state observation and action execution.

**Key design decision:** The rate limiter service must expose APIs that mirror what TiKV's PD API provides - cluster state, metrics, and action endpoints. This is intentionally different from using an off-the-shelf rate limiter to prove the operator can work with novel systems Claude hasn't seen in training.

## Component Overview

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `RateLimiterSubject` | `packages/operator-ratelimiter/src/operator_ratelimiter/subject.py` | Subject Protocol implementation |
| `RateLimiterClient` | `packages/operator-ratelimiter/src/operator_ratelimiter/client.py` | HTTP client for rate limiter management API |
| `RedisClient` | `packages/operator-ratelimiter/src/operator_ratelimiter/redis_client.py` | Redis client for metrics/state queries |
| `RateLimiterInvariants` | `packages/operator-ratelimiter/src/operator_ratelimiter/invariants.py` | Rate limiter-specific invariant checks |
| Rate Limiter Service | `subjects/ratelimiter/service/` | Custom rate limiter with management API |
| Docker Compose | `subjects/ratelimiter/docker-compose.yaml` | 3-node cluster + Redis + Prometheus |

### Modified Components

| Component | Change |
|-----------|--------|
| `operator-core/monitor/loop.py` | Parameterize subject type (currently hardcoded TiKV) |
| `operator-core/monitor/types.py` | Generalize violation key generation |
| `operator-core/cli/main.py` | Add `--subject` flag to select subject |

## Architecture Diagram

```
                        operator-core
                             |
                +------------+------------+
                |                         |
         operator-tikv            operator-ratelimiter
                |                         |
       +--------+--------+       +--------+--------+
       |        |        |       |        |        |
    PDClient  Prom    Invariants Client  Redis  Invariants
       |        |        |       |        |        |
       v        v        v       v        v        v
    TiKV/PD  Prometheus        Rate      Redis  Prometheus
    Cluster               Limiter Cluster  Cluster
```

## Subject Protocol Implementation

### RateLimiterSubject Class

```python
# packages/operator-ratelimiter/src/operator_ratelimiter/subject.py

from dataclasses import dataclass
from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.config import Action, Observation, SLO, SubjectConfig

# Rate limiter-specific types (not TiKV types)
from operator_ratelimiter.types import (
    RateLimiterNode,
    RateLimiterMetrics,
    LimitConfig,
    ClusterState,
)
from operator_ratelimiter.client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient


RATELIMITER_CONFIG = SubjectConfig(
    name="ratelimiter",
    actions=[
        Action(
            "reset_counter",
            ["key"],
            description="Reset rate limit counter for a specific key",
        ),
        Action(
            "update_limit",
            ["key_pattern", "max_requests", "window_seconds"],
            description="Update rate limit configuration for a key pattern",
        ),
        Action(
            "block_key",
            ["key", "duration_seconds"],
            description="Temporarily block a key entirely",
        ),
        Action(
            "unblock_key",
            ["key"],
            description="Remove block from a key",
        ),
        Action(
            "drain_node",
            ["node_id"],
            description="Stop accepting requests on a node",
        ),
    ],
    observations=[
        Observation(
            "get_nodes",
            "list[RateLimiterNode]",
            description="List all rate limiter nodes",
        ),
        Observation(
            "get_node_metrics",
            "RateLimiterMetrics",
            description="Get metrics for a specific node",
        ),
        Observation(
            "get_cluster_state",
            "ClusterState",
            description="Get cluster-wide state including limits and counters",
        ),
        Observation(
            "get_hot_keys",
            "list[str]",
            description="Get keys approaching or exceeding limits",
        ),
    ],
    slos=[
        SLO(
            "request_latency_p99",
            target=10.0,
            unit="ms",
            grace_period_s=30,
            description="99th percentile rate limit check latency",
        ),
        SLO(
            "false_block_rate",
            target=0.01,
            unit="percent",
            grace_period_s=60,
            description="Percentage of incorrectly blocked requests",
        ),
        SLO(
            "node_availability",
            target=100.0,
            unit="percent",
            grace_period_s=0,
            description="All nodes should be healthy",
        ),
        SLO(
            "redis_connectivity",
            target=100.0,
            unit="percent",
            grace_period_s=0,
            description="All nodes should be connected to Redis",
        ),
    ],
)


@dataclass
class RateLimiterSubject:
    """
    Rate limiter implementation of the Subject Protocol.

    Provides observations about rate limiter cluster state and
    implements actions for managing rate limits and counters.
    """

    client: RateLimiterClient  # HTTP client for management API
    redis: RedisClient         # Direct Redis access for metrics

    @classmethod
    def get_config(cls) -> SubjectConfig:
        return RATELIMITER_CONFIG

    def get_action_definitions(self) -> list[ActionDefinition]:
        """Return action definitions for ActionRegistry."""
        return [
            ActionDefinition(
                name="reset_counter",
                description="Reset rate limit counter for a specific key",
                parameters={
                    "key": ParamDef(
                        type="str",
                        description="The rate limit key to reset",
                        required=True,
                    ),
                },
                risk_level="medium",
                requires_approval=False,
            ),
            ActionDefinition(
                name="update_limit",
                description="Update rate limit configuration",
                parameters={
                    "key_pattern": ParamDef(
                        type="str",
                        description="Key pattern to apply limit to",
                        required=True,
                    ),
                    "max_requests": ParamDef(
                        type="int",
                        description="Maximum requests per window",
                        required=True,
                    ),
                    "window_seconds": ParamDef(
                        type="int",
                        description="Window duration in seconds",
                        required=True,
                    ),
                },
                risk_level="high",
                requires_approval=False,
            ),
            ActionDefinition(
                name="block_key",
                description="Temporarily block a key entirely",
                parameters={
                    "key": ParamDef(
                        type="str",
                        description="Key to block",
                        required=True,
                    ),
                    "duration_seconds": ParamDef(
                        type="int",
                        description="How long to block",
                        required=True,
                    ),
                },
                risk_level="high",
                requires_approval=False,
            ),
            ActionDefinition(
                name="drain_node",
                description="Stop accepting requests on a node",
                parameters={
                    "node_id": ParamDef(
                        type="str",
                        description="Node ID to drain",
                        required=True,
                    ),
                },
                risk_level="high",
                requires_approval=False,
            ),
        ]

    # -------------------------------------------------------------------------
    # Observations
    # -------------------------------------------------------------------------

    async def get_nodes(self) -> list[RateLimiterNode]:
        """Get all rate limiter nodes."""
        return await self.client.get_nodes()

    async def get_node_metrics(self, node_id: str) -> RateLimiterMetrics:
        """Get metrics for a specific node."""
        return await self.client.get_node_metrics(node_id)

    async def get_cluster_state(self) -> ClusterState:
        """Get cluster-wide state."""
        return await self.client.get_cluster_state()

    async def get_hot_keys(self) -> list[str]:
        """Get keys approaching or exceeding limits."""
        return await self.redis.get_hot_keys()

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    async def reset_counter(self, key: str) -> None:
        """Reset rate limit counter for a key."""
        await self.client.reset_counter(key)

    async def update_limit(
        self, key_pattern: str, max_requests: int, window_seconds: int
    ) -> None:
        """Update rate limit configuration."""
        await self.client.update_limit(key_pattern, max_requests, window_seconds)

    async def block_key(self, key: str, duration_seconds: int) -> None:
        """Temporarily block a key."""
        await self.client.block_key(key, duration_seconds)

    async def unblock_key(self, key: str) -> None:
        """Remove block from a key."""
        await self.client.unblock_key(key)

    async def drain_node(self, node_id: str) -> None:
        """Stop accepting requests on a node."""
        await self.client.drain_node(node_id)
```

### Type Definitions

```python
# packages/operator-ratelimiter/src/operator_ratelimiter/types.py

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RateLimiterNode:
    """A rate limiter service instance."""
    id: str
    address: str
    state: str  # "healthy", "unhealthy", "draining"
    redis_connected: bool


@dataclass
class RateLimiterMetrics:
    """Performance metrics for a rate limiter node."""
    node_id: str
    requests_per_second: float
    allowed_rate: float  # Percentage of requests allowed
    blocked_rate: float  # Percentage of requests blocked
    latency_p50_ms: float
    latency_p99_ms: float
    redis_latency_ms: float
    active_keys: int


@dataclass
class LimitConfig:
    """Rate limit configuration for a key pattern."""
    key_pattern: str
    max_requests: int
    window_seconds: int
    created_at: datetime
    updated_at: datetime


@dataclass
class ClusterState:
    """Cluster-wide rate limiter state."""
    node_count: int
    healthy_nodes: int
    total_keys: int
    total_requests_per_second: float
    limits: list[LimitConfig]
```

## Rate Limiter Service Design

The rate limiter service is a custom Python service that must expose:

### Required APIs

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/nodes` | GET | List all nodes with health status |
| `/api/v1/nodes/{id}` | GET | Get specific node details |
| `/api/v1/nodes/{id}/metrics` | GET | Get node metrics |
| `/api/v1/cluster/state` | GET | Get cluster-wide state |
| `/api/v1/counters/{key}` | DELETE | Reset counter for key |
| `/api/v1/limits` | GET/POST | Get/update limit configurations |
| `/api/v1/blocks/{key}` | POST/DELETE | Block/unblock key |
| `/api/v1/nodes/{id}/drain` | POST | Start draining node |
| `/health` | GET | Health check endpoint |
| `/metrics` | GET | Prometheus metrics |

### Core Rate Limiting Logic

The service implements sliding window rate limiting using Redis sorted sets:

```python
# Pseudocode for rate limit check
async def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Returns True if request is allowed, False if blocked.

    Uses Redis sorted set with timestamps as scores.
    """
    now = time.time()
    window_start = now - window_seconds

    # Atomic Lua script for consistency
    script = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window_start = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    local ttl = tonumber(ARGV[4])

    -- Remove old entries
    redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

    -- Count current entries
    local count = redis.call('ZCARD', key)

    if count < limit then
        -- Add new entry
        redis.call('ZADD', key, now, now .. '-' .. math.random())
        redis.call('EXPIRE', key, ttl)
        return 1  -- Allowed
    else
        return 0  -- Blocked
    end
    """

    result = await redis.eval(script, [key], [now, window_start, limit, window_seconds * 2])
    return result == 1
```

### Prometheus Metrics

The service exposes these metrics for monitoring:

```
# Counter metrics
ratelimiter_requests_total{node_id, result="allowed|blocked"}
ratelimiter_redis_operations_total{node_id, operation}

# Gauge metrics
ratelimiter_active_keys{node_id}
ratelimiter_node_state{node_id, state}

# Histogram metrics
ratelimiter_request_duration_seconds{node_id, quantile}
ratelimiter_redis_latency_seconds{node_id, quantile}
```

## Metrics and Observability

### Metrics Flow

```
Rate Limiter Node 1 -----> Prometheus <----- operator-ratelimiter
Rate Limiter Node 2 -----> (scrapes) <----- (queries)
Rate Limiter Node 3 ------->         <-----
         |
         v
       Redis (shared state, also scraped for metrics)
```

### RateLimiterMetrics Collection

```python
# packages/operator-ratelimiter/src/operator_ratelimiter/prom_client.py

@dataclass
class PrometheusClient:
    """Prometheus client for rate limiter metrics."""

    http: httpx.AsyncClient

    async def get_node_metrics(
        self, node_id: str, node_address: str
    ) -> RateLimiterMetrics:
        """Get metrics for a specific rate limiter node."""

        addr_pattern = node_address.replace(":", ".*")

        # Request rate
        rps = await self.get_metric_value(
            f'sum(rate(ratelimiter_requests_total{{node_id="{node_id}"}}[1m]))'
        ) or 0.0

        # Allowed vs blocked
        allowed = await self.get_metric_value(
            f'sum(rate(ratelimiter_requests_total{{node_id="{node_id}",result="allowed"}}[1m]))'
        ) or 0.0

        blocked = await self.get_metric_value(
            f'sum(rate(ratelimiter_requests_total{{node_id="{node_id}",result="blocked"}}[1m]))'
        ) or 0.0

        total = allowed + blocked
        allowed_rate = (allowed / total * 100) if total > 0 else 100.0
        blocked_rate = (blocked / total * 100) if total > 0 else 0.0

        # Latencies
        latency_p50 = await self.get_metric_value(
            f'histogram_quantile(0.50, rate(ratelimiter_request_duration_seconds_bucket{{node_id="{node_id}"}}[1m]))'
        ) or 0.0

        latency_p99 = await self.get_metric_value(
            f'histogram_quantile(0.99, rate(ratelimiter_request_duration_seconds_bucket{{node_id="{node_id}"}}[1m]))'
        ) or 0.0

        redis_latency = await self.get_metric_value(
            f'histogram_quantile(0.99, rate(ratelimiter_redis_latency_seconds_bucket{{node_id="{node_id}"}}[1m]))'
        ) or 0.0

        # Active keys
        active_keys = await self.get_metric_value(
            f'ratelimiter_active_keys{{node_id="{node_id}"}}'
        ) or 0

        return RateLimiterMetrics(
            node_id=node_id,
            requests_per_second=rps,
            allowed_rate=allowed_rate,
            blocked_rate=blocked_rate,
            latency_p50_ms=latency_p50 * 1000,
            latency_p99_ms=latency_p99 * 1000,
            redis_latency_ms=redis_latency * 1000,
            active_keys=int(active_keys),
        )
```

## Invariant Definitions

```python
# packages/operator-ratelimiter/src/operator_ratelimiter/invariants.py

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from operator_ratelimiter.types import RateLimiterNode, RateLimiterMetrics


@dataclass
class InvariantViolation:
    """Rate limiter invariant violation."""
    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    node_id: str | None = None
    severity: str = "warning"


@dataclass
class InvariantConfig:
    name: str
    grace_period: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    threshold: float = 0.0
    severity: str = "warning"


# Default configurations
NODE_DOWN_CONFIG = InvariantConfig(
    name="node_down",
    grace_period=timedelta(seconds=0),
    severity="critical",
)

HIGH_LATENCY_CONFIG = InvariantConfig(
    name="high_latency",
    grace_period=timedelta(seconds=30),
    threshold=10.0,  # 10ms P99
    severity="warning",
)

REDIS_DISCONNECTED_CONFIG = InvariantConfig(
    name="redis_disconnected",
    grace_period=timedelta(seconds=0),
    severity="critical",
)

HIGH_BLOCK_RATE_CONFIG = InvariantConfig(
    name="high_block_rate",
    grace_period=timedelta(seconds=60),
    threshold=50.0,  # 50% blocked = something wrong
    severity="warning",
)


class InvariantChecker:
    """Rate limiter invariant checker with grace period support."""

    def __init__(self) -> None:
        self._first_seen: dict[str, datetime] = {}

    def check_nodes_healthy(
        self, nodes: list[RateLimiterNode]
    ) -> list[InvariantViolation]:
        """Check that all nodes are healthy."""
        violations = []
        config = NODE_DOWN_CONFIG

        for node in nodes:
            is_unhealthy = node.state != "healthy"
            violation = self._check_with_grace_period(
                config=config,
                is_violated=is_unhealthy,
                message=f"Node {node.id} at {node.address} is {node.state}",
                node_id=node.id,
            )
            if violation:
                violations.append(violation)

        return violations

    def check_redis_connectivity(
        self, nodes: list[RateLimiterNode]
    ) -> list[InvariantViolation]:
        """Check that all nodes are connected to Redis."""
        violations = []
        config = REDIS_DISCONNECTED_CONFIG

        for node in nodes:
            is_disconnected = not node.redis_connected
            violation = self._check_with_grace_period(
                config=config,
                is_violated=is_disconnected,
                message=f"Node {node.id} lost Redis connection",
                node_id=node.id,
            )
            if violation:
                violations.append(violation)

        return violations

    def check_latency(
        self, metrics: RateLimiterMetrics
    ) -> InvariantViolation | None:
        """Check that P99 latency is below threshold."""
        config = HIGH_LATENCY_CONFIG
        is_high = metrics.latency_p99_ms > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=f"Node {metrics.node_id} P99 latency {metrics.latency_p99_ms:.1f}ms exceeds {config.threshold}ms",
            node_id=metrics.node_id,
        )

    def check_block_rate(
        self, metrics: RateLimiterMetrics
    ) -> InvariantViolation | None:
        """Check for unusually high block rate (potential misconfiguration)."""
        config = HIGH_BLOCK_RATE_CONFIG
        is_high = metrics.blocked_rate > config.threshold

        return self._check_with_grace_period(
            config=config,
            is_violated=is_high,
            message=f"Node {metrics.node_id} blocking {metrics.blocked_rate:.1f}% of requests (threshold: {config.threshold}%)",
            node_id=metrics.node_id,
        )

    def _check_with_grace_period(
        self,
        config: InvariantConfig,
        is_violated: bool,
        message: str,
        node_id: str | None = None,
    ) -> InvariantViolation | None:
        """Check if violation should be reported, respecting grace period."""
        key = f"{config.name}:{node_id}" if node_id else config.name
        now = datetime.now()

        if not is_violated:
            self._first_seen.pop(key, None)
            return None

        if key not in self._first_seen:
            self._first_seen[key] = now

        first_seen = self._first_seen[key]

        if now - first_seen < config.grace_period:
            return None

        return InvariantViolation(
            invariant_name=config.name,
            message=message,
            first_seen=first_seen,
            last_seen=now,
            node_id=node_id,
            severity=config.severity,
        )
```

## Action Integration

### Action Execution Pattern

Actions follow the same fire-and-forget pattern as TiKV:

```python
# packages/operator-ratelimiter/src/operator_ratelimiter/client.py

@dataclass
class RateLimiterClient:
    """HTTP client for rate limiter management API."""

    http: httpx.AsyncClient

    async def get_nodes(self) -> list[RateLimiterNode]:
        """Get all rate limiter nodes."""
        response = await self.http.get("/api/v1/nodes")
        response.raise_for_status()

        data = response.json()
        return [
            RateLimiterNode(
                id=node["id"],
                address=node["address"],
                state=node["state"],
                redis_connected=node["redis_connected"],
            )
            for node in data["nodes"]
        ]

    async def reset_counter(self, key: str) -> None:
        """Reset rate limit counter for a key."""
        response = await self.http.delete(f"/api/v1/counters/{key}")
        response.raise_for_status()

    async def update_limit(
        self, key_pattern: str, max_requests: int, window_seconds: int
    ) -> None:
        """Update rate limit configuration."""
        response = await self.http.post(
            "/api/v1/limits",
            json={
                "key_pattern": key_pattern,
                "max_requests": max_requests,
                "window_seconds": window_seconds,
            },
        )
        response.raise_for_status()

    async def block_key(self, key: str, duration_seconds: int) -> None:
        """Temporarily block a key."""
        response = await self.http.post(
            f"/api/v1/blocks/{key}",
            json={"duration_seconds": duration_seconds},
        )
        response.raise_for_status()

    async def unblock_key(self, key: str) -> None:
        """Remove block from a key."""
        response = await self.http.delete(f"/api/v1/blocks/{key}")
        response.raise_for_status()

    async def drain_node(self, node_id: str) -> None:
        """Start draining a node."""
        response = await self.http.post(f"/api/v1/nodes/{node_id}/drain")
        response.raise_for_status()
```

## Docker Compose Structure

```yaml
# subjects/ratelimiter/docker-compose.yaml

services:
  # Rate Limiter Nodes (3)
  ratelimiter0:
    build:
      context: ./service
      dockerfile: Dockerfile
    container_name: ratelimiter0
    ports:
      - "8080:8080"
    environment:
      - NODE_ID=ratelimiter0
      - REDIS_URL=redis://redis:6379
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8080/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  ratelimiter1:
    build:
      context: ./service
      dockerfile: Dockerfile
    container_name: ratelimiter1
    environment:
      - NODE_ID=ratelimiter1
      - REDIS_URL=redis://redis:6379
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8080/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  ratelimiter2:
    build:
      context: ./service
      dockerfile: Dockerfile
    container_name: ratelimiter2
    environment:
      - NODE_ID=ratelimiter2
      - REDIS_URL=redis://redis:6379
      - PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8080/health"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    restart: on-failure

  # Redis (shared state)
  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: on-failure

  # Prometheus
  prometheus:
    image: prom/prometheus:latest
    container_name: ratelimiter-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=15d
    depends_on:
      ratelimiter0:
        condition: service_healthy
    restart: on-failure

  # Grafana
  grafana:
    image: grafana/grafana:latest
    container_name: ratelimiter-grafana
    ports:
      - "3000:3000"
    volumes:
      - ./config/grafana/datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml:ro
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - prometheus
    restart: on-failure

  # Load Generator
  loadgen:
    build:
      context: ./loadgen
      dockerfile: Dockerfile
    container_name: loadgen
    profiles:
      - load
    environment:
      - TARGET_URL=http://ratelimiter0:8080
      - REQUESTS_PER_SECOND=1000
    depends_on:
      ratelimiter0:
        condition: service_healthy
      ratelimiter1:
        condition: service_healthy
      ratelimiter2:
        condition: service_healthy

  # Operator Container
  operator:
    build:
      context: ../..
      dockerfile: subjects/ratelimiter/Dockerfile.operator
    container_name: ratelimiter-operator
    environment:
      - RATELIMITER_URL=http://ratelimiter0:8080
      - PROMETHEUS_URL=http://prometheus:9090
      - REDIS_URL=redis://redis:6379
    depends_on:
      ratelimiter0:
        condition: service_healthy
      prometheus:
        condition: service_started
    profiles:
      - operator
    command: ["uv", "run", "python", "-c", "print('Operator container ready')"]

volumes:
  redis-data:
  prometheus-data:
  grafana-data:
```

## Core Abstraction Changes

### Monitor Loop Generalization

The current `MonitorLoop` hardcodes `TiKVSubject`. To support multiple subjects:

```python
# operator_core/monitor/loop.py - changes needed

from typing import Protocol, runtime_checkable

@runtime_checkable
class MonitorableSubject(Protocol):
    """Minimal interface for subjects the monitor loop can check."""

    async def get_nodes(self) -> list:
        """Get cluster nodes."""
        ...


class MonitorLoop:
    def __init__(
        self,
        subject: MonitorableSubject,  # Changed from TiKVSubject
        checker: Any,  # Subject-specific checker
        db_path: Path,
        interval_seconds: float = 30.0,
    ) -> None:
        ...
```

### Violation Key Generalization

Current `make_violation_key` imports from `operator_tikv`. Should be generic:

```python
# operator_core/monitor/types.py - generalized

from dataclasses import dataclass

@dataclass
class ViolationInfo:
    """Subject-agnostic violation info for ticket creation."""
    invariant_name: str
    message: str
    first_seen: datetime
    last_seen: datetime
    resource_id: str | None = None  # Generic (store_id, node_id, etc.)
    severity: str = "warning"


def make_violation_key(violation: ViolationInfo) -> str:
    """Generate deduplication key for a violation."""
    if violation.resource_id:
        return f"{violation.invariant_name}:{violation.resource_id}"
    return violation.invariant_name
```

## Build Order

### Phase 1: Rate Limiter Service (Foundation)

Build the custom rate limiter service first since everything depends on it.

1. Create `subjects/ratelimiter/service/` directory structure
2. Implement basic rate limiting with Redis sorted sets
3. Add management API endpoints
4. Add Prometheus metrics
5. Add health check endpoint
6. Write Dockerfile
7. Test standalone with curl

### Phase 2: Docker Compose Environment

Get the infrastructure running.

1. Create `subjects/ratelimiter/docker-compose.yaml`
2. Add Redis service
3. Add 3 rate limiter nodes
4. Add Prometheus with scrape config
5. Add Grafana with dashboard
6. Test cluster startup
7. Verify metrics in Prometheus

### Phase 3: operator-ratelimiter Package Types

Define the data structures.

1. Create `packages/operator-ratelimiter/` structure
2. Define types in `types.py`
3. Define invariants in `invariants.py`
4. Add `pyproject.toml`
5. Write unit tests

### Phase 4: Client Implementation

HTTP and Redis clients.

1. Implement `RateLimiterClient` for management API
2. Implement `RedisClient` for direct Redis queries
3. Implement `PrometheusClient` for metrics
4. Write client tests with mocked responses

### Phase 5: Subject Implementation

Bring it all together.

1. Implement `RateLimiterSubject`
2. Define `SubjectConfig` (RATELIMITER_CONFIG)
3. Implement `get_action_definitions()`
4. Wire up observations to clients
5. Wire up actions to clients
6. Write integration tests

### Phase 6: Core Abstraction Updates

Make operator-core subject-agnostic.

1. Generalize `MonitorLoop` to accept any subject
2. Generalize violation key generation
3. Add `--subject` flag to CLI
4. Add subject factory/registry
5. Test with both TiKV and rate limiter

### Phase 7: Load Generator and Chaos

Test the complete system.

1. Build simple load generator (Python + httpx)
2. Add chaos injection (kill nodes, Redis disconnect)
3. Run end-to-end demo
4. Verify AI diagnosis quality

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Subject Protocol | HIGH | Directly follows existing TiKV pattern |
| Docker Compose | HIGH | Mirrors existing TiKV setup |
| Rate limiter service design | MEDIUM | Custom service, validated algorithm from research |
| Core abstraction changes | HIGH | Minimal changes needed, Protocol-based |
| Action definitions | HIGH | Follows ActionDefinition pattern exactly |
| Metrics flow | HIGH | Same Prometheus pattern as TiKV |
| Invariant structure | HIGH | Same InvariantChecker pattern |

## Sources

### Primary (HIGH confidence)
- Existing codebase: `operator-tikv/subject.py`, `operator-core/subject.py`
- Existing architecture: `.planning/research/ARCHITECTURE.md` (v2.0)
- Project context: `.planning/PROJECT.md`

### Secondary (MEDIUM confidence)
- [Redis sliding window rate limiting](https://redis.io/learn/howtos/ratelimiting)
- [Distributed rate limiter patterns](https://github.com/uppnrise/distributed-rate-limiter)
- [Python Redis rate limiters](https://github.com/nickgaya/redbucket)
