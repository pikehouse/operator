# Phase 19: operator-ratelimiter Package - Research

**Researched:** 2026-01-26
**Domain:** Subject Protocol implementation for distributed rate limiter monitoring
**Confidence:** HIGH

## Summary

This phase implements the operator-ratelimiter package, bringing the distributed rate limiter service (Phase 17-18) under operator monitoring using the generic Subject Protocol. The goal is to prove the abstraction works for a second, completely different subject beyond TiKV.

The implementation follows the exact patterns established by operator-tikv: a Subject class implementing SubjectProtocol.observe() and action methods, an InvariantChecker implementing InvariantCheckerProtocol.check(), HTTP clients for observation (RateLimiterClient for management API, RedisClient for direct state inspection), and a factory function for CLI integration. The invariants detect rate-limiter-specific issues: node unreachable, Redis disconnected, high latency, counter drift, and ghost allowing.

The architecture mirrors TiKV's structure: observation dict from Subject.observe() containing nodes, metrics, and counters; InvariantChecker.check() parsing the observation to detect violations; and actions (reset_counter, update_limit) following fire-and-forget semantics. This proves the MonitorLoop can run unchanged with RateLimiterSubject, validating the generic abstraction.

**Primary recommendation:** Mirror operator-tikv structure exactly - Subject with observe() returning dict, InvariantChecker with check() parsing observation, HTTP clients injected via dependency injection, factory function returning tuple. The goal is proving abstraction works, not innovation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.27+ | HTTP client for management API | Already used in operator-tikv, async native |
| redis-py | 7.x | Redis client for state inspection | Official Redis client, async support built-in |
| operator-protocols | local | Protocol definitions | Zero-dependency abstractions |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.x | Response validation | Already in operator dependencies |
| dataclasses | stdlib | Type definitions | TiKV pattern for subjects |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | aiohttp | httpx already standard in codebase |
| redis-py | redis-om | redis-py sufficient, redis-om adds ORM overhead |
| Direct parsing | Pydantic models | Use Pydantic for API responses, match TiKV pattern |

**Installation:**
```bash
# In packages/operator-ratelimiter/pyproject.toml
dependencies = [
    "operator-protocols",
    "operator-core",  # For types
    "httpx>=0.27.0",
    "redis>=7.0.0",
    "pydantic>=2.0.0",
]
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-ratelimiter/
├── pyproject.toml
├── src/
│   └── operator_ratelimiter/
│       ├── __init__.py
│       ├── subject.py           # RateLimiterSubject (observe, actions)
│       ├── invariants.py        # RateLimiterInvariantChecker
│       ├── ratelimiter_client.py  # HTTP client for management API
│       ├── redis_client.py      # Redis client for state inspection
│       ├── types.py             # Response models (Node, Counter, etc.)
│       └── factory.py           # create_ratelimiter_subject_and_checker()
└── tests/
    ├── __init__.py
    ├── test_subject.py
    ├── test_invariants.py
    └── test_protocol_compliance.py
```

### Pattern 1: Subject with Injected HTTP Clients
**What:** Subject receives pre-configured HTTP clients via dependency injection, matching TiKV pattern.
**When to use:** Always for Subject implementations - enables testing and configuration flexibility.
**Example:**
```python
# Source: operator-tikv/subject.py pattern
from dataclasses import dataclass
import httpx
import redis.asyncio as redis

@dataclass
class RateLimiterSubject:
    """
    Rate limiter implementation of Subject Protocol.

    Provides observations about rate limiter cluster state through
    management API and direct Redis inspection.
    """
    ratelimiter: RateLimiterClient  # HTTP management API
    redis: RedisClient               # Direct Redis state inspection

    async def observe(self) -> dict[str, Any]:
        """Gather current rate limiter observations."""
        # Get nodes from management API
        nodes = await self.ratelimiter.get_nodes()

        # Get counters from management API
        counters = await self.ratelimiter.get_counters()

        # Get per-node metrics (latency, etc.)
        node_metrics = {}
        for node in nodes:
            if node.state == "Up":
                try:
                    metrics = await self._get_node_metrics(node.id)
                    node_metrics[node.id] = metrics
                except Exception:
                    pass  # Skip failed metrics

        return {
            "nodes": [{"id": n.id, "address": n.address, "state": n.state} for n in nodes],
            "counters": [{"key": c.key, "count": c.count, "limit": c.limit} for c in counters],
            "node_metrics": node_metrics,
        }
```

