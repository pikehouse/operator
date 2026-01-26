# Pitfalls Research: Rate Limiter Subject

**Domain:** Distributed rate limiter as second operator Subject
**Researched:** 2026-01-26
**Confidence:** HIGH (verified via official Redis docs, existing operator patterns, and distributed systems research)

## Context

This research identifies pitfalls specific to:
1. Building a distributed rate limiter (intentionally simple, demo/proof-of-concept)
2. Adding a second Subject to the existing operator-core abstraction
3. Using Redis for distributed coordination
4. Proving the operator abstraction generalizes beyond TiKV

**Key constraint:** This is a demo proving the abstraction works, not a production rate limiter. Pitfalls focus on things that would break the demo or invalidate the proof.

---

## Critical Pitfalls

### 1. Subject Interface Mismatch — TiKV-Specific Types Leak Into Core

**What goes wrong:** The existing operator-core types (`Store`, `Region`, `StoreMetrics`, `ClusterMetrics`) are TiKV-specific concepts. A rate limiter has no "stores" or "regions" — it has buckets, keys, and rate configurations. Attempting to shoehorn rate limiter concepts into TiKV types produces meaningless results.

**Why this happens:**
- The current `Subject` Protocol directly uses TiKV types in method signatures
- `get_stores() -> list[Store]` assumes all subjects have "stores"
- The `MonitorLoop` hardcodes calls to `check_stores_up()`, `check_latency()`, `check_disk_space()`
- `InvariantChecker` uses TiKV-specific invariants

**Evidence from codebase:**
```python
# packages/operator-core/src/operator_core/subject.py
async def get_stores(self) -> list[Store]:  # TiKV-specific
async def get_store_metrics(self, store_id: str) -> StoreMetrics:  # TiKV-specific
```

```python
# packages/operator-core/src/operator_core/monitor/loop.py
from operator_tikv.invariants import InvariantChecker, InvariantViolation  # Direct TiKV import!
```

**Consequences:**
- Rate limiter cannot implement the current Subject Protocol
- Proves the abstraction DOESN'T generalize (opposite of demo goal)
- Requires either forcing unnatural mapping or breaking the interface

**Warning signs:**
- Methods returning empty lists or dummy values to satisfy interface
- Comments like "N/A for rate limiter"
- Invariant checks that always pass or always fail

**Prevention:**
1. **Refactor Subject Protocol before implementing rate limiter:**
   - Make observation methods generic: `get_entities() -> list[Entity]` where `Entity` is subject-specific
   - Or use a capabilities pattern: subject declares what observations it supports
   - Move TiKV-specific types to `operator_tikv.types`

2. **Create subject-specific type hierarchies:**
   ```python
   # Generic in operator-core
   @dataclass
   class SubjectEntity:
       id: str
       state: str

   # TiKV-specific
   class Store(SubjectEntity):
       address: str

   # Rate limiter-specific
   class RateLimitBucket(SubjectEntity):
       key: str
       current_count: int
       max_count: int
   ```

3. **Make InvariantChecker pluggable:**
   - Subject provides its own invariant checker
   - MonitorLoop calls `subject.get_invariant_checker()` not hardcoded TiKV checker

**Phase to address:** Phase 1 — Must refactor core abstractions before implementing rate limiter Subject

---

### 2. Race Conditions in Counter-Based Rate Limiting

**What goes wrong:** Two requests concurrently read the counter from Redis, both see value `4`, both check if `4 + 1 <= 5` (limit), both increment to `5`. Result: 6 requests allowed when limit was 5.

**Why this happens:**
- Naive pattern: `GET`, check, `INCR` as separate operations
- Redis is single-threaded but clients are not
- Network latency between operations allows interleaving

**Consequences:**
- Rate limits exceeded (demo shows wrong behavior)
- Under high concurrency, limits can be significantly exceeded
- Non-deterministic failures make demo unreliable

