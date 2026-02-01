# Requirements: Operator v3.3

**Defined:** 2026-02-01
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems — and autonomous action without predefined playbooks.

## v3.3 Requirements

Requirements for Extended TiKV Chaos milestone. Adds 3 new resource pressure chaos types with host isolation guarantees.

### Chaos Injection

- [ ] **CHAOS-01**: cpu_pressure chaos type using stress-ng --cpu stressor
- [ ] **CHAOS-02**: memory_pressure chaos type using stress-ng --vm stressor
- [ ] **CHAOS-03**: io_latency chaos type using stress-ng --io stressor
- [ ] **CHAOS-04**: PID-based cleanup with verification (pkill + check process gone)
- [ ] **CHAOS-05**: Cleanup handles container restarts gracefully (detect restart, skip cleanup)

### Host Isolation

- [ ] **ISO-01**: TiKV containers have CPU limits in docker-compose.yaml
- [ ] **ISO-02**: TiKV containers have memory limits in docker-compose.yaml
- [ ] **ISO-03**: I/O chaos writes to container-internal paths, not host mounts
- [ ] **ISO-04**: Existing disk_pressure verified to use tmpfs only

### Integration

- [ ] **INT-01**: get_chaos_types() returns all 7 chaos types (4 existing + 3 new)
- [ ] **INT-02**: inject_chaos() dispatches to new chaos functions
- [ ] **INT-03**: cleanup_chaos() dispatches to new cleanup functions
- [ ] **INT-04**: Campaign YAML config supports new chaos types

### Infrastructure

- [ ] **INFRA-01**: stress-ng installed in Dockerfile.tikv-chaos

## Future Requirements

Deferred to later milestones.

### Advanced Chaos Types

- **CHAOS-06**: clock_skew chaos type using libfaketime for TSO disruption
- **CHAOS-07**: write_stall chaos type via RocksDB config manipulation

### Production Features

- **PROD-01**: Cloud API actions (AWS/GCP/Azure)
- **PROD-02**: Production approval layer

## Out of Scope

Explicitly excluded from v3.3.

| Feature | Reason |
|---------|--------|
| Block device latency injection (dm-delay) | Requires privileged containers, complex setup |
| clock_skew chaos | Hard difficulty, medium realism, defer to future |
| write_stall chaos | Hard difficulty, requires RocksDB config changes |
| Rate limiter chaos types | Focus on TiKV for this milestone |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CHAOS-01 | TBD | Pending |
| CHAOS-02 | TBD | Pending |
| CHAOS-03 | TBD | Pending |
| CHAOS-04 | TBD | Pending |
| CHAOS-05 | TBD | Pending |
| ISO-01 | TBD | Pending |
| ISO-02 | TBD | Pending |
| ISO-03 | TBD | Pending |
| ISO-04 | TBD | Pending |
| INT-01 | TBD | Pending |
| INT-02 | TBD | Pending |
| INT-03 | TBD | Pending |
| INT-04 | TBD | Pending |
| INFRA-01 | TBD | Pending |

**Coverage:**
- v3.3 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14 (pending roadmap creation)

---
*Requirements defined: 2026-02-01*
*Last updated: 2026-02-01 after initial definition*
