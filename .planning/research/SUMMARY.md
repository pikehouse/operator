# Project Research Summary

**Project:** Operator v2.1 - Multi-Subject Support (Rate Limiter)
**Domain:** Distributed rate limiter as second Subject implementation
**Researched:** 2026-01-26
**Confidence:** HIGH

## Executive Summary

The v2.1 milestone adds a distributed rate limiter as a second Subject to prove the operator abstraction generalizes beyond TiKV. Research reveals this requires critical core refactoring before implementation: the existing Subject Protocol and MonitorLoop are tightly coupled to TiKV-specific types, making it impossible to implement a non-TiKV subject without breaking the abstraction or creating meaningless stub implementations.

The rate limiter itself follows a simple architecture: 3+ Python async service nodes sharing Redis state, using sliding window counters implemented via atomic Lua scripts to prevent race conditions. The service exposes HTTP APIs mirroring TiKV's PD API pattern (cluster state, metrics, action endpoints) to maintain consistency with the existing operator-tikv implementation. This intentional simplicity keeps focus on proving the abstraction works rather than building production-grade rate limiting.

Key risks center on abstraction design rather than rate limiter complexity. The MonitorLoop directly imports operator-tikv types, SubjectConfig uses TiKV-specific observation types, and invariant checking is hardcoded to TiKV patterns. Phase 1 must refactor these abstractions to be subject-agnostic before implementing the rate limiter, or the demo will prove the opposite of its goal: that the operator cannot handle novel systems.

## Key Findings

### Recommended Stack

The rate limiter adds minimal new dependencies to the existing Python ecosystem. Redis integration uses the official redis-py client (v7.1.0+) which absorbed the deprecated aioredis library, providing native asyncio support via `redis.asyncio`. The rate limiter service itself requires no web framework - it's a simple Python async service using existing operator-core dependencies (httpx, Pydantic) plus Redis for shared state coordination.

**Core technologies:**
- **redis-py (>=7.1.0)**: Async Redis client for distributed state - official library from Redis Inc., absorbed aioredis in v4.2.0, proven asyncio support
- **hiredis (>=3.1.0)**: Optional C parser for Redis responses - zero code changes, significant performance boost for high-throughput scenarios
- **redis:7.4-alpine (Docker)**: Redis server for shared state - stable version, Alpine keeps image ~30MB, prevents breaking changes from Redis 8.x

**Architecture pattern:**
- Each rate limiter node connects to shared Redis via injected client (follows operator-tikv injection pattern)
- Sliding window counter algorithm using Redis sorted sets with atomic Lua scripts
- HTTP management API for observations and actions (no FastAPI/Flask - keep it minimal)
- Prometheus metrics exported from each node

**Critical decision: No new frameworks.** The rate limiter is an internal demo service, not a REST API product. Adding FastAPI/Flask/Celery would obscure the abstraction proof. Keep complexity minimal - this proves the Subject Protocol works with different systems, not that we can build production rate limiters.

### Expected Features

Research identifies three categories of rate limiter anomalies, with behavioral anomalies being the key differentiators that showcase AI diagnostic reasoning.

**Must have (table stakes):**
- Node health monitoring (reachable/unreachable) - infrastructure problem, obvious root cause
- Redis connectivity check (connected/disconnected) - critical failure, immediate detection
- High latency detection (P99 > 10ms threshold with 30s grace period) - performance degradation warning
- Redis latency monitoring (operation P99 > 10ms) - backend health signal

These are infrastructure problems similar to TiKV's "store down" invariant. Must detect, but not particularly interesting for AI diagnosis since root causes are obvious.

**Should have (differentiators - behavioral anomalies):**
- **Counter drift detection**: Same key has different counter values across nodes - requires AI reasoning about eventual consistency, replication lag, clock skew, or race conditions
- **Ghost allowing (over-admission)**: Actual allowed requests exceed configured limit - could be fixed-window boundary burst, clock skew, race condition, or misconfiguration
- **Over-throttling**: Deny rate too high for actual request volume - stuck counter, wrong window calculation, or stale state
- **Burst boundary abuse**: 2x normal traffic in narrow window at minute boundary - classic fixed-window vulnerability pattern recognition
- **Hot key imbalance**: One key getting 10x checks vs others - potential attack pattern or misconfigured client
- **Stale counter**: Counter hasn't decremented despite time passing - TTL/EXPIRE failure, key stuck in Redis

These showcase AI's diagnostic reasoning: the system is "up" but behaving incorrectly. The AI must analyze multiple signals to identify root causes.