**Warning signs:**
- Tests pass with single client, fail with concurrent clients
- Rate limit of 10 occasionally allows 11-15 requests
- "Works most of the time" behavior

**Prevention:**
1. **Use atomic Lua scripts (strongly recommended):**
   ```lua
   -- Atomic increment and check
   local current = redis.call('INCR', KEYS[1])
   if current == 1 then
       redis.call('EXPIRE', KEYS[1], ARGV[1])
   end
   if current > tonumber(ARGV[2]) then
       return 0  -- Rejected
   end
   return 1  -- Allowed
   ```

2. **Or use Redis MULTI/EXEC transactions** (less flexible but simpler)

3. **Never use GET-check-INCR pattern** — this is the canonical race condition

4. **Test with concurrent requests:**
   ```python
   async def test_concurrent_rate_limiting():
       tasks = [check_rate_limit("key") for _ in range(100)]
       results = await asyncio.gather(*tasks)
       allowed = sum(results)
       assert allowed == 10  # Exactly the limit
   ```

**Phase to address:** Phase 2 — Core rate limiting implementation

**Sources:**
- [Redis Race Condition](https://redis.io/glossary/redis-race-condition/)
- [Fixing Race Conditions in Redis Counters](https://dev.to/silentwatcher_95/fixing-race-conditions-in-redis-counters-why-lua-scripting-is-the-key-to-atomicity-and-reliability-38a4)

---

### 3. Redis Key Expiration Race — Non-Expiring Keys

**What goes wrong:** A key gets expired between a `RENAME`/`INCR` sequence. `INCR` on non-existing key creates it without TTL. The key lives forever, rate limit counter persists across windows.

**Why this happens:**
- Redis expires keys asynchronously
- Multi-step operations have gaps where expiration can occur
- `INCR` on non-existing key sets value to 1 (without TTL)

**Evidence:** [GitHub Issue](https://github.com/Tabcorp/redis-rate-limiter/issues/1) documents this exact bug — hard to reproduce but causes "rate-limited forever" state.

**Consequences:**
- Users stuck at rate limit indefinitely
- Demo breaks when key unexpectedly persists
- Requires manual Redis intervention to fix

**Warning signs:**
- Rate limiting works initially, then user is "permanently" limited
- Redis keys without TTL accumulating over time
- Rate limits not resetting at window boundaries

**Prevention:**
1. **Always set TTL atomically with increment (Lua script):**
   ```lua
   local current = redis.call('INCR', KEYS[1])
   if current == 1 then
       redis.call('EXPIRE', KEYS[1], ARGV[1])
   end
   return current
   ```

2. **Never use RENAME in rate limiting logic** — expiration race window is too risky

3. **Add TTL verification in health checks:**
   ```python
   async def check_key_health(redis, key):
       ttl = await redis.ttl(key)
       if ttl == -1:  # Key exists without expiration
           logger.warning(f"Rate limit key {key} has no TTL!")
   ```

**Phase to address:** Phase 2 — Lua script implementation must handle TTL atomically

**Sources:**
- [Race condition that leads to non-expiring redis key](https://github.com/Tabcorp/redis-rate-limiter/issues/1)

---

### 4. MonitorLoop Coupling to TiKV — Invariant Check Hardcoding

**What goes wrong:** The `MonitorLoop` directly imports and uses `operator_tikv.invariants.InvariantChecker`. Adding a rate limiter subject means either:
- Creating a separate monitor loop (code duplication)
- Modifying MonitorLoop to handle multiple subject types (coupling)
- Breaking the abstraction entirely

**Evidence from codebase:**
```python
# packages/operator-core/src/operator_core/monitor/loop.py
from operator_tikv.invariants import InvariantChecker, InvariantViolation
from operator_tikv.subject import TiKVSubject

class MonitorLoop:
    def __init__(
        self,
        subject: TiKVSubject,  # Hardcoded to TiKV!
        checker: InvariantChecker,  # TiKV-specific checker!
        ...
    )
```

**Consequences:**
- Cannot reuse MonitorLoop for rate limiter
- Either duplicate loop logic or create tight coupling
- Proves abstraction doesn't work (defeats demo purpose)

**Warning signs:**
- Creating `RateLimiterMonitorLoop` that copies `MonitorLoop` code
- `isinstance(subject, TiKVSubject)` checks appearing in core
- Import cycles between core and subject packages

**Prevention:**
1. **Make MonitorLoop subject-agnostic:**
   ```python
   class MonitorLoop:
       def __init__(
           self,
           subject: Subject,  # Protocol, not concrete type
           invariant_checker: InvariantCheckerProtocol,  # Generic protocol
           ...
       )
   ```

2. **Define InvariantChecker protocol in core:**
   ```python
   # operator_core/monitor/types.py
   class InvariantCheckerProtocol(Protocol):
       async def check_all(self, subject: Subject) -> list[InvariantViolation]:
           ...
   ```

3. **Each subject provides its own checker:**
   ```python
   # operator_tikv
   class TiKVInvariantChecker(InvariantCheckerProtocol):
       async def check_all(self, subject: TiKVSubject) -> list[InvariantViolation]:
           ...

   # operator_ratelimit
   class RateLimitInvariantChecker(InvariantCheckerProtocol):
       async def check_all(self, subject: RateLimitSubject) -> list[InvariantViolation]:
           ...
   ```

**Phase to address:** Phase 1 — Core refactoring before rate limiter implementation

---

## Moderate Pitfalls

### 5. Clock Skew in Distributed Time Windows

**What goes wrong:** Rate limiter uses time-based windows (e.g., "10 requests per minute"). If Redis server clock differs from application server clocks, windows don't align properly. Requests near boundaries may be incorrectly allowed or rejected.

**Why this happens:**
- Cloud VMs can have clock drift
- NTP synchronization isn't perfect (10-100ms typical)
- Redis server time may differ from client time

**Consequences:**
- Rate limits off by a few requests near window boundaries
- For demo: minor issue unless demo specifically tests boundary behavior
- Non-deterministic test failures

**Warning signs:**
- Tests pass/fail inconsistently
- Rate limit works but allows 11 requests instead of 10 occasionally
- Works locally, flaky in CI/cloud

**Prevention:**
1. **Use Redis server time, not client time:**
   ```lua
   local now = redis.call('TIME')[1]  -- Redis server timestamp
   ```

2. **For demo: accept window approximation is not exact** — Cloudflare found only 0.003% of requests affected

3. **Avoid testing exact boundary behavior** — test "approximately 10 per minute" not "exactly 10"

4. **Document as known limitation** — production systems need more sophisticated handling

**Phase to address:** Phase 2 — Design decision, document limitation

**Sources:**
- [Why you shouldn't use Redis as a rate limiter](https://medium.com/ratelimitly/why-you-shouldnt-use-redis-as-a-rate-limiter-part-1-of-2-3d4261f5b38a)

---

### 6. Sliding Window Log Memory Growth

**What goes wrong:** Sliding window using sorted sets stores timestamp for each request. High-traffic keys accumulate thousands of entries. Memory grows unbounded.

**Why this happens:**
- Each request adds: `ZADD key timestamp timestamp`
- Need to call `ZREMRANGEBYSCORE` to clean old entries
- If cleanup not done atomically, entries accumulate

**Consequences:**
- Redis memory usage grows over time
- Demo Redis instance runs out of memory
- Performance degrades as sorted sets grow

**Warning signs:**
- Redis memory increasing over demo duration
- `ZCARD` on rate limit keys shows thousands of entries
- Demo slows down over time

**Prevention:**
1. **Clean old entries in same Lua script as adding:**
   ```lua
   local now = tonumber(ARGV[1])
   local window = tonumber(ARGV[2])
   local cutoff = now - window

   -- Clean old entries first
   redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)

   -- Add new entry
   redis.call('ZADD', KEYS[1], now, now)

   -- Set expiration on key itself (belt and suspenders)
   redis.call('EXPIRE', KEYS[1], window)

   return redis.call('ZCARD', KEYS[1])
   ```

2. **For demo: use simpler fixed window** — less accurate but no memory growth

3. **Monitor memory in demo health checks**

**Phase to address:** Phase 2 — Algorithm choice affects complexity

---

### 7. Redis Connection Handling — Async Client Lifecycle

**What goes wrong:** Creating new Redis connections per request, or not properly closing connections. Connection pool exhausted, Redis refuses connections.

**Why this happens:**
- Async Redis clients need explicit lifecycle management
- Connection pools have limits
- Not awaiting cleanup properly

**Evidence from TiKV subject pattern:**
```python
# TiKVSubject receives injected httpx clients
@dataclass
class TiKVSubject:
    pd: PDClient
    prom: PrometheusClient
```

**Consequences:**
- "Max connections exceeded" errors
- Demo crashes after running for a while
- Memory leaks from unclosed connections

**Warning signs:**
- Works initially, fails after minutes
- Redis logs showing connection refused
- Python warnings about unclosed connections

**Prevention:**
1. **Follow TiKV pattern — inject Redis client:**
   ```python
   @dataclass
   class RateLimitSubject:
       redis: redis.asyncio.Redis  # Injected, lifecycle managed externally
   ```

2. **Use connection pooling:**
   ```python
   redis = redis.asyncio.Redis.from_url(
       "redis://localhost:6379",
       max_connections=10,
   )
   ```

3. **Ensure proper cleanup in context managers**

**Phase to address:** Phase 2 — Follow established injection pattern

---

### 8. Invariant Domain Mismatch — What Does "Healthy" Mean?

**What goes wrong:** TiKV invariants check "store up", "latency low", "disk space available". What are the equivalent invariants for a rate limiter? Forcing TiKV invariant patterns produces meaningless checks.

**Why this happens:**
- Rate limiter health is fundamentally different from TiKV health
- "Store down" has no equivalent — rate limiter doesn't have stores
- Must define new invariant semantics from scratch

**Possible rate limiter invariants:**
- Redis connection healthy
- No clients permanently rate-limited (stuck keys)
- Rate limit configurations loaded
- No keys without TTL (the race condition bug)
- Request latency acceptable

**Consequences:**
- Copy-paste TiKV invariants = meaningless or always-passing checks
- Demo shows invariant system but checks nothing useful
- Fails to prove abstraction generalizes

**Warning signs:**
- All invariant checks pass regardless of state
- Invariants don't detect real rate limiter problems
- Comments like "placeholder invariant"

**Prevention:**
1. **Design rate limiter invariants first:**
   - `redis_healthy`: Can connect to Redis
   - `no_stuck_keys`: No keys without TTL
   - `config_loaded`: Rate limit configs present

2. **Ensure invariants are meaningful:**
   - Should fail when something is wrong
   - Should pass when things are healthy
   - Detection within demo window

3. **Make InvariantChecker subject-specific** (see pitfall #4)

**Phase to address:** Phase 1 — Define invariants as part of Subject design

---

## Demo/Proof-of-Concept Pitfalls

### 9. Failing to Prove Generalization — Demo Tests Same Path as TiKV

**What goes wrong:** Demo uses rate limiter but exercises same code paths as TiKV demo. Doesn't prove the abstraction generalizes — just proves TiKV-shaped subject works.

**Why this happens:**
- Natural tendency to follow existing patterns
- Easier to copy TiKV demo structure
- Doesn't surface abstraction problems until too late

**What the demo should prove:**
1. A non-TiKV subject can implement the Subject Protocol
2. MonitorLoop works with any subject
3. AI diagnosis works with non-TiKV context
4. The abstraction enables adding new subjects without modifying core

**What would invalidate the proof:**
- Rate limiter subject has empty/stub methods to satisfy Protocol
- MonitorLoop required modification for rate limiter
- AI diagnosis required rate-limiter-specific prompts in core
- Significant code duplication between TiKV and rate limiter

**Warning signs:**
- `NotImplementedError` in rate limiter Subject methods
- `if isinstance(subject, RateLimitSubject)` in core code
- New core modules created specifically for rate limiter

**Prevention:**
1. **Define success criteria upfront:**
   - Rate limiter implements full Subject Protocol
   - MonitorLoop unmodified (or minimally modified)
   - AI diagnosis context gatherer works generically

2. **Refactor core BEFORE implementing rate limiter** — not after

3. **Track "generalization debt"** — modifications to core that assume rate limiter

**Phase to address:** Phase 1 — Establish success criteria before implementation

---

### 10. Over-Engineering the Rate Limiter — Production Features in Demo

**What goes wrong:** Implementing distributed consensus, exactly-once semantics, multi-region coordination, sophisticated algorithms. Demo becomes complex, obscures the abstraction proof.

**Why this happens:**
- Rate limiting is a well-studied problem with many solutions
- Natural temptation to implement "properly"
- Confusing demo goals with production goals

**What the demo needs:**
- Simple rate limiter that works
- Enough complexity to have meaningful invariants
- Clear demonstration of Subject Protocol

**What the demo does NOT need:**
- Exactly-once guarantees
- Multi-region support
- Sophisticated burst handling
- Production-grade monitoring
- High availability

**Warning signs:**
- Implementing RedLock for distributed locks
- Adding circuit breakers
- Multi-Redis coordination
- "Just one more feature" scope creep

**Prevention:**
1. **Define "done" clearly:**
   - Fixed window or simple token bucket
   - Single Redis instance
   - Basic health invariants
   - Works for demo scenarios

2. **Document what's intentionally simplified:**
   - Clock skew tolerance
   - Race condition handling (Lua script is fine)
   - Recovery scenarios

3. **Time-box implementation:** If it takes more than a day, it's too complex

**Phase to address:** All phases — Constant vigilance against scope creep

---

### 11. Redis Dependency Making Demo Fragile

**What goes wrong:** Demo requires Redis running, but Redis not part of existing docker-compose. Demo fails because Redis isn't started.

**Current docker-compose includes:**
- TiKV cluster (3 nodes)
- PD cluster (3 nodes)
- Prometheus
- Grafana
- go-ycsb load generator

**Consequences:**
- Demo instructions incomplete
- "Works on my machine" when Redis running locally
- CI fails because Redis not in compose

**Warning signs:**
- Demo README has "make sure Redis is running" step
- Tests skip if Redis unavailable
- Docker-compose doesn't include Redis

**Prevention:**
1. **Add Redis to docker-compose:**
   ```yaml
   services:
     redis:
       image: redis:7
       ports:
         - "6379:6379"
       healthcheck:
         test: ["CMD", "redis-cli", "ping"]
   ```

2. **Make Redis optional for TiKV demo** — only required for rate limiter demo

3. **Or use separate compose file:**
   - `docker-compose.yml` — TiKV demo (existing)
   - `docker-compose.ratelimit.yml` — Rate limiter demo

**Phase to address:** Phase 3 — Infrastructure setup

---

## Redis Coordination Pitfalls

### 12. Lua Script Loading and Caching

**What goes wrong:** Loading Lua script on every request. Performance degrades, unnecessary network round-trips.

**Why this happens:**
- Simple approach: `EVAL script keys args` every time
- Script is re-parsed on every call
- Network transfers script text repeatedly

**Consequences:**
- Higher latency than necessary
- Demo may appear slow
- Not demonstrating good Redis practices

**Prevention:**
1. **Use SCRIPT LOAD and EVALSHA:**
   ```python
   # On startup
   sha = await redis.script_load(LUA_SCRIPT)

   # On each request
   result = await redis.evalsha(sha, keys=[key], args=[window, limit])
   ```

2. **Handle NOSCRIPT error (script evicted):**
   ```python
   try:
       result = await redis.evalsha(sha, ...)
   except redis.exceptions.NoScriptError:
       result = await redis.eval(LUA_SCRIPT, ...)  # Re-load
   ```

3. **redis-py handles this automatically with `Script` class**

**Phase to address:** Phase 2 — Implementation detail

---

### 13. Key Naming Collisions

**What goes wrong:** Rate limiter keys collide with other Redis users. Key prefix not consistent or configurable.

**Why this happens:**
- Using simple keys like `user:123`
- Shared Redis instance with other services
- No namespace prefix

**Consequences:**
- Keys overwritten by other services
- Rate limits applied incorrectly
- Debugging confusion

**Prevention:**
1. **Use consistent prefix:**
   ```python
   KEY_PREFIX = "ratelimit:"
   key = f"{KEY_PREFIX}{client_id}:{endpoint}"
   ```

2. **Make prefix configurable** for multi-tenant scenarios

3. **Document key format** in rate limiter design

**Phase to address:** Phase 2 — Design decision

---

## Prevention Summary

### Phase 1: Core Refactoring (CRITICAL)

Before implementing rate limiter:

- [ ] Refactor Subject Protocol to be type-agnostic
- [ ] Move TiKV types from operator-core to operator-tikv
- [ ] Make MonitorLoop accept generic Subject and InvariantChecker
- [ ] Define InvariantCheckerProtocol in core
- [ ] Establish success criteria for generalization proof

### Phase 2: Rate Limiter Implementation

- [ ] Use Lua scripts for atomic operations (prevent race conditions)
- [ ] Set TTL atomically with increment (prevent non-expiring keys)
- [ ] Follow TiKV pattern for client injection
- [ ] Choose simple algorithm (fixed window or basic token bucket)
- [ ] Define meaningful invariants (redis_healthy, no_stuck_keys)
- [ ] Use SCRIPT LOAD/EVALSHA for performance

### Phase 3: Infrastructure

- [ ] Add Redis to docker-compose
- [ ] Health checks for Redis
- [ ] Key prefix configured

### Testing Checklist

- [ ] Test with concurrent requests (race condition verification)
- [ ] Test key expiration (no stuck keys)
- [ ] Test Redis connection failure handling
- [ ] Verify invariants detect actual problems
- [ ] Run full demo without TiKV-specific modifications to core

---

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Subject interface mismatch | HIGH | Direct code inspection of operator-core |
| Race conditions | HIGH | Well-documented Redis pattern, multiple sources |
| Key expiration race | HIGH | Documented GitHub issue with exact reproduction |
| MonitorLoop coupling | HIGH | Direct code inspection |
| Clock skew | MEDIUM | Real issue but minor for demo |
| Invariant domain mismatch | HIGH | Logical analysis of TiKV vs rate limiter |
| Demo scope creep | HIGH | Common pattern, known risk |

## Sources

### Primary (HIGH confidence)
- [Redis Race Condition Glossary](https://redis.io/glossary/redis-race-condition/)
- [Redis Lua Atomicity](https://redis.io/learn/develop/java/spring/rate-limiting/fixed-window/reactive-lua)
- [asyncio-redis-rate-limit Library](https://github.com/wemake-services/asyncio-redis-rate-limit)
- Operator codebase inspection (packages/operator-core, packages/operator-tikv)

### Secondary (MEDIUM confidence)
- [Building Distributed Rate Limiting System with Redis and Lua](https://www.freecodecamp.org/news/build-rate-limiting-system-using-redis-and-lua/)
- [Distributed Rate Limiting at Ably](https://ably.com/blog/distributed-rate-limiting-scale-your-platform)
- [Rate Limiter for the Real World - ByteByteGo](https://blog.bytebytego.com/p/rate-limiter-for-the-real-world)

### Tertiary (LOW confidence)
- Various Medium articles on rate limiting patterns
- Stack Overflow discussions on Redis race conditions
