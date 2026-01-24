# Roadmap: Operator

**Created:** 2026-01-24
**Depth:** standard
**Total phases:** 6

## Overview

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Foundation | Core abstractions and local deployment ready | CORE-01, DEPLOY-01, DEPLOY-02 | 3 |
| 2 | TiKV Subject | Operator can observe TiKV cluster state | TIKV-01, TIKV-02, TIKV-03, TIKV-04 | 4 |
| 3 | Local Cluster | Fully containerized test environment running | ENV-01, ENV-02, ENV-03, ENV-04 | 4 |
| 4 | Monitor Loop | Automated invariant checking with ticket creation | CORE-02, CORE-03 | 3 |
| 5 | AI Diagnosis | Claude analyzes tickets with structured reasoning | CORE-04, DIAG-01, DIAG-02, DIAG-03, DIAG-04 | 5 |
| 6 | Chaos Demo | End-to-end demo with fault injection | CHAOS-01 | 3 |

## Phase Details

### Phase 1: Foundation ✓

**Status:** Complete (2026-01-24)

**Goal:** Core abstractions and local deployment infrastructure are ready for subject implementation.

**Requirements:**
- CORE-01: Subject adapter interface — clean separation between core and subject implementations
- DEPLOY-01: Deployment abstraction — clean interface separating local vs. cloud deployment
- DEPLOY-02: Local deployment — Docker Compose implementation (OrbStack-compatible)

**Success Criteria:**
1. ✓ A new subject can be added by implementing the adapter interface without modifying core code
2. ✓ Local deployment spins up containers via a single command (e.g., `operator deploy up`)
3. ✓ Deployment abstraction allows swapping local for cloud without changing operator code

**Plans:** 4 plans

Plans:
- [x] 01-01-PLAN.md — Project setup with uv workspace and operator-core package
- [x] 01-02-PLAN.md — Subject adapter interface (CORE-01) with Protocol and types
- [x] 01-03-PLAN.md — Deployment abstraction (DEPLOY-01) with LocalDeployment
- [x] 01-04-PLAN.md — CLI integration (DEPLOY-02) with deploy commands

---

### Phase 2: TiKV Subject ✓

**Status:** Complete (2026-01-24)

**Goal:** Operator can observe TiKV cluster state through a complete subject implementation.

**Requirements:**
- TIKV-01: PD API client — cluster state, region info, store info
- TIKV-02: Prometheus metrics client — QPS, latency, disk, CPU, Raft lag
- TIKV-03: TiKV invariants — health, latency, replication checks
- TIKV-04: Log parser — leader elections, snapshots, slow operations

**Success Criteria:**
1. ✓ Operator retrieves cluster topology, region distribution, and store health from PD API
2. ✓ Operator queries Prometheus for real-time metrics (QPS, latency, disk usage, Raft lag)
3. ✓ TiKV invariants detect when a store is down, latency exceeds threshold, or replication is degraded
4. ✓ Log parser extracts leader election events, snapshot transfers, and slow operations from TiKV logs

**Plans:** 5 plans

Plans:
- [x] 02-01-PLAN.md — Package setup with operator-tikv and Pydantic response types
- [x] 02-02-PLAN.md — PD API client (TDD) for cluster state observation
- [x] 02-03-PLAN.md — Prometheus metrics client (TDD) for performance metrics
- [x] 02-04-PLAN.md — Log parser (TDD) for leadership change extraction
- [x] 02-05-PLAN.md — TiKV invariants and TiKVSubject implementation

---

### Phase 3: Local Cluster ✓

**Status:** Complete (2026-01-24)

**Goal:** Fully containerized test environment with TiKV cluster, observability, and load generation.

**Requirements:**
- ENV-01: Docker Compose cluster — 3 TiKV nodes, 3 PD nodes, all containerized
- ENV-02: Containerized observability — Prometheus + Grafana in Docker (no host install)
- ENV-03: Containerized load generator — traffic simulation in Docker
- ENV-04: Containerized operator — the operator itself runs in Docker

**Success Criteria:**
1. ✓ `docker compose up` starts a 6-node TiKV/PD cluster with networking configured
2. ✓ Prometheus scrapes all TiKV and PD metrics; Grafana dashboards show cluster health
3. ✓ Load generator produces configurable traffic patterns against the cluster
4. ✓ Operator container connects to cluster and observability stack without host dependencies