**Anti-features (explicitly NOT building):**
- Per-user dashboards (high cardinality, scope creep)
- Automatic limit adjustment (too complex, out of scope)
- DDoS detection (different problem domain)
- Request content analysis (not rate limiter's job)
- Multi-tenancy isolation (complicates architecture)
- Persistent violation history (in-memory sufficient)
- ML-based thresholds (too complex per CONTEXT.md)

**Key principle:** The rate limiter is a vehicle for demonstrating AI diagnosis of novel systems, not a production-grade rate limiter. Simplicity enables focus on abstraction proof.

### Architecture Approach

The rate limiter follows the established operator-tikv pattern: a separate `operator-ratelimiter` package implementing the Subject Protocol from operator-core. However, research reveals critical gaps in the current abstraction that must be addressed first.

**Current state (blocking issue):**
- `Subject` Protocol uses TiKV-specific types in signatures: `get_stores() -> list[Store]`, `get_store_metrics() -> StoreMetrics`
- `MonitorLoop` directly imports `operator_tikv.invariants.InvariantChecker` and `operator_tikv.subject.TiKVSubject`
- `operator-core` contains TiKV domain types (`Store`, `Region`, `StoreMetrics`) that are meaningless for rate limiters
- Violation key generation assumes TiKV-style resource identifiers

**Required refactoring (Phase 1):**
- Move TiKV-specific types from operator-core to operator-tikv
- Define generic `InvariantCheckerProtocol` that subjects implement
- Make `MonitorLoop` accept generic `Subject` protocol with subject-specific checker
- Generalize violation key generation to handle different resource identifier patterns
- Add CLI `--subject` flag to select subject type

**Rate limiter architecture (Phase 2+):**
```
operator-core (generic abstractions)
       |
operator-ratelimiter (implements Subject Protocol)
       |
  +----+----+--------+
  |         |        |
Client  RedisClient  PrometheusClient
  |         |        |
Rate Limiter HTTP API | Prometheus
                Redis
```

**Major components:**
1. **RateLimiterSubject** - Subject Protocol implementation with rate limiter-specific observations and actions
2. **Rate Limiter Service** - Custom Python async service with HTTP management API, Prometheus metrics, sliding window algorithm
3. **RateLimiterClient** - HTTP client for management API calls (get nodes, reset counters, update limits)
4. **RedisClient** - Direct Redis access for state inspection and hot key detection
5. **RateLimiterInvariantChecker** - Subject-specific invariant checks (redis_healthy, no_stuck_keys, high_block_rate)

**Key architectural decision:** The rate limiter service exposes HTTP APIs that mirror TiKV's PD API pattern (cluster state, node metrics, action endpoints). This maintains pattern consistency while using completely different domain semantics.

**Critical implementation detail:** Atomic Lua scripts prevent race conditions in counter operations. Never use GET-check-INCR pattern. Always set TTL atomically with increment to prevent non-expiring keys.

### Critical Pitfalls

1. **Subject Interface Mismatch (BLOCKING)** - The existing Subject Protocol uses TiKV-specific types (`Store`, `Region`, `StoreMetrics`) making it impossible to implement a rate limiter subject without meaningless stub methods. Prevention: Refactor core abstractions BEFORE implementing rate limiter. Move TiKV types to operator-tikv, make Subject methods return subject-specific types, define InvariantCheckerProtocol.

2. **MonitorLoop Hardcoding (BLOCKING)** - MonitorLoop directly imports `operator_tikv.invariants.InvariantChecker` and accepts only `TiKVSubject`, making it impossible to reuse for rate limiter without duplication or tight coupling. Prevention: Make MonitorLoop subject-agnostic by accepting generic Subject protocol and InvariantCheckerProtocol. Each subject provides its own invariant checker.

3. **Race Conditions in Counter Operations** - Naive GET-check-INCR pattern allows concurrent requests to exceed rate limits. Example: two requests read counter=4, both check 4+1<=5, both increment to 5, result is 6 allowed requests when limit was 5. Prevention: Use atomic Lua scripts for all counter operations. Test with concurrent requests to verify limits are exactly enforced.

4. **Redis Key Expiration Race** - Keys can expire between RENAME/INCR sequences. INCR on non-existing key creates it WITHOUT TTL, causing permanent rate limit. Prevention: Always set TTL atomically with increment in Lua script. Never use RENAME in rate limiting logic. Add health checks for keys without TTL.

5. **Invariant Domain Mismatch** - TiKV invariants check "store up", "disk space", "replication lag". Rate limiters need different invariants: "redis_connected", "no_stuck_keys", "reasonable_block_rate". Copy-pasting TiKV invariants produces meaningless checks. Prevention: Design rate limiter invariants first as part of Subject design. Ensure invariants detect real rate limiter problems and fail when something is actually wrong.

6. **Demo Scope Creep** - Temptation to implement production features (RedLock, exactly-once, multi-region) obscures abstraction proof. Prevention: Define "done" clearly - fixed window or simple token bucket, single Redis instance, basic health invariants. Time-box implementation. Document intentional simplifications.

## Implications for Roadmap

Research reveals that Phase 1 must focus on core refactoring before any rate limiter implementation. The current operator-core is TiKV-coupled in ways that make implementing a second subject impossible without breaking the abstraction.

### Phase 1: Core Abstraction Refactoring
**Rationale:** Current Subject Protocol and MonitorLoop are TiKV-coupled. Must refactor before implementing rate limiter or demo will prove abstraction doesn't work.

**Delivers:**
- Subject Protocol with generic observation/action patterns
- TiKV-specific types moved from operator-core to operator-tikv
- InvariantCheckerProtocol defined in operator-core
- MonitorLoop accepting generic Subject + InvariantChecker
- CLI with --subject flag for subject selection
- Violation key generation generalized

**Critical tasks:**
- Audit operator-core for TiKV assumptions
- Define InvariantCheckerProtocol interface
- Refactor MonitorLoop to use protocol instead of concrete types
- Add subject factory/registry pattern
- Verify TiKV subject still works after refactoring

**Avoids:**
- Pitfall #1: Subject interface mismatch
- Pitfall #2: MonitorLoop hardcoding
- Pitfall #5: Invariant domain mismatch

**Success criteria:** TiKV subject works with refactored core, no operator-core imports of operator-tikv types, MonitorLoop can theoretically accept any Subject implementation.

### Phase 2: Rate Limiter Service Foundation
**Rationale:** Rate limiter service must exist before operator-ratelimiter can observe/control it. Service complexity determines how interesting demo anomalies can be.

**Delivers:**
- Custom Python async rate limiter service
- Sliding window counter with atomic Lua scripts
- HTTP management API (/api/v1/nodes, /counters, /limits, /blocks)
- Prometheus metrics export
- Health check endpoint
- Dockerfile and standalone testing

**Uses:**
- redis-py 7.1.0+ for async Redis operations
- redis:7.4-alpine Docker image
- Existing httpx/Pydantic from operator-core

**Implements:**
- Atomic counter increment with TTL (single Lua script)
- Key prefix namespacing (ratelimit:*)
- SCRIPT LOAD/EVALSHA for performance
- Connection pooling for Redis client

**Avoids:**
- Pitfall #3: Race conditions (via Lua atomicity)
- Pitfall #4: Expiration race (TTL set atomically)
- Pitfall #6: Scope creep (no RedLock, no exactly-once)

**Success criteria:** Service enforces limits exactly under concurrent load, no stuck keys without TTL, latency < 5ms P99.

### Phase 3: Docker Compose Environment
**Rationale:** Integration testing requires full infrastructure. Establishes Prometheus scraping before operator integration.

**Delivers:**
- docker-compose.yaml with 3 rate limiter nodes
- Redis service with health check
- Prometheus configured to scrape all nodes
- Grafana with basic dashboard
- Load generator for testing

**Configuration:**
- Redis: appendonly=yes, maxmemory=100mb, eviction=allkeys-lru
- Health checks on all services
- Dependency ordering (Redis healthy before rate limiter starts)

**Avoids:**
- Pitfall #11: Redis dependency fragility (explicit compose dependency)

**Success criteria:** docker-compose up brings up 3 nodes + Redis + Prometheus, metrics visible in Prometheus, rate limiting works across nodes.

### Phase 4: operator-ratelimiter Package (Types & Invariants)
**Rationale:** Define data structures and invariant logic before Subject implementation.

**Delivers:**
- packages/operator-ratelimiter/ package structure
- types.py: RateLimiterNode, RateLimiterMetrics, LimitConfig, ClusterState
- invariants.py: RateLimiterInvariantChecker implementing InvariantCheckerProtocol
- InvariantConfig definitions for redis_disconnected, node_down, high_latency, high_block_rate
- pyproject.toml with dependencies
- Unit tests for types and invariant logic

**Implements:**
- Grace period support for invariants (same pattern as TiKV)
- Subject-specific violation key generation
- Meaningful invariant definitions distinct from TiKV

**Avoids:**
- Pitfall #5: Invariant domain mismatch (rate limiter-specific checks)

**Success criteria:** Invariants detect real rate limiter problems (stuck keys, Redis disconnect, high latency), tests cover grace period behavior.

### Phase 5: Client Implementations
**Rationale:** Subject observations/actions delegate to clients. Test clients independently before Subject integration.

**Delivers:**
- RateLimiterClient: HTTP client for management API
- RedisClient: Direct Redis queries for metrics/state
- PrometheusClient: Metrics queries for RateLimiterMetrics
- Client unit tests with mocked responses

**Follows:**
- operator-tikv pattern: inject httpx.AsyncClient
- Connection pooling for Redis
- Proper async lifecycle management

**Avoids:**
- Pitfall #7: Redis connection handling (follow injection pattern)

**Success criteria:** Clients handle errors gracefully, connection pooling works, integration tests with real services pass.

### Phase 6: RateLimiterSubject Implementation
**Rationale:** Bring all components together implementing Subject Protocol.

**Delivers:**
- RateLimiterSubject class with SubjectConfig
- get_action_definitions() returning ActionDefinition list
- Observations: get_nodes(), get_node_metrics(), get_cluster_state(), get_hot_keys()
- Actions: reset_counter(), update_limit(), block_key(), unblock_key(), drain_node()
- Integration tests with running rate limiter cluster

**Wires up:**
- Observations to RateLimiterClient and RedisClient
- Actions to RateLimiterClient HTTP endpoints
- Metrics to PrometheusClient queries
- Subject to generic MonitorLoop

**Success criteria:** Subject implements full protocol without stubs, MonitorLoop runs with RateLimiterSubject unmodified, invariants detect problems, actions execute successfully.

### Phase 7: End-to-End Demo & Chaos Testing
**Rationale:** Validate abstraction proof - AI can diagnose novel systems it hasn't seen before.

**Delivers:**
- Load generator creating normal traffic patterns
- Chaos injection scripts (kill node, Redis disconnect, clock skew, boundary burst)
- Demo scenarios showing behavioral anomalies
- Verification that AI diagnosis works without rate-limiter-specific prompts

**Demo scenarios:**
- Counter drift (partition node briefly, observe convergence)
- Ghost allowing (boundary burst with fixed window)
- Stuck key (PERSIST a key, observe over-throttling)

**Validates:**
- Abstraction generalization (same MonitorLoop, same AI context gathering)
- AI diagnosis quality with non-TiKV system
- Subject Protocol completeness

**Success criteria:** AI correctly diagnoses rate limiter anomalies using only generic Subject observations, no core code modified specifically for rate limiter demo.

### Phase Ordering Rationale

- **Phase 1 first (CRITICAL):** Cannot implement rate limiter until core abstractions support non-TiKV subjects. Attempting Phase 2 first leads to stub implementations or core coupling.

- **Phase 2 before Phase 4:** Service must exist to understand what metrics/invariants are possible. Types follow observable reality, not theoretical design.

- **Phase 3 parallel with Phase 4:** Infrastructure and types can develop independently once service exists.

- **Phase 5 before Phase 6:** Client logic tested independently prevents debugging Subject and clients simultaneously.

- **Phase 7 last:** Requires all components working together. Chaos testing validates full integration.

**Dependency chain:** Phase 1 (core) → Phase 2 (service) → Phase 3 (infra) + Phase 4 (types) → Phase 5 (clients) → Phase 6 (subject) → Phase 7 (demo)

**Pitfall avoidance:** This ordering ensures abstraction refactoring happens before implementation, preventing the "prove abstraction doesn't work" scenario. Each phase has clear success criteria preventing scope creep.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 1 (Core Refactoring):** Complex architectural change affecting existing TiKV functionality. Need to audit all operator-core/operator-tikv interactions, ensure backward compatibility. Recommend detailed design doc before implementation.

- **Phase 2 (Lua Scripts):** Race condition prevention is critical. Research atomic patterns thoroughly, review Redis Lua scripting best practices, validate TTL atomicity approach.

Phases with standard patterns (skip research-phase):

- **Phase 3 (Docker Compose):** Well-documented patterns, mirrors existing TiKV compose setup. Straightforward infrastructure work.

- **Phase 4 (Types):** Standard dataclass definitions following established patterns from operator-tikv.

- **Phase 5 (Clients):** HTTP client patterns established, follow operator-tikv's PDClient implementation.

- **Phase 6 (Subject):** Direct implementation of Protocol defined in Phase 1. If Phase 1 design is solid, this is mechanical.

- **Phase 7 (Demo):** Creative chaos injection, not research-heavy. May need specific Redis fault injection techniques.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | redis-py verified on PyPI, Redis 7.4 on Docker Hub, minimal new dependencies |
| Features | HIGH | Rate limiting patterns well-documented, anomaly types proven in industry |
| Architecture | HIGH | Follows existing operator-tikv pattern exactly, verified with codebase inspection |
| Pitfalls | HIGH | Core coupling identified via direct code inspection, race conditions documented in Redis resources, expiration race has GitHub issue with reproduction |

**Overall confidence:** HIGH

Research based on:
- Direct inspection of existing operator codebase (operator-core, operator-tikv)
- Official Redis documentation and PyPI package verification
- Multiple high-quality sources on distributed rate limiting
- Known patterns from existing Subject implementation

The high confidence stems from two factors:
1. Most architecture follows proven operator-tikv patterns
2. Core coupling issues identified through actual code inspection, not speculation

### Gaps to Address

**Phase 1 design complexity:** While pitfalls are clear (TiKV coupling), the exact refactoring approach needs design validation. Recommend:
- Create Protocol-based Subject interface draft before implementation
- Validate with both TiKV and theoretical rate limiter use cases
- Ensure backward compatibility with existing TiKV monitoring

**Lua script atomicity verification:** While research confirms approach, actual implementation needs careful testing:
- Test concurrent requests at scale (1000+ concurrent)
- Verify TTL always set atomically
- Test Redis failover/restart scenarios

**AI diagnosis generalization:** Unknown if existing context gathering produces useful signal for non-TiKV systems:
- Monitor diagnosis quality during Phase 7
- May need subject-specific context hints (acceptable if generic framework)
- Validate diagnosis doesn't require rate-limiter-specific prompts in core

**Clock skew impact:** Research indicates minor issue for demo but not quantified:
- Test with intentional clock skew during Phase 7
- Document acceptable variance (e.g., "approximately 10 requests, ±1")
- Decision: accept approximation vs. complex time synchronization

These gaps are expected for a research phase and can be addressed during implementation with the research as foundation.

## Sources

### Primary (HIGH confidence)
- Operator codebase inspection: `packages/operator-core/src/`, `packages/operator-tikv/src/` - Direct evidence of TiKV coupling
- [redis-py PyPI page](https://pypi.org/project/redis/) - Version 7.1.0 verification, Python 3.10+ requirement, aioredis merger
- [Redis Docker Hub](https://hub.docker.com/_/redis) - Official image verification, 7.4-alpine availability
- [Redis Rate Limiting Guide](https://redis.io/learn/howtos/ratelimiting) - Official algorithm documentation
- [Redis Race Condition Glossary](https://redis.io/glossary/redis-race-condition/) - Official documentation on atomicity
- [Redis Lua Atomicity](https://redis.io/learn/develop/java/spring/rate-limiting/fixed-window/reactive-lua) - Official Lua script patterns

### Secondary (MEDIUM confidence)
- [API7 Rate Limiting Guide](https://api7.ai/blog/rate-limiting-guide-algorithms-best-practices) - Algorithm tradeoffs, boundary burst issues
- [Hidden Complexity of Rate Limiting](https://bnacar.dev/2025/10/23/hidden-complexity-of-rate-limiting.html) - Distributed challenges, clock synchronization
- [Redis Rate Limiter Issues](https://medium.com/@umeshcapg/when-redis-cluster-says-break-up-redis-cluster-split-brain-problem-and-solution-f9637e9984ed) - Split-brain scenarios
- [GitHub: redis-rate-limiter expiration race](https://github.com/Tabcorp/redis-rate-limiter/issues/1) - Documented bug reproduction
- [Fixing Race Conditions with Lua](https://dev.to/silentwatcher_95/fixing-race-conditions-in-redis-counters-why-lua-scripting-is-the-key-to-atomicity-and-reliability-38a4) - Counter race prevention
- [Sliding Window Counter Explanation](https://medium.com/redis-with-raphael-de-lio/sliding-window-counter-rate-limiter-redis-java-1ba8901c02e5) - Algorithm details
- [redis-py async examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) - Connection pooling patterns

### Tertiary (LOW confidence - validation recommended)
- Various distributed rate limiter GitHub implementations - Pattern reference only, not production-ready
- Medium articles on rate limiting patterns - Cross-reference with official docs

---
*Research completed: 2026-01-26*
*Ready for roadmap: yes*
