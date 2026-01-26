---
phase: 13-tikv-subject-actions
plan: 01
subsystem: tikv
tags: [pd-api, actions, httpx, pydantic, transfer-leader, transfer-peer, drain-store]

# Dependency graph
requires:
  - phase: 12-action-foundation
    provides: ActionRegistry, ActionDefinition, ParamDef for runtime action discovery
provides:
  - PDClient.add_transfer_leader_operator() for leader transfers
  - PDClient.add_transfer_peer_operator() for peer replica moves
  - PDClient.add_evict_leader_scheduler() for store draining
  - TiKVSubject.transfer_leader() action method
  - TiKVSubject.transfer_peer() action method
  - TiKVSubject.drain_store() action method
  - TiKVSubject.get_action_definitions() for ActionRegistry integration
affects: [14-approval-workflow, 15-workflow-actions]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fire-and-forget action execution via raise_for_status()"
    - "Store ID type conversion (str to int) at Subject layer"
    - "Hyphenated operator names in PD API (transfer-leader, not transfer_leader)"

key-files:
  created: []
  modified:
    - packages/operator-tikv/src/operator_tikv/pd_client.py
    - packages/operator-tikv/src/operator_tikv/subject.py

key-decisions:
  - "Fire-and-forget semantics - return on API success, don't poll for completion"
  - "Minimal validation - let PD API reject invalid requests"
  - "Pass-through errors - don't transform PD error messages"

patterns-established:
  - "PDClient POST methods use hyphenated operator names (transfer-leader)"
  - "Subject action methods convert string store IDs to int for PD API"
  - "get_action_definitions() returns ActionDefinition with ParamDef schemas"

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 13 Plan 01: TiKV Subject Actions Summary

**PD API operator/scheduler POST methods in PDClient with TiKVSubject action methods delegating to them, plus ActionRegistry integration via get_action_definitions()**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T16:02:39Z
- **Completed:** 2026-01-26T16:05:17Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- PDClient extended with POST methods for PD API operators and schedulers
- TiKVSubject action methods (transfer_leader, transfer_peer, drain_store) implemented with fire-and-forget semantics
- ActionRegistry integration via get_action_definitions() with proper parameter schemas and risk levels

## Task Commits

Each task was committed atomically:

1. **Task 1: Add PD API operator and scheduler methods to PDClient** - `4592329` (feat)
2. **Task 2: Implement TiKVSubject action methods** - `0934779` (feat)
3. **Task 3: Implement get_action_definitions for ActionRegistry integration** - `a0f1a30` (feat)

## Files Created/Modified

- `packages/operator-tikv/src/operator_tikv/pd_client.py` - Added 3 async POST methods for operators/schedulers
- `packages/operator-tikv/src/operator_tikv/subject.py` - Implemented action methods and get_action_definitions()

## Decisions Made

None - followed plan as specified. All implementation decisions (fire-and-forget, minimal validation, pass-through errors) were pre-defined in CONTEXT.md.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff linter not installed in venv - skipped lint check (not blocking, code follows existing patterns)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TiKVSubject action execution layer complete
- ActionRegistry can discover all 3 actions at runtime
- Ready for Phase 14 (Approval Workflow) to add human approval gates
- Ready for Phase 15 (Workflow Actions) to integrate actions into agent workflow

---
*Phase: 13-tikv-subject-actions*
*Completed: 2026-01-26*