**Plans:** 4 plans

Plans:
- [x] 03-01-PLAN.md — TiKV/PD cluster docker-compose (ENV-01)
- [x] 03-02-PLAN.md — Prometheus and Grafana observability (ENV-02)
- [x] 03-03-PLAN.md — go-ycsb load generator (ENV-03)
- [x] 03-04-PLAN.md — Operator container with verification (ENV-04)

---

### Phase 4: Monitor Loop

**Goal:** Automated invariant checking runs continuously and creates tickets on violations.

**Requirements:**
- CORE-02: Ticket database — SQLite-backed ticket tracking (created, diagnosed, resolved)
- CORE-03: Monitor loop — periodic invariant checking with configurable interval

**Success Criteria:**
1. Tickets persist in SQLite with status transitions (created -> diagnosed -> resolved)
2. Monitor loop runs at configurable intervals (e.g., every 30s) checking all registered invariants
3. When an invariant fails, a ticket is automatically created with the violation details

**Plans:** 3 plans

Plans:
- [ ] 04-01-PLAN.md — Ticket database with SQLite persistence and deduplication
- [ ] 04-02-PLAN.md — MonitorLoop daemon with signal handling and heartbeat
- [ ] 04-03-PLAN.md — CLI commands for tickets and monitor daemon

---

### Phase 5: AI Diagnosis

**Goal:** Claude analyzes tickets and produces structured reasoning about distributed system issues.

**Requirements:**
- CORE-04: Agent runner — process tickets, invoke Claude for diagnosis
- DIAG-01: Structured tickets — diagnosis with observation, root cause, context
- DIAG-02: Metric correlation — correlate across multiple metrics to identify root cause
- DIAG-03: Options-considered logging — log alternatives considered and why not chosen
- DIAG-04: Suggested actions — recommend what to do (observe-only mode)

**Success Criteria:**
1. Agent picks up undiagnosed tickets and invokes Claude with relevant context
2. Diagnosis output includes observation summary, identified root cause, and supporting evidence
3. AI correlates multiple metrics (e.g., latency + Raft lag + disk I/O) to pinpoint issues
4. Diagnosis logs show alternatives considered (e.g., "could be disk I/O, but metrics don't support")
5. Each diagnosis includes recommended action with rationale (even though v1 is observe-only)

**Estimated plans:** 4-5

---

### Phase 6: Chaos Demo

**Goal:** End-to-end demonstration showing AI diagnosis of injected faults.

**Requirements:**
- CHAOS-01: Node kill — hard failure of a store via Docker stop/kill

**Success Criteria:**
1. Operator detects store failure within configurable window after node kill
2. AI diagnosis correctly identifies "node X is down" and correlates with missing heartbeats
3. Demo script runs full cycle: healthy cluster -> inject fault -> detect -> diagnose -> explain

**Estimated plans:** 2-3

---

## Coverage Validation

- Total v1 requirements: 19
- Mapped: 19
- Unmapped: 0

All v1 requirements are mapped to exactly one phase.

| Requirement | Phase |
|-------------|-------|
| CORE-01 | Phase 1 |
| CORE-02 | Phase 4 |
| CORE-03 | Phase 4 |
| CORE-04 | Phase 5 |
| TIKV-01 | Phase 2 |
| TIKV-02 | Phase 2 |
| TIKV-03 | Phase 2 |
| TIKV-04 | Phase 2 |
| ENV-01 | Phase 3 |
| ENV-02 | Phase 3 |
| ENV-03 | Phase 3 |
| ENV-04 | Phase 3 |
| DEPLOY-01 | Phase 1 |
| DEPLOY-02 | Phase 1 |
| CHAOS-01 | Phase 6 |
| DIAG-01 | Phase 5 |
| DIAG-02 | Phase 5 |
| DIAG-03 | Phase 5 |
| DIAG-04 | Phase 5 |

---
*Roadmap created: 2026-01-24*
*Phase 2 complete: 2026-01-24*
*Phase 3 complete: 2026-01-24*
*Phase 4 planned: 2026-01-24*
