---
phase: 25-host-actions
plan: 02
subsystem: infra
tags: [os.kill, signal, SIGTERM, SIGKILL, process-management, pid-validation]

# Dependency graph
requires:
  - phase: 25-host-actions-01
    provides: HostActionExecutor class, ServiceWhitelist validation
provides:
  - validate_pid function for PID validation with kernel thread protection
  - kill_process method with graceful SIGTERM -> SIGKILL escalation
  - Comprehensive tests for process signaling operations
affects: [26-script-execution, 28-agent-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: [graceful-escalation, pid-validation-pattern]

key-files:
  created: []
  modified:
    - packages/operator-core/src/operator_core/host/validation.py
    - packages/operator-core/src/operator_core/host/actions.py
    - packages/operator-core/src/operator_core/host/__init__.py
    - packages/operator-core/tests/test_host_actions.py

key-decisions:
  - "PID < 300 threshold blocks kernel threads conservatively"
  - "Signal 0 pre-validation confirms process existence and permission"
  - "Graceful timeout default 5s matches Docker/Kubernetes convention"
  - "Escalation happens only after timeout loop completes"

patterns-established:
  - "PID validation: check type, init, kernel threads, then signal 0"
  - "Graceful escalation: SIGTERM -> poll existence -> SIGKILL if still alive"

# Metrics
duration: 4min
completed: 2026-01-28
---

# Phase 25 Plan 02: Process Kill with Graceful Escalation Summary

**Process kill capability with SIGTERM -> 5s wait -> SIGKILL escalation and PID validation protecting init and kernel threads**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-28T05:54:42Z
- **Completed:** 2026-01-28T05:58:48Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- validate_pid function blocks PID 1 (init), PID < 300 (kernel threads), and validates existence via signal 0
- kill_process method sends SIGTERM by default with configurable graceful timeout
- Graceful escalation pattern: SIGTERM -> wait up to graceful_timeout seconds -> SIGKILL if still running
- 21 new tests covering PID validation and process kill scenarios (787 total lines in test file)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add validate_pid function to validation module** - `65e2109` (feat)
2. **Task 2: Add kill_process method to HostActionExecutor** - `57c644b` (feat)
3. **Task 3: Add unit tests for process kill functionality** - `1da7792` (test)

## Files Created/Modified

- `packages/operator-core/src/operator_core/host/validation.py` - Added validate_pid function with PID constraints
- `packages/operator-core/src/operator_core/host/actions.py` - Added kill_process method with graceful escalation
- `packages/operator-core/src/operator_core/host/__init__.py` - Export validate_pid
- `packages/operator-core/tests/test_host_actions.py` - Added TestPidValidation (8 tests) and TestHostKillProcess (13 tests)

## Decisions Made

1. **PID < 300 threshold** - Conservative protection against kernel threads. On modern Linux, user processes typically start at PID 300+. This prevents accidental signaling of critical kernel threads (kthreadd, etc.).

2. **Signal 0 pre-validation** - Using os.kill(pid, 0) validates both process existence and permission atomically before attempting the actual signal. This provides clear error messages and prevents TOCTOU issues.

3. **5-second default graceful timeout** - Matches Docker and Kubernetes conventions for graceful shutdown. Long enough for most applications to clean up, short enough to not delay operations unnecessarily.

4. **Check every 100ms during timeout** - Efficient polling frequency that balances responsiveness with CPU usage. Process exit detected within 100ms of actual termination.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation followed research patterns directly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Process signaling capability complete for Phase 25
- Ready for Plan 03 (if any) or Phase 26 (Script Execution)
- All HOST-04, HOST-05, HOST-06 requirements for process operations now met

---
*Phase: 25-host-actions*
*Completed: 2026-01-28*
