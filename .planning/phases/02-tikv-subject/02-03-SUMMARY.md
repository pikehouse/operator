---
phase: 02-tikv-subject
plan: 03
subsystem: metrics
tags: [prometheus, httpx, async, tikv, metrics, observability]

# Dependency graph
requires:
  - phase: 02-01
    provides: Pydantic Prometheus response types (PrometheusQueryResponse, PrometheusData)
provides:
  - PrometheusClient for querying TiKV metrics
  - get_store_metrics aggregating QPS, latency, disk, CPU
affects: [02-05, 04-monitor-loop, 05-ai-diagnosis]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Injected httpx.AsyncClient for dependency injection"
    - "String-to-float conversion for Prometheus values"
    - "Address pattern escaping for instance label matching"

key-files:
  created:
    - packages/operator-tikv/src/operator_tikv/prom_client.py
  modified: []

key-decisions:
  - "PrometheusClient uses injected httpx.AsyncClient (consistent with PDClient pattern)"
  - "Latency converted from seconds to milliseconds in StoreMetrics"
  - "Default disk_total_bytes=1 to avoid division by zero"
  - "Raft lag hardcoded to 0 (deferred per CONTEXT.md)"

patterns-established:
  - "Query Prometheus via /api/v1/query endpoint with PromQL"
  - "Handle Prometheus string values with explicit float() conversion"

# Metrics
duration: 5min
completed: 2026-01-24
---

# Phase 02 Plan 03: Prometheus Metrics Client Summary

**PrometheusClient with TDD-driven instant_query, get_metric_value, and get_store_metrics methods using injected httpx.AsyncClient**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-24T21:02:18Z
- **Completed:** 2026-01-24T21:07:41Z
- **Tasks:** TDD RED-GREEN (1 feature, 2 commits)
- **Files created:** 1

## Accomplishments

- PrometheusClient with instant_query for raw PromQL execution
- get_metric_value with string-to-float conversion (RESEARCH.md Pitfall 2)
- get_store_metrics aggregating QPS, P99 latency, disk, CPU metrics
- Correct TiKV metric names (tikv_storage_command_total, tikv_grpc_msg_duration_seconds_bucket, etc.)
- All 11 test cases passing

## Task Commits

TDD plan with RED-GREEN cycle:

1. **RED: Failing tests** - Tests were already committed in 02-04 (f9c962f)
2. **GREEN: Implementation** - `766e46c` (feat: implement PrometheusClient)

Note: Tests existed from a prior plan but implementation was pending for this plan.

## Files Created/Modified

- `packages/operator-tikv/src/operator_tikv/prom_client.py` - PrometheusClient with 3 async methods
- `packages/operator-tikv/tests/test_prom_client.py` - 11 test cases (already tracked)
- `packages/operator-tikv/src/operator_tikv/__init__.py` - Export added (via prior commit)

## Decisions Made

1. **Address pattern escaping** - Replace colon with `.*` for flexible instance matching (`tikv-0:20160` -> `tikv-0.*20160`)
2. **Latency units** - Prometheus returns seconds, convert to milliseconds in StoreMetrics
3. **Missing metric defaults** - Use 0.0 for missing numeric metrics, 1 for disk_total_bytes (avoid div/0)
4. **Raft lag deferred** - Hardcoded to 0 per CONTEXT.md decision to focus on basic health first

## Deviations from Plan

None - plan executed exactly as written. Tests existed from a prior plan (02-04) so RED phase was already complete.

## Issues Encountered

None - straightforward TDD implementation.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PrometheusClient ready for use in TiKVSubject (02-05)
- Follows same injected httpx.AsyncClient pattern as PDClient
- All success criteria met:
  - get_store_metrics returns StoreMetrics with QPS, latency, disk, CPU
  - String-to-float conversion handles Prometheus Pitfall 2
  - Raises on HTTP errors and query failures (fail loudly per CONTEXT.md)
  - Correct TiKV metric names from RESEARCH.md

---
*Phase: 02-tikv-subject*
*Completed: 2026-01-24*
