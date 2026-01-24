# Requirements: Operator

**Defined:** 2026-01-24
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Operator Core

- [ ] **CORE-01**: Subject adapter interface — clean separation between core and subject implementations
- [ ] **CORE-02**: Ticket database — SQLite-backed ticket tracking (created, diagnosed, resolved)
- [ ] **CORE-03**: Monitor loop — periodic invariant checking with configurable interval
- [ ] **CORE-04**: Agent runner — process tickets, invoke Claude for diagnosis

### TiKV Subject

- [ ] **TIKV-01**: PD API client — cluster state, region info, store info
- [ ] **TIKV-02**: Prometheus metrics client — QPS, latency, disk, CPU, Raft lag
- [ ] **TIKV-03**: TiKV invariants — health, latency, replication checks
- [ ] **TIKV-04**: Log parser — leader elections, snapshots, slow operations

### Local Environment

- [ ] **ENV-01**: Docker Compose cluster — 3 TiKV nodes, 3 PD nodes, all containerized
- [ ] **ENV-02**: Containerized observability — Prometheus + Grafana in Docker (no host install)
- [ ] **ENV-03**: Containerized load generator — traffic simulation in Docker
- [ ] **ENV-04**: Containerized operator — the operator itself runs in Docker

### Deployment

- [ ] **DEPLOY-01**: Deployment abstraction — clean interface separating local vs. cloud deployment
- [ ] **DEPLOY-02**: Local deployment — Docker Compose implementation (OrbStack-compatible)

### Chaos Injection

- [ ] **CHAOS-01**: Node kill — hard failure of a store via Docker stop/kill

### AI Diagnosis

- [ ] **DIAG-01**: Structured tickets — diagnosis with observation, root cause, context
- [ ] **DIAG-02**: Metric correlation — correlate across multiple metrics to identify root cause
- [ ] **DIAG-03**: Options-considered logging — log alternatives considered and why not chosen
- [ ] **DIAG-04**: Suggested actions — recommend what to do (observe-only mode)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Chaos Injection

- **CHAOS-02**: Hot region — concentrate load on narrow key range
- **CHAOS-03**: Latency injection — slow disk reads
- **CHAOS-04**: Network partition — isolate node from cluster
- **CHAOS-05**: Disk pressure — fill disk with data

### Deployment

- **DEPLOY-03**: AWS deployment — ECS/EKS or EC2-based cloud deployment

### Actions

- **ACT-01**: Action execution — actually perform recommended actions (transfer_leader, split_region, etc.)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| TiKV source code in repo | We orchestrate, not fork |
| Other subjects (Kafka, Postgres, etc.) | TiKV first, extract patterns later |
| Web dashboard | CLI and logs for v1 |
| Host-installed dependencies | Everything in containers |
| Multi-subject support | Single subject (TiKV) for v1 |
| Runbook learning | Focus on diagnosis quality first |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | TBD | Pending |
| CORE-02 | TBD | Pending |
| CORE-03 | TBD | Pending |
| CORE-04 | TBD | Pending |
| TIKV-01 | TBD | Pending |
| TIKV-02 | TBD | Pending |
| TIKV-03 | TBD | Pending |
| TIKV-04 | TBD | Pending |
| ENV-01 | TBD | Pending |
| ENV-02 | TBD | Pending |
| ENV-03 | TBD | Pending |
| ENV-04 | TBD | Pending |
| DEPLOY-01 | TBD | Pending |
| DEPLOY-02 | TBD | Pending |
| CHAOS-01 | TBD | Pending |
| DIAG-01 | TBD | Pending |
| DIAG-02 | TBD | Pending |
| DIAG-03 | TBD | Pending |
| DIAG-04 | TBD | Pending |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 0
- Unmapped: 19 (pending roadmap creation)

---
*Requirements defined: 2026-01-24*
*Last updated: 2026-01-24 after initial definition*
