---
phase: 02-tikv-subject
plan: 01
subsystem: api
tags: [tikv, pydantic, pd-api, prometheus, response-types]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: operator-core package with workspace setup, pydantic dependency
provides:
  - operator-tikv package as workspace member
  - PDStoresResponse, PDRegionResponse types for PD API parsing
  - PrometheusQueryResponse type with string-to-float conversion
  - Package dependency on operator-core (inherits httpx, pydantic)
affects: [02-tikv-subject, 03-local-cluster]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pydantic models for external API response validation
    - Nested PD API response handling (stores.store.id pattern)
    - Prometheus string value conversion (get_single_value method)

key-files:
  created:
    - packages/operator-tikv/pyproject.toml
    - packages/operator-tikv/src/operator_tikv/__init__.py
    - packages/operator-tikv/src/operator_tikv/types.py
  modified:
    - pyproject.toml

key-decisions:
  - "Use Pydantic for API response types (external data validation)"
  - "PrometheusQueryResponse.get_single_value() handles string-to-float conversion"
  - "PD types mirror nested API structure (PDStoreItem contains PDStoreInfo and PDStoreStatus)"

patterns-established:
  - "API response types live in types.py within subject package"
  - "Helper methods on response models for common operations (get_single_value, get_vector_results)"

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 02 Plan 01: TiKV Package and Types Summary

**Pydantic response types for TiKV PD API and Prometheus HTTP API with nested structure handling and string-to-float conversion**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T20:57:53Z
- **Completed:** 2026-01-24T20:59:38Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created operator-tikv package as workspace member depending on operator-core
- Implemented PD API response types handling nested structures (PDStoresResponse, PDRegionResponse)
- Implemented Prometheus response types with string-to-float value conversion
- All types exported from package __init__.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Create operator-tikv package structure** - `0084f75` (feat)
2. **Task 2: Create TiKV response types** - `5675999` (feat)

**Plan metadata:** Pending

## Files Created/Modified

- `packages/operator-tikv/pyproject.toml` - Package configuration with operator-core dependency
- `packages/operator-tikv/src/operator_tikv/__init__.py` - Package entry point with type exports
- `packages/operator-tikv/src/operator_tikv/types.py` - Pydantic models for PD API and Prometheus responses
- `pyproject.toml` - Root workspace updated with operator-tikv dependency

## Decisions Made

- **Pydantic for API types, dataclass for internal types:** Following established pattern from 01-02, Pydantic is used for external API response validation while core internal types remain dataclasses
- **Helper methods on response models:** Added get_single_value(), get_vector_results(), get_all_values() methods to PrometheusQueryResponse for common operations
- **Nested PD type structure:** Created separate PDStoreInfo/PDStoreStatus types to mirror API nesting rather than flattening

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TiKV response types ready for PD client and Prometheus client implementations
- Package structure established for additional modules (pd_client.py, prom_client.py, invariants.py, log_parser.py)
- No blockers

---
*Phase: 02-tikv-subject*
*Completed: 2026-01-24*
