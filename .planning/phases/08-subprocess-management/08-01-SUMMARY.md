---
phase: 08-subprocess-management
plan: 01
subsystem: tui
tags: [asyncio, subprocess, output-capture, daemon]

# Dependency graph
requires:
  - phase: 07-tui-foundation
    provides: OutputBuffer ring buffer for captured output
provides:
  - ManagedProcess dataclass (process + buffer + name)
  - SubprocessManager class (spawn, read_output, terminate)
  - PYTHONUNBUFFERED=1 pattern for unbuffered capture
  - SIGTERM -> wait -> SIGKILL shutdown pattern
affects: [08-02, 08-03, tui-controller-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.create_subprocess_exec with PIPE"
    - "asyncio.wait_for(readline(), timeout=0.1)"
    - "start_new_session=True for process groups"

key-files:
  created:
    - packages/operator-core/src/operator_core/tui/subprocess.py
  modified:
    - packages/operator-core/src/operator_core/tui/__init__.py

key-decisions:
  - "PYTHONUNBUFFERED=1 over PTY for output buffering"
  - "0.1s readline timeout for responsive shutdown"
  - "Merge stderr into stdout for simpler capture"

patterns-established:
  - "ManagedProcess pattern: subprocess + buffer + name"
  - "Shutdown coordination via asyncio.Event"

# Metrics
duration: 3min
completed: 2026-01-25
---

# Phase 8 Plan 01: SubprocessManager Summary

**SubprocessManager class with asyncio subprocess spawning, OutputBuffer capture, and SIGTERM/SIGKILL shutdown**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-25T07:43:16Z
- **Completed:** 2026-01-25T07:46:28Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- ManagedProcess dataclass wrapping process, buffer, and name
- SubprocessManager with spawn/read_output/terminate/terminate_all/get_buffer methods
- PYTHONUNBUFFERED=1 environment variable for immediate output
- start_new_session=True for clean process group termination
- Integration test verifying subprocess spawn and output capture

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SubprocessManager class** - `4634444` (feat)
2. **Task 2: Verify subprocess spawn and output capture** - verification only, no changes needed

**Plan metadata:** pending

## Files Created/Modified
- `packages/operator-core/src/operator_core/tui/subprocess.py` - SubprocessManager class with ManagedProcess dataclass
- `packages/operator-core/src/operator_core/tui/__init__.py` - Exports ManagedProcess and SubprocessManager

## Decisions Made
- Used `sys.executable` with command args for flexible subprocess spawning (not hardcoded -m operator_core.cli.main)
- Merged stderr into stdout (stderr=asyncio.subprocess.STDOUT) for simpler single-buffer capture
- 0.1s readline timeout balances responsiveness with CPU efficiency

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None - implementation followed research patterns exactly.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SubprocessManager ready for TUIController integration in 08-02
- ManagedProcess and OutputBuffer patterns established
- Reader tasks compatible with asyncio.TaskGroup

---
*Phase: 08-subprocess-management*
*Completed: 2026-01-25*
