---
phase: 16-core-abstraction-refactoring
plan: 04
subsystem: cli
tags: [cli, factory-pattern, subject-selection, typer]

# Dependency graph
requires:
  - phase: 16-02
    provides: Factory function create_tikv_subject_and_checker
provides:
  - CLI --subject flag for monitor and agent commands
  - Subject factory module with lazy imports
  - Helpful error messages for unknown subjects
affects: [16-05, 17, 19, 20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Factory pattern for CLI subject selection with lazy imports"
    - "--subject flag required (no default) for explicit subject selection"
    - "ValueError for unknown subjects with available subjects list"

key-files:
  created:
    - packages/operator-core/src/operator_core/cli/subject_factory.py
  modified:
    - packages/operator-core/src/operator_core/cli/monitor.py
    - packages/operator-core/src/operator_core/cli/agent.py
    - packages/operator-core/src/operator_core/monitor/types.py
    - packages/operator-core/src/operator_core/db/tickets.py
    - packages/operator-core/src/operator_core/agent/runner.py
    - packages/operator-core/src/operator_core/agent/context.py

key-decisions:
  - "--subject flag is required (no default) per CONTEXT.md"
  - "Factory returns tuple of (subject, checker) for convenience"
  - "Lazy imports in factory prevent loading unused subject packages"

patterns-established:
  - "CLI uses factory pattern for subject creation"
  - "Subject-specific CLI options (--pd, --prometheus) passed through factory kwargs"
  - "ValueError from factory shown as user-friendly error message"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 16 Plan 04: CLI Subject Selection Summary

**Added --subject CLI flag to monitor and agent commands with factory pattern for subject creation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-26T22:32:20Z
- **Completed:** 2026-01-26T22:36:18Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Created subject_factory.py module with create_subject() factory function
- Added required --subject flag to monitor run command
- Added required --subject flag to agent start and diagnose commands
- Removed all direct TiKV imports from CLI files (except lazy import in factory)
- Unknown subject shows helpful error: "Unknown subject 'X'. Available subjects: tikv"

## Task Commits

Each task was committed atomically:

1. **Task 1: Create subject factory module** - `cb66345` (feat)
2. **Task 2: Update monitor CLI with --subject flag** - `2ffc5c7` (feat)
3. **Task 3: Update agent CLI with --subject flag** - `8383010` (feat)

**Plan metadata:** (pending)

## Files Created/Modified

- `packages/operator-core/src/operator_core/cli/subject_factory.py` - Factory function for creating subject/checker pairs
- `packages/operator-core/src/operator_core/cli/monitor.py` - Added --subject flag, uses factory
- `packages/operator-core/src/operator_core/cli/agent.py` - Added --subject flag, uses factory
- `packages/operator-core/src/operator_core/monitor/types.py` - Fixed import to use operator_protocols
- `packages/operator-core/src/operator_core/db/tickets.py` - Fixed import to use operator_protocols
- `packages/operator-core/src/operator_core/agent/runner.py` - Updated to use SubjectProtocol
- `packages/operator-core/src/operator_core/agent/context.py` - Updated to use SubjectProtocol

## Decisions Made

1. **--subject flag is required (no default)** - Per CONTEXT.md, explicit subject selection prevents accidental usage with wrong subject

2. **Factory returns tuple (subject, checker)** - Convenience pattern since CLI commands typically need both

3. **Lazy imports in factory** - Prevents loading operator-tikv unless --subject tikv is specified

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed circular import by updating TiKV imports**
- **Found during:** Task 2 verification
- **Issue:** Circular import between operator-core and operator-tikv prevented CLI import
- **Fix:** Updated monitor/types.py, db/tickets.py, agent/runner.py, agent/context.py to import from operator_protocols instead of operator_tikv
- **Files modified:** monitor/types.py, db/tickets.py, agent/runner.py, agent/context.py
- **Verification:** CLI imports work correctly
- **Committed in:** 2ffc5c7 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Blocking fix was necessary to complete CLI updates. This work overlaps with 16-03 scope but was required to unblock 16-04.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CLI now supports --subject flag for monitor and agent commands
- Factory pattern enables adding new subjects by extending AVAILABLE_SUBJECTS and adding elif clause
- Ready for 16-05 (validation and testing)
- TiKV works via `--subject tikv`

---
*Phase: 16-core-abstraction-refactoring*
*Completed: 2026-01-26*