### Pattern 2: InvariantChecker Parsing Observation Dict
**What:** Checker receives generic dict from observe(), parses to typed objects internally, matches TiKV pattern.
**When to use:** Always - observation dict is generic, checking logic is specific.
**Example:**
```python
# Source: operator-tikv/invariants.py pattern
class RateLimiterInvariantChecker:
    def __init__(self) -> None:
        self._first_seen: dict[str, datetime] = {}

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """Check rate-limiter invariants against observation."""
        violations: list[InvariantViolation] = []

        # Parse nodes from observation dict
        nodes_data = observation.get("nodes", [])
        nodes = [Node(**n) for n in nodes_data]
        violations.extend(self.check_nodes_up(nodes))

        # Parse counters and check for drift
        counters_data = observation.get("counters", [])
        violations.extend(self.check_counter_drift(counters_data))

        # Parse node metrics and check latency
        node_metrics = observation.get("node_metrics", {})
        for node_id, metrics_data in node_metrics.items():
            if violation := self.check_latency(node_id, metrics_data):
                violations.append(violation)

        return violations
```

### Pattern 3: Fire-and-Forget Action Semantics
**What:** Actions return when API accepts request, don't wait for completion (matches TiKV pattern).
**When to use:** Always for rate limiter actions - same semantics as TiKV for consistency.
**Example:**
```python
# Source: operator-tikv/subject.py action pattern
async def reset_counter(self, key: str) -> None:
    """
    Reset rate limit counter for a key.

    Fire-and-forget: returns when API accepts the request.
    Does not verify counter was actually cleared.
    """
    await self.ratelimiter.reset_counter(key)

async def update_limit(self, new_limit: int) -> None:
    """
    Update the default rate limit.

    Fire-and-forget: returns when API accepts the request.
    Does not verify all nodes picked up the new limit.
    """
    await self.ratelimiter.update_limit(new_limit)
```

### Pattern 4: Factory Function for CLI Integration
**What:** Factory function returns tuple of (subject, checker) with configured clients, avoiding direct imports in CLI.
**When to use:** Always - enables CLI to create subject/checker pairs without knowing implementation details.
**Example:**
```python
# Source: operator-tikv/factory.py pattern
import httpx
import redis.asyncio as redis

def create_ratelimiter_subject_and_checker(
    ratelimiter_url: str,
    redis_url: str,
    ratelimiter_http: httpx.AsyncClient | None = None,
    redis_client: redis.Redis | None = None,
) -> tuple[RateLimiterSubject, RateLimiterInvariantChecker]:
    """
    Create rate limiter subject and checker pair.

    Factory function for CLI integration without direct imports.
    """
    if ratelimiter_http is None:
        ratelimiter_http = httpx.AsyncClient(base_url=ratelimiter_url, timeout=10.0)
    if redis_client is None:
        redis_client = redis.from_url(redis_url)

    subject = RateLimiterSubject(
        ratelimiter=RateLimiterClient(http=ratelimiter_http),
        redis=RedisClient(redis=redis_client),
    )
    checker = RateLimiterInvariantChecker()

    return subject, checker
```

### Pattern 5: Grace Period with first_seen Tracking
**What:** Track when violations first appear, only report after grace period elapses (matches TiKV pattern).
**When to use:** For invariants that may have transient violations (high latency, counter drift).
**Example:**
```python
# Source: operator-tikv/invariants.py grace period pattern
def _check_with_grace_period(
    self,
    config: InvariantConfig,
    is_violated: bool,
    message: str,
    node_id: str | None = None,
) -> InvariantViolation | None:
    """Check if violation should be reported after grace period."""
    key = self._get_violation_key(config.name, node_id)
    now = datetime.now()

    if not is_violated:
        # Clear tracking when violation resolves
        self._first_seen.pop(key, None)
        return None

    # Track when violation was first seen
    if key not in self._first_seen:
        self._first_seen[key] = now

    first_seen = self._first_seen[key]

    # Check if grace period has elapsed
    if now - first_seen < config.grace_period:
        return None  # Still within grace period

    return InvariantViolation(
        invariant_name=config.name,
        message=message,
        first_seen=first_seen,
        last_seen=now,
        store_id=node_id,  # reuse store_id field for node_id
        severity=config.severity,
    )
```

