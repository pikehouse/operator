---
phase: 16-core-abstraction-refactoring
plan: 01
subsystem: core
tags: [protocols, typing, dataclasses, abstraction]

# Dependency graph
requires:
  - phase: none
    provides: first package in v2.1 abstraction refactoring
provides:
  - SubjectProtocol for observable systems
  - InvariantCheckerProtocol for health checking
  - InvariantViolation dataclass for violation tracking
  - Generic Store, StoreMetrics, ClusterMetrics types
affects: [16-02, 16-03, 16-04, 16-05, 17, 19]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "@runtime_checkable Protocol for structural typing"
    - "dict[str, Any] for flexible observation schema"
    - "Zero-dependency protocol package"

key-files:
  created:
    - packages/operator-protocols/pyproject.toml
    - packages/operator-protocols/src/operator_protocols/__init__.py
    - packages/operator-protocols/src/operator_protocols/subject.py
    - packages/operator-protocols/src/operator_protocols/invariant.py
    - packages/operator-protocols/src/operator_protocols/types.py
  modified: []

key-decisions:
  - "Observation type is dict[str, Any] for maximum flexibility across subjects"
  - "store_id kept in InvariantViolation for backward compatibility"
  - "Zero dependencies - package has no external requirements"

patterns-established:
  - "Protocol package: Zero dependencies, pure type definitions"
  - "runtime_checkable: Enable isinstance() checks for protocol compliance"

# Metrics
duration: 2min
completed: 2026-01-26
---

# Phase 16 Plan 01: Create operator-protocols Package Summary

**Zero-dependency protocol package with SubjectProtocol, InvariantCheckerProtocol, and generic Store/StoreMetrics/ClusterMetrics types**

## Performance

- **Duration:** 2 min 18 sec
- **Started:** 2026-01-26T22:20:05Z
- **Completed:** 2026-01-26T22:22:23Z
- **Tasks:** 3 (combined into 1 atomic commit)
- **Files created:** 5

## Accomplishments

- Created operator-protocols package with hatchling build system
- Defined SubjectProtocol with observe() and get_action_definitions() methods
- Defined InvariantCheckerProtocol with check() method returning InvariantViolation list
- Extracted generic Store, StoreMetrics, ClusterMetrics types from operator-core
- All protocols are @runtime_checkable for isinstance() checking
- Package has zero dependencies on other operator-* packages

## Task Commits

All tasks were combined into a single atomic commit since they create the same package:

1. **Tasks 1-3: Create operator-protocols package** - `bb2b7a9` (feat)
   - Package structure (pyproject.toml, __init__.py)
   - SubjectProtocol and InvariantCheckerProtocol definitions
   - Generic types (Store, StoreMetrics, ClusterMetrics)

## Files Created

- `packages/operator-protocols/pyproject.toml` - Package config with no dependencies
- `packages/operator-protocols/src/operator_protocols/__init__.py` - Public API re-exports
- `packages/operator-protocols/src/operator_protocols/subject.py` - SubjectProtocol definition
- `packages/operator-protocols/src/operator_protocols/invariant.py` - InvariantCheckerProtocol and InvariantViolation
- `packages/operator-protocols/src/operator_protocols/types.py` - Generic Store, StoreMetrics, ClusterMetrics

## Decisions Made

1. **Observation type as dict[str, Any]** - Per CONTEXT.md, using flexible dict allows different subjects to have different observation schemas without protocol changes

2. **store_id field name preserved** - Per RESEARCH.md backward compatibility recommendation, kept store_id in InvariantViolation even though it can represent any entity

3. **Combined tasks into single commit** - Since all three tasks create files in the same new package, combining into one atomic commit is cleaner than three commits that would each leave the package in a broken state

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- operator-protocols package ready for 16-02 (operator-tikv migration)
- SubjectProtocol ready for TiKVSubject to implement
- InvariantCheckerProtocol ready for InvariantChecker to implement
- Generic types ready to replace TiKV-specific types in operator-core

---
*Phase: 16-core-abstraction-refactoring*
*Completed: 2026-01-26*
