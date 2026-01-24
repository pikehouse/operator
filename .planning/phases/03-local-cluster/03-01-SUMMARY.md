---
phase: 03-local-cluster
plan: 01
subsystem: infra
tags: [tikv, pd, docker-compose, cluster]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: subjects/tikv directory structure
provides:
  - Complete 6-node TiKV cluster definition (3 PD + 3 TiKV)
  - ARM64-compatible multi-arch images
  - Health-check based startup ordering
affects: [03-02, 03-03, 03-04, 04-monitor-loop]

# Tech tracking
tech-stack:
  added: [pingcap/pd:v8.5.5, pingcap/tikv:v8.5.5]
  patterns: [depends_on with service_healthy, curl-based healthchecks]

key-files:
  created: []
  modified: [subjects/tikv/docker-compose.yaml]

key-decisions:
  - "Use pingcap/*:v8.5.5 multi-arch images instead of -arm64 variants"
  - "Use curl for healthchecks instead of wget (better JSON/empty-body handling)"

patterns-established:
  - "Pattern: Multi-arch Docker images with pinned versions for reproducibility"
  - "Pattern: curl -sf for PD healthcheck, curl -s for TiKV (empty body response)"

# Metrics
duration: 6min
completed: 2026-01-24
---

# Phase 3 Plan 1: TiKV/PD Cluster Summary

**Production-like 6-node TiKV cluster definition with ARM64-native multi-arch images and healthcheck-based startup ordering**

## Performance

- **Duration:** 6 min
- **Started:** 2026-01-24T21:54:18Z
- **Completed:** 2026-01-24T22:00:20Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Replaced Phase 1 nginx:alpine stub with complete 6-node TiKV cluster
- 3 PD nodes with proper initial-cluster configuration for quorum
- 3 TiKV nodes with depends_on: service_healthy for startup ordering
- Verified cluster starts with all 3 stores in "Up" state
- Named volumes for data persistence across restarts

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TiKV/PD cluster docker-compose.yaml** - `e9c3cee` (feat)
2. **Task 2: Verify cluster starts and reaches healthy state** - `ccfc896` (fix)

## Files Created/Modified

- `subjects/tikv/docker-compose.yaml` - Complete 6-node cluster definition with PD/TiKV services

## Decisions Made

1. **Use pingcap/*:v8.5.5 multi-arch images instead of -arm64 variants**
   - Rationale: The -arm64 images don't have a `latest` tag (only versioned tags up to v6.0.0)
   - The standard images (pingcap/pd, pingcap/tikv) are multi-arch and support ARM64 natively
   - v8.5.5 is the latest stable version with ARM64 support

2. **Use curl for healthchecks instead of wget**
   - Rationale: PD health endpoint returns JSON, wget --spider doesn't handle it well
   - TiKV status endpoint returns empty body (200 OK), curl -sf fails on empty response
   - curl -s handles both cases correctly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ARM64 images don't have latest tag**
- **Found during:** Task 2 (Verify cluster starts)
- **Issue:** `pingcap/pd-arm64:latest` and `pingcap/tikv-arm64:latest` don't exist
- **Fix:** Changed to multi-arch `pingcap/pd:v8.5.5` and `pingcap/tikv:v8.5.5`
- **Files modified:** subjects/tikv/docker-compose.yaml
- **Verification:** Images pull successfully, cluster starts
- **Committed in:** ccfc896

**2. [Rule 1 - Bug] wget healthcheck fails on PD JSON response**
- **Found during:** Task 2 (Verify cluster starts)
- **Issue:** `wget --spider` doesn't handle JSON response, causes healthcheck failure
- **Fix:** Changed to `curl -sf` for PD healthchecks
- **Files modified:** subjects/tikv/docker-compose.yaml
- **Verification:** PD containers reach healthy state
- **Committed in:** ccfc896

**3. [Rule 1 - Bug] TiKV status endpoint returns empty body**
- **Found during:** Task 2 (Verify cluster starts)
- **Issue:** `curl -sf` fails on empty response body even with 200 status
- **Fix:** Changed to `curl -s` with CMD-SHELL for TiKV healthchecks
- **Files modified:** subjects/tikv/docker-compose.yaml
- **Verification:** All containers reach healthy state
- **Committed in:** ccfc896

---

**Total deviations:** 3 auto-fixed (all Rule 1 - Bug)
**Impact on plan:** All fixes necessary for cluster to start. Research document mentioned ARM64-specific images but standard images now support multi-arch.

## Issues Encountered

None beyond the auto-fixed deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- docker-compose.yaml ready for Prometheus/Grafana integration (Plan 03-02)
- TiKV cluster can be started with `docker compose up -d`
- PD API accessible on localhost:2379 for operator integration
- TiKV gRPC on localhost:20160, status on localhost:20180

---
*Phase: 03-local-cluster*
*Completed: 2026-01-24*