### Anti-Patterns to Avoid
- **Subject-specific types in protocols:** Keep operator-protocols generic (dict[str, Any], not RateLimiterNode)
- **Importing subject in core:** Use factory functions and protocol types only
- **Synchronous Redis calls:** Always use redis.asyncio for async operations
- **Blocking on action completion:** Actions are fire-and-forget, match TiKV semantics
- **Custom observation structure:** Follow TiKV pattern - dict with nodes, metrics, state

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Redis connection pooling | Manual connection management | redis.asyncio.from_url() | Handles connection pooling, reconnection automatically |
| HTTP retry logic | Manual retry wrapper | httpx.Client with timeout | Let httpx handle timeouts, fail loudly |
| Observation structure | New dict format | TiKV observation pattern | Consistency across subjects for AI diagnosis |
| Grace period logic | Per-invariant tracking | TiKVInvariantChecker pattern | Proven pattern with clear first_seen semantics |
| Action definitions | Custom schema | ActionDefinition from operator-core | Already integrated with ActionRegistry |

**Key insight:** The value is in proving the abstraction works, not inventing new patterns. Mirror TiKV implementation as closely as possible - observation dict structure, invariant checking flow, action semantics, factory pattern. This makes the MonitorLoop truly generic.

## Common Pitfalls

### Pitfall 1: Counter Drift Definition Ambiguity
**What goes wrong:** Unclear what "counter drift" means - nodes don't have independent counters, they all use Redis.
**Why it happens:** Misunderstanding rate limiter architecture - all nodes share Redis state.
**How to avoid:** Define drift as Redis counter value disagreeing with observed traffic patterns (e.g., counter shows 50 but Prometheus metrics show 100 requests counted across nodes).
**Warning signs:** Invariant never fires because nodes always agree (they use same Redis).

### Pitfall 2: Node Unreachable vs Redis Disconnected
**What goes wrong:** Conflating node health with Redis connectivity - both cause failures but need different responses.
**Why it happens:** Both manifest as service unavailability.
**How to avoid:** Check node health separately (HTTP /health endpoint) from Redis connectivity (explicit Redis ping from operator). Node down = node unreachable. Node up but can't reach Redis = Redis disconnected.
**Warning signs:** Single invariant firing for two different failure modes.

### Pitfall 3: Ghost Allowing Detection Without Traffic Data
**What goes wrong:** Can't detect "actual allowed > limit" without knowing actual request volume.
**Why it happens:** Management API shows counters, not actual allow/deny decisions.
**How to avoid:** Use Prometheus metrics (ratelimiter_requests_checked_total{result="allowed"}) to count actual allows, compare to configured limit over window. Requires correlating counter value with metric scrapes.
**Warning signs:** Invariant requires complex time-windowing logic to compare counter snapshots with metric totals.

### Pitfall 4: High Latency P99 Without Prometheus
**What goes wrong:** Management API doesn't expose latency percentiles.
**Why it happens:** Latency metrics are in Prometheus, not management API.
**How to avoid:** RateLimiterSubject needs PrometheusClient (like TiKV) to query ratelimiter_check_duration_seconds histogram for P99. This adds a third client dependency.
**Warning signs:** Can't implement latency invariant without Prometheus integration.

### Pitfall 5: Fire-and-Forget Action Verification
**What goes wrong:** Actions report success but don't verify outcome (e.g., reset_counter succeeds but counter still has value).
**Why it happens:** Trying to verify action completion contradicts fire-and-forget semantics.
**How to avoid:** Match TiKV semantics - action succeeds when API accepts request. Verification happens on next observation cycle when invariant checker sees resolved state.
**Warning signs:** Action methods doing GET after POST to verify.

### Pitfall 6: Redis Connection Leaking
**What goes wrong:** Redis connections accumulate, eventually exhausting pool.
**Why it happens:** Not properly closing async Redis clients.
**How to avoid:** Use async context managers or ensure proper cleanup. Factory function should document lifecycle management (caller owns clients).
**Warning signs:** Connection errors after operator runs for extended period.

## Code Examples

Verified patterns from existing codebase and official documentation:

### RateLimiter HTTP Client Pattern
```python
# Source: operator-tikv/pd_client.py pattern
from dataclasses import dataclass
import httpx
from pydantic import BaseModel

class NodeInfo(BaseModel):
    id: str
    address: str
    state: str

class NodesResponse(BaseModel):
    nodes: list[NodeInfo]

@dataclass
class RateLimiterClient:
    """HTTP client for rate limiter management API."""
    http: httpx.AsyncClient

    async def get_nodes(self) -> list[NodeInfo]:
        """Get all rate limiter nodes."""
        response = await self.http.get("/api/nodes")
        response.raise_for_status()
        data = NodesResponse.model_validate(response.json())
        return data.nodes

    async def reset_counter(self, key: str) -> None:
        """Reset rate limit counter for a key."""
        response = await self.http.post(f"/api/counters/{key}/reset")
        response.raise_for_status()
```

