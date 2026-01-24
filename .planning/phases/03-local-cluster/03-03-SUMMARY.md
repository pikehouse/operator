---
phase: 03-local-cluster
plan: 03
subsystem: infra
tags: [go-ycsb, load-testing, docker, tikv, ycsb, benchmark]

# Dependency graph
requires:
  - phase: 03-01
    provides: TiKV cluster docker-compose definition
provides:
  - go-ycsb Docker image built from source
  - YCSB workload configuration (workloada)
  - ycsb service in docker-compose with profile-based activation
  - Verified load generation against TiKV cluster
affects: [04-monitor-loop, chaos-testing, performance-testing]

# Tech tracking
tech-stack:
  added: [go-ycsb, golang-alpine-builder]
  patterns: [multi-stage-docker-build, docker-compose-profiles]

key-files:
  created:
    - subjects/tikv/Dockerfile.ycsb
    - subjects/tikv/workloads/workloada.properties
  modified:
    - subjects/tikv/docker-compose.yaml

key-decisions:
  - "Use Docker Compose profiles for ycsb - doesn't start with default 'up'"
  - "Raw TiKV mode for YCSB - simpler than txn mode for testing"
  - "Smaller workload config (10k records) - suitable for local testing"

patterns-established:
  - "Profile-based service activation: profiles: ['load'] for on-demand services"
  - "Multi-stage build: golang builder -> alpine runtime for minimal image"

# Metrics
duration: 4min
completed: 2026-01-24
---

# Phase 3 Plan 3: YCSB Load Generator Summary

**go-ycsb containerized load generator producing configurable traffic against TiKV via PD endpoints**

## Performance

- **Duration:** 4 min 30s
- **Started:** 2026-01-24T22:03:31Z
- **Completed:** 2026-01-24T22:08:01Z
- **Tasks:** 3
- **Files created:** 2
- **Files modified:** 1

## Accomplishments

- go-ycsb Docker image built from source (100MB multi-stage build)
- YCSB workload configuration with 50/50 read/update mix
- Load phase verified: 1000 records inserted at 1451 OPS
- Run phase verified: 3012 total OPS (1504 reads, 1526 updates per second)
- ycsb service integrated with TiKV cluster healthcheck dependencies

## Task Commits

1. **Task 1: Create go-ycsb Dockerfile and workload config** - `8398797` (feat)
2. **Task 2: Add ycsb service to docker-compose** - `4e6ab9f` (feat, included in 03-02 commit)
3. **Task 3: Verify load generator produces traffic** - No commit (verification only)

## Files Created/Modified

- `subjects/tikv/Dockerfile.ycsb` - Multi-stage build for go-ycsb from pingcap/go-ycsb
- `subjects/tikv/workloads/workloada.properties` - YCSB workload A config (50/50 read/update)
- `subjects/tikv/docker-compose.yaml` - Added ycsb service with profile-based activation

## Decisions Made

1. **Raw TiKV mode for YCSB** - Used `tikv.type="raw"` for simpler key-value operations without transaction overhead
2. **Profile-based activation** - ycsb service uses `profiles: ["load"]` so it doesn't start with default `docker compose up`
3. **Smaller workload for local testing** - 10k records / 100k operations vs original YCSB defaults (much larger)

## Deviations from Plan

### Task 2 Already Committed

The ycsb service addition to docker-compose.yaml was found to already be committed in `4e6ab9f` (labeled as 03-02 commit). This appears to be from a previous plan execution that included the ycsb service.

**Impact:** No additional commit needed for Task 2. The work was already done and committed.

---

**Total deviations:** 1 (pre-existing commit)
**Impact on plan:** None - work was already complete, verification successful.

## Issues Encountered

1. **Container cleanup required** - Initial cluster startup failed due to orphaned container references. Resolved by running `docker compose down -v` before fresh startup.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Load generator ready for chaos testing scenarios
- Can produce measurable traffic for operator monitoring
- Ready for Phase 4 monitor loop integration

**Usage:**
```bash
# Start cluster (without ycsb)
docker compose -f subjects/tikv/docker-compose.yaml up -d

# Load initial data
docker compose -f subjects/tikv/docker-compose.yaml run --rm ycsb load tikv \
  -P /workloads/workloada \
  -p tikv.pd="pd0:2379,pd1:2379,pd2:2379" \
  -p tikv.type="raw" \
  -p recordcount=1000

# Run workload
docker compose -f subjects/tikv/docker-compose.yaml run --rm ycsb run tikv \
  -P /workloads/workloada \
  -p tikv.pd="pd0:2379,pd1:2379,pd2:2379" \
  -p tikv.type="raw" \
  -p operationcount=10000
```

---
*Phase: 03-local-cluster*
*Completed: 2026-01-24*
