---
phase: 16-core-abstraction-refactoring
plan: 02
subsystem: core
tags: [protocols, tikv, abstraction, factory]

# Dependency graph
requires:
  - phase: 16-01
    provides: SubjectProtocol, InvariantCheckerProtocol, InvariantViolation, generic types
provides:
  - TiKVSubject implementing SubjectProtocol with observe() method
  - TiKVInvariantChecker implementing InvariantCheckerProtocol with check() method
  - Factory function create_tikv_subject_and_checker for CLI integration
affects: [16-03, 16-04, 16-05, 17, 19]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "observe() returns dict[str, Any] with stores, cluster_metrics, store_metrics"
    - "check(observation) parses dict to typed objects for validation"
    - "Factory function creates subject+checker pair for CLI"

key-files:
  created:
    - packages/operator-tikv/src/operator_tikv/factory.py
  modified:
    - packages/operator-tikv/pyproject.toml
    - packages/operator-tikv/src/operator_tikv/__init__.py
    - packages/operator-tikv/src/operator_tikv/subject.py
    - packages/operator-tikv/src/operator_tikv/invariants.py
    - packages/operator-tikv/tests/test_invariants.py
    - pyproject.toml

key-decisions:
  - "InvariantChecker renamed to TiKVInvariantChecker with backward compat alias"
  - "InvariantViolation removed from invariants.py, imported from operator_protocols"
  - "Test imports updated to use operator_protocols.types"

patterns-established:
  - "Subject.observe() returns structured dict with stores/cluster_metrics/store_metrics"
  - "InvariantChecker.check() parses observation dict to typed objects internally"
  - "Factory functions for CLI integration to avoid direct imports"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 16 Plan 02: Update operator-tikv to Use Protocols Summary

**TiKVSubject now implements SubjectProtocol with observe(), TiKVInvariantChecker implements InvariantCheckerProtocol with check(), factory function for CLI**

## Performance

- **Duration:** 4 min 7 sec
- **Started:** 2026-01-26T22:24:25Z
- **Completed:** 2026-01-26T22:28:32Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- TiKVSubject now implements SubjectProtocol with async observe() returning dict[str, Any]
- TiKVInvariantChecker implements InvariantCheckerProtocol with check(observation) method
- InvariantViolation is no longer defined in operator-tikv; imported from operator_protocols
- Factory function create_tikv_subject_and_checker() for CLI integration
- All 60 operator-tikv tests pass with updated imports

## Task Commits

Each task was committed atomically:

1. **Task 1: Update dependencies and imports** - `2599d4f` (chore)
2. **Task 2: Update TiKVSubject for SubjectProtocol** - `7493861` (feat)
3. **Task 3: Update InvariantChecker for InvariantCheckerProtocol** - `ec200c4` (feat)

## Files Created/Modified

- `packages/operator-tikv/pyproject.toml` - Added operator-protocols dependency
- `packages/operator-tikv/src/operator_tikv/__init__.py` - Updated exports, added factory
- `packages/operator-tikv/src/operator_tikv/subject.py` - Added observe() method
- `packages/operator-tikv/src/operator_tikv/invariants.py` - Renamed class, added check()
- `packages/operator-tikv/src/operator_tikv/factory.py` - New factory function
- `packages/operator-tikv/tests/test_invariants.py` - Updated imports
- `pyproject.toml` - Added operator-protocols to workspace sources

## Decisions Made

1. **Backward compatibility alias for InvariantChecker** - Kept `InvariantChecker = TiKVInvariantChecker` alias to avoid breaking existing code that imports `InvariantChecker`

2. **Test imports updated to operator_protocols.types** - Tests now import Store/StoreMetrics from operator_protocols.types instead of operator_core.types

3. **Factory function is synchronous** - `create_tikv_subject_and_checker()` does not create httpx clients itself if none provided, keeping it simple and avoiding async context management

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added operator-protocols to workspace sources**
- **Found during:** Task 1
- **Issue:** uv pip install failed with "missing entry in tool.uv.sources"
- **Fix:** Added `operator-protocols = { workspace = true }` to root pyproject.toml
- **Files modified:** pyproject.toml
- **Verification:** `uv pip install` succeeds
- **Committed in:** 2599d4f (Task 1 commit)

**2. [Rule 1 - Bug] Updated test imports to match new module structure**
- **Found during:** Task 3 verification
- **Issue:** Tests imported `InvariantChecker` which was renamed to `TiKVInvariantChecker`
- **Fix:** Updated test_invariants.py to use new imports with local alias
- **Files modified:** packages/operator-tikv/tests/test_invariants.py
- **Verification:** All 60 tests pass
- **Committed in:** ec200c4 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TiKVSubject and TiKVInvariantChecker now implement generic protocols
- Ready for 16-03 (update operator-core to use protocols instead of TiKV imports)
- Factory function available for CLI integration
- Backward compatibility maintained for existing code

---
*Phase: 16-core-abstraction-refactoring*
*Completed: 2026-01-26*
