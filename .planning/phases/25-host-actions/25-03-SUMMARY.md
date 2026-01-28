---
phase: 25-host-actions
plan: 03
subsystem: infra
tags: [host, actions, tools, systemd, process, action-framework]

# Dependency graph
requires:
  - phase: 25-01
    provides: HostActionExecutor with start/stop/restart_service methods
  - phase: 25-02
    provides: kill_process method with graceful escalation
provides:
  - get_host_tools() returns 4 ActionDefinitions for host operations
  - Host actions registered in get_general_tools() as ActionType.TOOL
  - TOOL_EXECUTORS maps all 4 host actions to executor methods
  - Integration tests verify framework integration
affects: [agent-integration, action-discovery, phase-26-script-execution]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy host executor initialization to avoid circular imports"
    - "Host actions discoverable through standard tool framework"

key-files:
  created:
    - .planning/phases/25-host-actions/25-03-SUMMARY.md
  modified:
    - packages/operator-core/src/operator_core/host/actions.py
    - packages/operator-core/src/operator_core/host/__init__.py
    - packages/operator-core/src/operator_core/actions/tools.py
    - packages/operator-core/tests/test_host_actions.py

key-decisions:
  - "Risk levels: MEDIUM for service start/restart (recoverable), HIGH for stop/kill_process (availability impact)"
  - "Lazy initialization of HostActionExecutor in _get_host_executor() to prevent circular import between tools.py and actions.py"
  - "All host actions require approval (no read-only host operations)"
  - "Lambda wrappers map tool names to executor methods (host_service_start -> start_service)"

patterns-established:
  - "ActionDefinition pattern: Host actions register as ActionType.TOOL with complete parameter definitions"
  - "Lazy executor pattern: Import executor inside getter function to break circular dependencies"
  - "TOOL_EXECUTORS map: Lambda wrappers call executor methods with keyword arguments"

# Metrics
duration: 4min
completed: 2026-01-28
---

# Phase 25 Plan 03: Host Action Registration Summary

**4 host actions registered as ActionType.TOOL in action framework with risk-based approval for systemd and process operations**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-28T04:15:00Z
- **Completed:** 2026-01-28T04:19:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Created get_host_tools() returning 4 ActionDefinition objects with proper risk levels
- Integrated host tools into get_general_tools() (14 total tools: 2 base + 8 Docker + 4 host)
- Mapped all 4 host actions to executor methods in TOOL_EXECUTORS
- Added 12 integration tests verifying framework integration and risk levels
- All 58 host tests pass (46 existing + 12 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create get_host_tools() function** - `53364da` (feat)
   - 4 ActionDefinition objects with ActionType.TOOL
   - Risk levels: medium (start, restart), high (stop, kill_process)
   - All actions require approval
   - Export get_host_tools from host package

2. **Task 2: Integrate host tools into tools.py** - `522a9fd` (feat)
   - Host tools included in get_general_tools()
   - Lazy executor initialization with _get_host_executor()
   - TOOL_EXECUTORS maps all 4 host actions

3. **Task 3: Add integration tests** - `8a2f1af` (test)
   - TestHostActionIntegration with 12 tests
   - Tests tool discovery, ActionType, executors, dispatching, and risk levels
   - All 58 tests pass

## Files Created/Modified
- `packages/operator-core/src/operator_core/host/actions.py` - Added get_host_tools() function with 4 ActionDefinitions
- `packages/operator-core/src/operator_core/host/__init__.py` - Export get_host_tools
- `packages/operator-core/src/operator_core/actions/tools.py` - Integrate host tools, lazy executor, TOOL_EXECUTORS mapping
- `packages/operator-core/tests/test_host_actions.py` - Added TestHostActionIntegration test class (12 tests)

## Decisions Made

**Risk level assignment:**
- MEDIUM risk (requires_approval=True): State changes that are recoverable
  - host_service_start: Start stopped service
  - host_service_restart: Restart service (temporary disruption)
- HIGH risk (requires_approval=True): Availability impact or process termination
  - host_service_stop: Stop running service (availability impact)
  - host_kill_process: Terminate process (process loss)

**All host actions require approval:**
Unlike Docker actions (which have read-only operations like logs/inspect), all host actions modify state. There are no read-only host operations exposed through the action framework.

**Circular import resolution:**
Applied same pattern from Docker integration - moved HostActionExecutor import inside _get_host_executor() function to break circular dependency between tools.py and host/actions.py.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Phase 25 Host Actions COMPLETE:**
- HOST-01: start_service implementation (25-01)
- HOST-02: stop_service implementation (25-01)
- HOST-03: restart_service implementation (25-01)
- HOST-04: kill_process with SIGTERM/SIGKILL (25-02)
- HOST-05: Graceful SIGTERM -> SIGKILL escalation (25-02)
- HOST-06: Service whitelist and PID validation (25-01, 25-02)
- HOST-07: Command injection prevention via create_subprocess_exec (25-01, 25-02)

**Ready for Phase 26 (Script Execution & Validation):**
- All infrastructure action patterns established (Docker + Host)
- ActionType.TOOL framework proven for agent discovery
- TOOL_EXECUTORS dispatch pattern ready for script execution
- Risk-based approval workflow operational

**No blockers.** Host action framework integration complete. Agent can now discover and execute host actions through standard action workflow.

---
*Phase: 25-host-actions*
*Completed: 2026-01-28*
