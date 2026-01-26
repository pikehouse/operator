# Requirements: Operator v2.1

**Defined:** 2026-01-26
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems — proving the abstraction works for novel, out-of-distribution systems.

## v2.1 Requirements

Requirements for Multi-Subject Support milestone. Each maps to roadmap phases.

### Core Abstraction

- [ ] **CORE-01**: Subject Protocol uses generic types, not TiKV-specific types
- [ ] **CORE-02**: MonitorLoop accepts any Subject implementing InvariantCheckerProtocol
- [ ] **CORE-03**: CLI supports --subject flag to select subject type
- [ ] **CORE-04**: TiKV-specific types moved from operator-core to operator-tikv
- [ ] **CORE-05**: TiKV subject works unchanged after refactoring

### Rate Limiter Service

- [ ] **RLSVC-01**: Rate limiter runs as 3+ containerized nodes sharing Redis state
- [ ] **RLSVC-02**: Sliding window counter implemented with atomic Lua scripts
- [ ] **RLSVC-03**: HTTP management API exposes node list, counters, and limits
- [ ] **RLSVC-04**: Prometheus metrics exported from each node
- [ ] **RLSVC-05**: Docker Compose environment with Redis, nodes, Prometheus

### operator-ratelimiter Package

- [ ] **RLPKG-01**: RateLimiterSubject implements Subject Protocol
- [ ] **RLPKG-02**: RateLimiterClient for HTTP management API calls
- [ ] **RLPKG-03**: RedisClient for direct state inspection
- [ ] **RLPKG-04**: RateLimiterInvariantChecker implements InvariantCheckerProtocol

### Monitoring & Invariants

- [ ] **MON-01**: Detect node unreachable (rate limiter node down)
- [ ] **MON-02**: Detect Redis disconnected (backend unavailable)
- [ ] **MON-03**: Detect high latency (P99 > threshold)
- [ ] **MON-04**: Detect counter drift (nodes disagree on count for same key)
- [ ] **MON-05**: Detect ghost allowing (actual allowed > configured limit)

### Actions

- [ ] **ACT-01**: Reset counter (clear rate limit state for a key)
- [ ] **ACT-02**: Update limit (change rate limit configuration)

### Demo & Validation

- [ ] **DEMO-01**: Load generator creates realistic traffic patterns
- [ ] **DEMO-02**: Chaos injection causes counter drift anomaly
- [ ] **DEMO-03**: Chaos injection causes ghost allowing anomaly
- [ ] **DEMO-04**: AI diagnosis identifies root cause without rate-limiter-specific prompts

## Future Requirements

Deferred to later milestones. Tracked but not in v2.1 roadmap.

### Extended Actions

- **ACT-03**: Block key (explicitly deny all requests for key)
- **ACT-04**: Unblock key (remove explicit block)
- **ACT-05**: Drain node (stop accepting new requests on node)

### Extended Monitoring

- **MON-06**: Detect stuck keys (counters that don't decrement due to TTL failure)
- **MON-07**: Hot key detection (single key getting disproportionate traffic)

### Multi-Subject CLI

- **CLI-01**: Subject-specific help text based on selected subject
- **CLI-02**: Subject auto-detection from environment

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Production-ready rate limiter | This is a demo to prove abstraction, not a product |
| Complex algorithms (RedLock, exactly-once) | Adds complexity without proving abstraction |
| Multi-tenancy | Complicates architecture without adding demo value |
| Persistent violation history | In-memory sufficient for proof of concept |
| DDoS detection | Different problem domain |
| Web dashboard | CLI and logs, consistent with existing approach |
| Third subject (Kafka, etc.) | Rate limiter proves abstraction; more subjects are diminishing returns |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | TBD | Pending |
| CORE-02 | TBD | Pending |
| CORE-03 | TBD | Pending |
| CORE-04 | TBD | Pending |
| CORE-05 | TBD | Pending |
| RLSVC-01 | TBD | Pending |
| RLSVC-02 | TBD | Pending |
| RLSVC-03 | TBD | Pending |
| RLSVC-04 | TBD | Pending |
| RLSVC-05 | TBD | Pending |
| RLPKG-01 | TBD | Pending |
| RLPKG-02 | TBD | Pending |
| RLPKG-03 | TBD | Pending |
| RLPKG-04 | TBD | Pending |
| MON-01 | TBD | Pending |
| MON-02 | TBD | Pending |
| MON-03 | TBD | Pending |
| MON-04 | TBD | Pending |
| MON-05 | TBD | Pending |
| ACT-01 | TBD | Pending |
| ACT-02 | TBD | Pending |
| DEMO-01 | TBD | Pending |
| DEMO-02 | TBD | Pending |
| DEMO-03 | TBD | Pending |
| DEMO-04 | TBD | Pending |

**Coverage:**
- v2.1 requirements: 25 total
- Mapped to phases: 0 (pending roadmap creation)
- Unmapped: 25

---
*Requirements defined: 2026-01-26*
*Last updated: 2026-01-26 after initial definition*
