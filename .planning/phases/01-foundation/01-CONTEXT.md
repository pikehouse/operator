# Phase 1: Foundation - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Core abstractions (subject adapter interface, deployment abstraction) and local Docker Compose implementation. This phase establishes the patterns that TiKV and future subjects will follow.

</domain>

<decisions>
## Implementation Decisions

### Subject Adapter Contract

**API Surface (minimal for v1):**
```python
# Actions
transfer_leader(region_id, to_store_id)
split_region(region_id)
set_leader_schedule_limit(n)
set_replica_schedule_limit(n)
drain_store(store_id)

# Observations
get_stores() -> list[Store]
get_hot_write_regions() -> list[Region]
get_store_metrics(store_id) -> StoreMetrics
get_cluster_metrics() -> ClusterMetrics

# Configs
set_low_space_threshold(percent)
set_leader_schedule_limit(n)
set_region_schedule_limit(n)
```

**Registration pattern:** Declarative Python config defining actions, observations, and SLOs:
```python
# subjects/tikv/config.py
from operator import Action, Observation, SLO

actions = [
    Action("transfer_leader", args=["region_id", "to_store_id"]),
    Action("split_region", args=["region_id"]),
    # ...
]

slos = [
    SLO("write_latency_p99", target_ms=100),
    SLO("under_replicated_regions", target=0, grace_period_s=600),
]
```

**Implementation:** Class-based — `class TiKVSubject(Subject)` with methods matching declared actions/observations

**Connection management:** Core injects clients (HTTP, Prometheus) — subject doesn't create its own

### Deployment Interface

**CLI pattern:** Subcommands — `operator deploy local up`, `operator deploy local down`

**Local vs cloud:** Explicit subcommand — `operator deploy local ...` vs `operator deploy aws ...`

**Output:** Progress + endpoints — show startup progress, then print service URLs (Grafana, PD, Prometheus)

**Operator included:** `deploy up` starts cluster + operator together

**Health checks:** Block until healthy before returning

**Configuration:** Config file — `deploy/local.yaml` (or per-subject) defines topology

**Subcommands:**
- `up` — start everything
- `down` — stop everything
- `status` — show running containers and health
- `logs` — tail logs from all or specific services
- `restart` — restart specific service without full teardown

**Working directory:** Project root only — no path discovery magic

### Project Structure

**Organization:** Monorepo with packages — `packages/` directory with separate packages

**Package naming:** Claude's discretion

**Docker files:** Per-subject — `subjects/tikv/docker-compose.yaml` (subject owns its infra)

**Shared code:** Explicit common package — `packages/common/` for shared types and utilities

### Docker Networking

**Container discovery:** Docker DNS — service names as hostnames (tikv-1, pd-1, prometheus)

**Exposed ports:** Grafana, Prometheus, PD API — accessible from host for debugging

**Data persistence:** Ephemeral — fresh cluster each time (simpler for testing)

**Docker socket:** No — operator uses APIs only, separate tool for chaos/container control

### Claude's Discretion

- Package naming convention
- Exact health check implementation
- Progress bar/spinner design
- Internal module organization within packages

</decisions>

<specifics>
## Specific Ideas

- API surface deliberately minimal — just enough for hot-region and node-failure scenarios
- "Expand later once the basic loop works"
- SLO-driven observation model — subject config defines key metrics and thresholds
- Inspired by harness-demo patterns but adapted for distributed systems

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-01-24*
