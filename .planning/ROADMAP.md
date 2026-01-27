# Roadmap: Operator

## Milestones

- [x] **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- [x] **v1.1 TUI Demo** - Phases 7-11 (shipped 2026-01-25)
- [x] **v2.0 Agent Actions** - Phases 12-15 (shipped 2026-01-26)
- [ ] **v2.1 Multi-Subject Support** - Phases 16-20 (in progress)

## Archived Milestones

<details>
<summary>v1.0 MVP (Phases 1-6) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.0-ROADMAP.md

**Summary:** 6 phases, 22 plans total. Delivered end-to-end chaos demo with fault injection, live detection, and AI diagnosis.

</details>

<details>
<summary>v1.1 TUI Demo (Phases 7-11) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.1-ROADMAP.md

**Summary:** 5 phases, 9 plans total. Rich-based live dashboard with real daemon output, cluster health visualization, and key-press driven demo chapters.

</details>

<details>
<summary>v2.0 Agent Actions (Phases 12-15) - SHIPPED 2026-01-26</summary>

Archived in milestones/v2.0-ROADMAP.md

**Summary:** 4 phases, 12 plans total. Action execution framework with safety controls, approval workflows, TiKV actions, workflow chaining, scheduled execution, and retry logic.

</details>

## v2.1 Multi-Subject Support (Rate Limiter)

**Milestone Goal:** Prove the operator abstraction generalizes beyond TiKV by implementing a second subject (custom distributed rate limiter) that the AI can diagnose without system-specific prompts.

### Phase 16: Core Abstraction Refactoring

**Goal:** Decouple operator-core from TiKV-specific types so any Subject can be monitored
**Depends on:** Phase 15 (v2.0 complete)
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05
**Success Criteria** (what must be TRUE):
  1. Subject Protocol uses generic types - no TiKV-specific types in signatures
  2. MonitorLoop accepts any Subject implementing InvariantCheckerProtocol
  3. CLI supports `--subject` flag to select between tikv and ratelimiter
  4. TiKV-specific types live in operator-tikv, not operator-core
  5. Existing TiKV subject works unchanged after refactoring (no regressions)
**Plans:** 5 plans

Plans:
- [x] 16-01-PLAN.md - Create operator-protocols package with generic protocols
- [x] 16-02-PLAN.md - Update operator-tikv to implement new protocols
- [x] 16-03-PLAN.md - Update operator-core to use protocols (remove TiKV imports)
- [x] 16-04-PLAN.md - Add --subject CLI flag and factory pattern
- [x] 16-05-PLAN.md - Protocol compliance tests

### Phase 17: Rate Limiter Service Foundation

**Goal:** Build the custom rate limiter service that will be monitored by operator-ratelimiter
**Depends on:** Phase 16
**Requirements:** RLSVC-01, RLSVC-02, RLSVC-03, RLSVC-04
**Success Criteria** (what must be TRUE):
  1. Rate limiter runs as 3+ nodes sharing Redis state via atomic Lua scripts
  2. Sliding window counter enforces limits exactly under concurrent load
  3. HTTP management API returns node list, counters, limits, and blocks
  4. Prometheus metrics exported from each node (requests, blocks, latency)
**Plans:** 4 plans (3 original + 1 gap closure)

Plans:
- [x] 17-01-PLAN.md - Package setup with config and Redis client
- [x] 17-02-PLAN.md - Sliding window rate limiter with Lua script
- [x] 17-03-PLAN.md - API endpoints, Prometheus metrics, and FastAPI app
- [x] 17-04-PLAN.md - Wire unused metrics (gap closure: latency histogram, active counters gauge)

### Phase 18: Docker Compose Environment

**Goal:** Create reproducible development environment for rate limiter cluster
**Depends on:** Phase 17
**Requirements:** RLSVC-05, DEMO-01
**Success Criteria** (what must be TRUE):
  1. `docker-compose up` brings up 3 rate limiter nodes, Redis, Prometheus
  2. Prometheus successfully scrapes all rate limiter nodes
  3. Load generator creates configurable traffic patterns against the cluster
