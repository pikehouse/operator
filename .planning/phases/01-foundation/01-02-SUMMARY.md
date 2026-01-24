---
phase: 01-foundation
plan: 02
subsystem: api
tags: [protocol, dataclass, typing, subject-adapter]

# Dependency graph
requires:
  - phase: 01-01
    provides: uv workspace with operator-core package
provides:
  - Subject Protocol for TiKV/Kafka subject implementations
  - Store, Region, StoreMetrics, ClusterMetrics data types
  - Action, Observation, SLO, SubjectConfig for declarative capability registration
affects: [02-tikv-subject, 04-monitor-loop, 05-ai-diagnosis]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Protocol-based interfaces with @runtime_checkable
    - dataclass for internal data types (not Pydantic)
    - async methods for all Subject operations

key-files:
  created:
    - packages/operator-core/src/operator_core/types.py
    - packages/operator-core/src/operator_core/subject.py
    - packages/operator-core/src/operator_core/config.py
  modified:
    - packages/operator-core/src/operator_core/__init__.py

key-decisions:
  - "Use @dataclass for internal types, reserve Pydantic for API/config models"
  - "All Subject methods are async for non-blocking I/O with httpx"
  - "Subject Protocol uses @runtime_checkable for isinstance() checks"

patterns-established:
  - "Protocol pattern: Structural subtyping without inheritance requirement"
  - "Type aliases: StoreId = str, RegionId = int for semantic clarity"
  - "Config pattern: Declarative capability registration via dataclasses"

# Metrics
duration: 8min
completed: 2026-01-24
---

# Phase 1 Plan 2: Subject Adapter Interface Summary

**Protocol-based Subject interface with Store/Region data types and declarative SLO config using dataclasses**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-24T12:10:00Z
- **Completed:** 2026-01-24T12:18:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Subject Protocol defining observation and action methods for distributed system adapters
- Data types (Store, Region, StoreMetrics, ClusterMetrics) as typed dataclasses with TiKV-specific docstrings
- Declarative config system (Action, Observation, SLO, SubjectConfig) for capability registration
- All types exported from package for convenient imports

## Task Commits

Each task was committed atomically:

1. **Task 1: Create data types module** - `e7fa9b1` (feat)
2. **Task 2: Create Subject Protocol** - `8dd3c1c` (feat)
3. **Task 3: Create subject config module** - `6a7c061` (feat)
4. **Package exports update** - `1dc5ad1` (feat)

## Files Created/Modified

- `packages/operator-core/src/operator_core/types.py` - Store, Region, StoreMetrics, ClusterMetrics dataclasses with type aliases
- `packages/operator-core/src/operator_core/subject.py` - Subject Protocol with async observation/action methods
- `packages/operator-core/src/operator_core/config.py` - Action, Observation, SLO, SubjectConfig for declarative registration
- `packages/operator-core/src/operator_core/__init__.py` - Updated exports for all new types

## Decisions Made

1. **@dataclass over Pydantic for internal types** - These are internal data structures, not API models or config files. Dataclasses are simpler and don't require additional validation overhead.

2. **All Subject methods async** - Following research recommendation for non-blocking I/O with httpx. The operator core will inject async HTTP clients.

3. **@runtime_checkable decorator on Protocol** - Enables isinstance() checks at runtime for debugging and validation, while primarily relying on static type checking.

4. **Type aliases (StoreId, RegionId)** - Provides semantic meaning without runtime overhead. Makes method signatures clearer.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Subject Protocol ready for TiKV implementation in Phase 2
- Config types ready for TiKV capability declaration
- Data types ready for PD API response parsing
- All imports verified working via uv run

---
*Phase: 01-foundation*
*Completed: 2026-01-24*