### Redis Async Client for State Inspection
```python
# Source: redis-py async documentation
import redis.asyncio as redis
from dataclasses import dataclass

@dataclass
class RedisClient:
    """Redis client for direct state inspection."""
    redis: redis.Redis

    async def ping(self) -> bool:
        """Check if Redis is reachable."""
        try:
            await self.redis.ping()
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            return False

    async def get_counter_value(self, key: str) -> int:
        """Get raw counter value from Redis."""
        prefixed_key = f"ratelimit:{key}"
        count = await self.redis.zcard(prefixed_key)
        return count
```

### Observation Dict Structure
```python
# Source: TiKV observation pattern from operator-tikv/subject.py
async def observe(self) -> dict[str, Any]:
    """
    Gather current rate limiter observations.

    Returns dict matching TiKV pattern:
    - Top-level keys: nodes, counters, node_metrics, redis_connected
    - Values are dicts/lists, not typed objects (parsed in checker)
    """
    nodes = await self.ratelimiter.get_nodes()
    counters = await self.ratelimiter.get_counters()
    redis_ok = await self.redis.ping()

    # Get per-node metrics (similar to TiKV per-store metrics)
    node_metrics: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.state == "Up":
            try:
                # Query Prometheus for node-specific latency
                latency_p99 = await self.prom.query_node_latency_p99(node.id)
                node_metrics[node.id] = {
                    "latency_p99_ms": latency_p99,
                }
            except Exception:
                pass  # Skip failed metrics

    return {
        "nodes": [{"id": n.id, "address": n.address, "state": n.state} for n in nodes],
        "counters": [{"key": c.key, "count": c.count, "limit": c.limit} for c in counters],
        "node_metrics": node_metrics,
        "redis_connected": redis_ok,
    }
```

### Invariant: Node Unreachable
```python
# Source: TiKV store_down invariant pattern
def check_nodes_up(self, nodes: list[Node]) -> list[InvariantViolation]:
    """Check that all nodes are reachable."""
    violations = []
    current_down_nodes: set[str] = set()

    for node in nodes:
        is_down = node.state != "Up"
        if is_down:
            current_down_nodes.add(node.id)

        violation = self._check_with_grace_period(
            config=NODE_DOWN_CONFIG,
            is_violated=is_down,
            message=f"Node {node.id} at {node.address} is {node.state}",
            node_id=node.id,
        )
        if violation:
            violations.append(violation)

    # Clear tracking for nodes that came back up
    keys_to_clear = [
        key for key in self._first_seen
        if key.startswith("node_down:")
        and key.split(":", 1)[1] not in current_down_nodes
    ]
    for key in keys_to_clear:
        self._first_seen.pop(key, None)

    return violations
```

### Invariant: Counter Drift
```python
# Source: Inferred from requirements MON-04
def check_counter_drift(
    self,
    counters: list[dict],
    observation: dict[str, Any],
) -> list[InvariantViolation]:
    """
    Detect counter drift - Redis counter disagrees with observed traffic.

    This checks if the counter value in Redis differs significantly from
    what Prometheus metrics indicate should be the count.
    """
    violations = []

    # This is a complex check requiring:
    # 1. Counter value from Redis (in observation)
    # 2. Sum of allowed requests from Prometheus over window
    # 3. Comparison allowing for some drift tolerance

    # For MVP: Check if counter exceeds limit (simple form of drift)
    for counter in counters:
        key = counter["key"]
        count = counter["count"]
        limit = counter["limit"]

        # Simple drift: counter exceeds limit (shouldn't happen with atomic Lua)
        is_drifted = count > limit * 1.1  # 10% tolerance

        violation = self._check_with_grace_period(
            config=COUNTER_DRIFT_CONFIG,
            is_violated=is_drifted,
            message=f"Counter {key} has {count} but limit is {limit}",
            node_id=None,  # Global invariant, not node-specific
        )
        if violation:
            violations.append(violation)

    return violations
```

