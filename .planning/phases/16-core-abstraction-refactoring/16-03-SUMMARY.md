---
phase: 16-core-abstraction-refactoring
plan: 03
subsystem: core
tags: [protocols, abstraction, decoupling, monitor-loop]

# Dependency graph
requires:
  - phase: 16-02
    provides: TiKVSubject/TiKVInvariantChecker implementing protocols, factory function
provides:
  - operator-core with zero TiKV imports in core paths
  - MonitorLoop accepting any SubjectProtocol and InvariantCheckerProtocol
  - Generic observe/check pattern for invariant monitoring
  - Types re-exported from operator_protocols
affects: [16-04, 16-05, 17, 19, 20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MonitorLoop uses subject.observe() and checker.check() generics"
    - "Types re-exported from operator_protocols for backward compatibility"
    - "Demo module kept TiKV-specific with TODO for future generalization"

key-files:
  created: []
  modified:
    - packages/operator-core/pyproject.toml
    - packages/operator-core/src/operator_core/types.py
    - packages/operator-core/src/operator_core/__init__.py
    - packages/operator-core/src/operator_core/monitor/loop.py
    - packages/operator-core/src/operator_core/monitor/types.py
    - packages/operator-core/src/operator_core/db/tickets.py
    - packages/operator-core/src/operator_core/agent/runner.py
    - packages/operator-core/src/operator_core/agent/context.py
    - packages/operator-core/src/operator_core/demo/chaos.py

key-decisions:
  - "Keep Region/RegionId locally in types.py with deprecation note"
  - "Demo module stays TiKV-specific (not core functionality)"
  - "subject_factory.py uses lazy imports for CLI integration"

patterns-established:
  - "observe/check pattern: subject.observe() -> checker.check(observation) -> violations"
  - "Type re-exports from protocols for backward compatibility"
  - "Lazy imports in factory for subject selection"

# Metrics
duration: 7min
completed: 2026-01-26
---

# Phase 16 Plan 03: Remove TiKV Imports from operator-core Summary

**operator-core now has zero TiKV imports in core paths, using SubjectProtocol and InvariantCheckerProtocol throughout**

## Performance

- **Duration:** 7 min
- **Started:** 2026-01-26T22:30:00Z
- **Completed:** 2026-01-26T22:37:23Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- MonitorLoop now accepts any SubjectProtocol and InvariantCheckerProtocol
- Simplified _check_cycle to use generic observe/check pattern
- Types re-exported from operator_protocols (Store, StoreMetrics, ClusterMetrics, StoreId)
- InvariantViolation imported from operator_protocols in all core modules
- Demo module documented as intentional TiKV-specific exception

## Task Commits

Each task was committed atomically:

1. **Task 1: Update dependencies and types** - `e16f365` (chore)
2. **Task 2: Update MonitorLoop to use protocols** - `01aeab9` (feat)
3. **Task 3: Update remaining files and document exceptions** - `02ff0ab` (chore)

## Files Created/Modified

- `packages/operator-core/pyproject.toml` - Added operator-protocols dependency
- `packages/operator-core/src/operator_core/types.py` - Re-export from protocols, keep Region/RegionId with deprecation
- `packages/operator-core/src/operator_core/__init__.py` - Add InvariantViolation re-export
- `packages/operator-core/src/operator_core/monitor/loop.py` - Use SubjectProtocol/InvariantCheckerProtocol, simplify _check_cycle
- `packages/operator-core/src/operator_core/monitor/types.py` - Import InvariantViolation from protocols
- `packages/operator-core/src/operator_core/db/tickets.py` - Import InvariantViolation from protocols
- `packages/operator-core/src/operator_core/agent/runner.py` - Use SubjectProtocol type
- `packages/operator-core/src/operator_core/agent/context.py` - Use SubjectProtocol type
- `packages/operator-core/src/operator_core/demo/chaos.py` - Add NOTE/TODO for TiKV-specific demo

## Decisions Made

1. **Keep Region/RegionId locally** - These are TiKV-specific types kept in operator_core.types for backward compatibility with deprecation notes pointing to operator_tikv

2. **Demo module stays TiKV-specific** - The demo/chaos.py module is intentionally TiKV-specific as it's demo functionality, not core. Added TODO for potential future generalization.

3. **subject_factory.py uses lazy imports** - The CLI integration factory (created in 16-04) uses lazy imports inside the function, so operator-core doesn't have a hard dependency on operator-tikv at module load time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Files auto-updated by linter**
- **Found during:** Task 3
- **Issue:** tickets.py, runner.py, context.py showed as modified but had no diff
- **Fix:** These files were auto-updated by the linter during earlier edits, already committed in previous commits
- **Files affected:** db/tickets.py, agent/runner.py, agent/context.py
- **Verification:** All imports correct, no TiKV imports
- **Impact:** No additional commit needed, changes were captured organically

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** Linter auto-applied some changes during edits. All goals achieved.

## Issues Encountered

- Discovered 16-04 commits were interleaved during execution (subject_factory.py, CLI updates). This was expected as 16-04 work was happening in parallel. The 16-03 commits are correctly identified and separate.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- operator-core is now subject-agnostic
- MonitorLoop works with any SubjectProtocol/InvariantCheckerProtocol
- Ready for 16-04 (CLI subject selection) - mostly complete already
- Ready for 16-05 (integration testing)
- Foundation ready for Phase 17+ (rate limiter subject)

---
*Phase: 16-core-abstraction-refactoring*
*Completed: 2026-01-26*