**Plans:** 2 plans

Plans:
- [x] 18-01-PLAN.md - Docker Compose infrastructure (Dockerfile, docker-compose.yml, Prometheus)
- [x] 18-02-PLAN.md - Load generator with configurable traffic patterns

### Phase 19: operator-ratelimiter Package

**Goal:** Implement Subject Protocol for rate limiter with invariants and actions
**Depends on:** Phase 18
**Requirements:** RLPKG-01, RLPKG-02, RLPKG-03, RLPKG-04, MON-01, MON-02, MON-03, MON-04, MON-05, ACT-01, ACT-02
**Success Criteria** (what must be TRUE):
  1. RateLimiterSubject implements Subject Protocol completely (no stubs)
  2. MonitorLoop runs with RateLimiterSubject using same code path as TiKV
  3. Invariant checker detects: node unreachable, Redis disconnected, high latency, counter drift, ghost allowing
  4. Actions execute successfully: reset counter, update limit
  5. AI diagnosis receives observations and can reason about rate limiter state
**Plans:** 5 plans

Plans:
- [x] 19-01-PLAN.md - Package foundation (types, HTTP/Redis/Prom clients)
- [x] 19-02-PLAN.md - RateLimiterSubject and RateLimiterInvariantChecker
- [x] 19-03-PLAN.md - Add reset counter API endpoint to ratelimiter-service
- [x] 19-04-PLAN.md - Factory function and CLI integration
- [x] 19-05-PLAN.md - Protocol compliance and unit tests

### Phase 20: E2E Demo & Chaos

**Goal:** Validate that AI can diagnose rate limiter anomalies without system-specific prompts
**Depends on:** Phase 19
**Requirements:** DEMO-02, DEMO-03, DEMO-04
**Success Criteria** (what must be TRUE):
  1. Chaos injection causes counter drift anomaly (partition then observe)
  2. Chaos injection causes ghost allowing anomaly (boundary burst)
  3. AI correctly identifies root cause without rate-limiter-specific prompts in core
  4. Same demo patterns work for both TiKV and rate limiter subjects
**Plans:** 5 plans

Plans:
- [x] 20-01-PLAN.md - Shared demo infrastructure (Chapter, ChaosConfig, DemoRunner)
- [x] 20-02-PLAN.md - TiKV demo entry point with chapters and chaos
- [x] 20-03-PLAN.md - Rate limiter demo with counter drift and ghost allowing chaos
- [x] 20-04-PLAN.md - TUI integration and run-demo script
- [x] 20-05-PLAN.md - E2E validation (human verification)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7-11 | v1.1 | 9/9 | Complete | 2026-01-25 |
| 12-15 | v2.0 | 12/12 | Complete | 2026-01-26 |
| 16 - Core Abstraction | v2.1 | 5/5 | Complete | 2026-01-26 |
| 17 - Rate Limiter Service | v2.1 | 4/4 | Complete | 2026-01-26 |
| 18 - Docker Compose | v2.1 | 2/2 | Complete | 2026-01-26 |
| 19 - operator-ratelimiter | v2.1 | 5/5 | Complete | 2026-01-27 |
| 20 - E2E Demo | v2.1 | 5/5 | Complete | 2026-01-27 |

---
*Roadmap created: 2026-01-25*
*v1.0 archived: 2026-01-25*
*v1.1 archived: 2026-01-25*
*v2.0 archived: 2026-01-26*
*v2.1 phases added: 2026-01-26*
*Phase 16 planned: 2026-01-26*
*Phase 16 completed: 2026-01-26*
*Phase 17 planned: 2026-01-26*
*Phase 17 gap closure plan added: 2026-01-26*
*Phase 17 completed: 2026-01-26*
*Phase 18 planned: 2026-01-26*
*Phase 18 completed: 2026-01-26*
*Phase 19 planned: 2026-01-26*
*Phase 19 completed: 2026-01-27*
*Phase 20 planned: 2026-01-27*
