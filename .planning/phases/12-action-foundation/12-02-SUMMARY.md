---
phase: 12-action-foundation
plan: 02
subsystem: actions
tags: [pydantic, validation, registry, protocol, discovery]

# Dependency graph
requires:
  - phase: 12-01
    provides: ActionProposal, ActionRecord, ActionStatus types
provides:
  - ActionDefinition and ParamDef Pydantic models
  - ActionRegistry for runtime action discovery
  - validate_action_params for pre-flight parameter checking
  - Subject.get_action_definitions() protocol method
affects: [12-03-safety-infrastructure, 12-04-action-executor, 13-tikv-actions, 14-approval-workflow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Forward reference TYPE_CHECKING for circular import avoidance
    - Lazy caching in ActionRegistry
    - Collect-all-errors validation pattern

key-files:
  created:
    - packages/operator-core/src/operator_core/actions/registry.py
    - packages/operator-core/src/operator_core/actions/validation.py
  modified:
    - packages/operator-core/src/operator_core/subject.py
    - packages/operator-core/src/operator_core/actions/__init__.py

key-decisions:
  - "Forward reference for ActionDefinition in Subject protocol avoids circular imports"
  - "Lazy cache in ActionRegistry built on first call, can be cleared if subject changes"
  - "Validation collects ALL errors before raising for complete user feedback"

patterns-established:
  - "TYPE_CHECKING import guard for cross-module type hints"
  - "ActionRegistry caching pattern for expensive discovery calls"
  - "ValidationError with action_name + errors list for actionable feedback"

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 12 Plan 02: Action Registry Summary

**ActionRegistry for runtime action discovery from subjects with ParamDef/ActionDefinition models and validate_action_params pre-flight checking**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T15:12:37Z
- **Completed:** 2026-01-26T15:16:15Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Subject protocol extended with get_action_definitions() method for runtime discovery
- ActionDefinition model with name, description, parameters dict, risk_level, and requires_approval
- ParamDef model for individual parameter schemas (type, description, required, default)
- ActionRegistry class with lazy caching, get_definitions(), get_definition(), list_action_names()
- validate_action_params function with type checking for int/str/float/bool
- ValidationError exception collecting all errors for complete feedback

## Task Commits

Each task was committed atomically:

1. **Task 1: Add action discovery to Subject protocol** - `7593732` (feat)
2. **Task 2: Create ActionRegistry and ActionDefinition** - `83333f9` (feat)
3. **Task 3: Create parameter validation framework** - `a955045` (feat)

## Files Created/Modified
- `packages/operator-core/src/operator_core/subject.py` - Added get_action_definitions() to Subject protocol
- `packages/operator-core/src/operator_core/actions/registry.py` - ActionRegistry, ActionDefinition, ParamDef
- `packages/operator-core/src/operator_core/actions/validation.py` - validate_action_params, ValidationError
- `packages/operator-core/src/operator_core/actions/__init__.py` - Export new types

## Decisions Made
- Used TYPE_CHECKING import guard for ActionDefinition forward reference in Subject to avoid circular imports
- ActionRegistry uses lazy caching pattern - cache built on first call to get_definitions()
- ValidationError collects ALL errors before raising rather than failing on first error
- Type checking handles Python's bool-is-subclass-of-int quirk explicitly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ActionRegistry ready for safety infrastructure (12-03) to validate actions
- validate_action_params ready for executor pre-flight checks (12-04)
- Subject protocol ready for TiKV implementation (Phase 13)

---
*Phase: 12-action-foundation*
*Completed: 2026-01-26*