### Action Definitions
```python
# Source: operator-tikv/subject.py action pattern
def get_action_definitions(self) -> list[ActionDefinition]:
    """Return definitions of all actions this subject supports."""
    return [
        ActionDefinition(
            name="reset_counter",
            description="Reset rate limit counter for a specific key",
            parameters={
                "key": ParamDef(
                    type="str",
                    description="Rate limit key to reset (e.g., 'user:123')",
                    required=True,
                ),
            },
            risk_level="low",
            requires_approval=False,
        ),
        ActionDefinition(
            name="update_limit",
            description="Update the default rate limit for all keys",
            parameters={
                "new_limit": ParamDef(
                    type="int",
                    description="New request limit per window",
                    required=True,
                ),
            },
            risk_level="medium",
            requires_approval=False,
        ),
    ]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| aioredis separate package | redis-py async built-in | 2023 (redis-py 4.2+) | Use redis.asyncio import |
| Subject-specific protocols | Generic SubjectProtocol | Phase 16 (2026-01) | All subjects use dict observation |
| Hardcoded TiKV monitoring | Multi-subject abstraction | Phase 16-19 (2026-01) | MonitorLoop works with any subject |
| Custom HTTP wrapper | httpx.AsyncClient injection | TiKV pattern | Consistent client pattern |

**Deprecated/outdated:**
- aioredis package: Merged into redis-py, use `import redis.asyncio as redis`
- TiKV-specific MonitorLoop: Now generic with SubjectProtocol

## Open Questions

Things that couldn't be fully resolved:

1. **Prometheus dependency for latency metrics**
   - What we know: Latency is in Prometheus, not management API
   - What's unclear: Should RateLimiterSubject have PrometheusClient like TiKV?
   - Recommendation: Yes, add PrometheusClient as third injected dependency. Observation needs latency for high_latency invariant. Match TiKV pattern.

2. **Ghost allowing detection feasibility**
   - What we know: Need to compare actual allows (from metrics) with limit
   - What's unclear: Complexity of correlating time-windowed metrics with counters
   - Recommendation: Start with simple check - if counter shows allowed > limit, that's ghost allowing. Use Prometheus histogram sum to get total allowed requests, compare to limit over window.

3. **Counter drift threshold**
   - What we know: Drift means Redis counter disagrees with reality
   - What's unclear: What percentage drift is acceptable? 1%? 10%?
   - Recommendation: Use 10% threshold initially. Counter should never exceed limit (atomic Lua), but allow small drift for clock skew and race conditions. Configurable via InvariantConfig.

4. **Redis disconnected vs node Redis disconnected**
   - What we know: Redis can be unreachable globally or per-node
   - What's unclear: Should we check Redis connectivity per-node or globally?
   - Recommendation: Check globally from operator (RedisClient.ping()). If Redis is down, all nodes are affected. Per-node check would require querying each node's health status.

5. **Update limit action scope**
   - What we know: Rate limiter has default_limit configurable
   - What's unclear: Does update_limit API exist in ratelimiter-service?
   - Recommendation: Check if management API supports PUT /api/limits. If not, this action may need to be deferred or implemented as environment variable change + restart (not fire-and-forget).

## Sources

### Primary (HIGH confidence)
- Existing codebase patterns:
  - `/packages/operator-tikv/src/operator_tikv/subject.py` - Subject implementation pattern
  - `/packages/operator-tikv/src/operator_tikv/invariants.py` - InvariantChecker pattern
  - `/packages/operator-tikv/src/operator_tikv/factory.py` - Factory function pattern
  - `/packages/operator-tikv/src/operator_tikv/pd_client.py` - HTTP client pattern
  - `/packages/operator-protocols/src/operator_protocols/subject.py` - SubjectProtocol definition
  - `/packages/operator-protocols/src/operator_protocols/invariant.py` - InvariantCheckerProtocol definition
  - `/packages/operator-core/src/operator_core/monitor/loop.py` - MonitorLoop generic implementation
  - `/packages/ratelimiter-service/src/ratelimiter_service/api/management.py` - Management API endpoints
  - `/packages/ratelimiter-service/src/ratelimiter_service/limiter.py` - Rate limiter with reset_counter
  - `/packages/ratelimiter-service/src/ratelimiter_service/metrics.py` - Prometheus metrics
  - `/packages/ratelimiter-service/src/ratelimiter_service/node_registry.py` - Node discovery pattern

### Secondary (MEDIUM confidence)
- [redis-py async documentation](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - Async Redis client patterns
- [httpx AsyncClient documentation](https://www.python-httpx.org/async/) - Async HTTP client usage

### Tertiary (LOW confidence)
- Web search results on counter drift patterns - General distributed systems concepts, not specific implementation guidance

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Following established operator-tikv patterns exactly
- Architecture: HIGH - All patterns verified in existing codebase
- Pitfalls: MEDIUM - Some invariants (counter drift, ghost allowing) need design decisions

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - stable codebase patterns)
