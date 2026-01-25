---
phase: 06-chaos-demo
plan: 02
subsystem: demo
tags: [typer, cli, asyncio, rich, chaos-engineering]

# Dependency graph
requires:
  - phase: 06-01
    provides: ChaosDemo orchestrator class
provides:
  - CLI command `operator demo chaos`
  - End-to-end chaos demo experience
  - Active invariant checking pattern during fault detection
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typer subcommand for demo namespace"
    - "Active invariant checking during detection wait"
    - "asyncio.run() for CLI-to-async bridge"

key-files:
  created:
    - packages/operator-core/src/operator_core/cli/demo.py
  modified:
    - packages/operator-core/src/operator_core/cli/main.py
    - packages/operator-core/src/operator_core/demo/chaos.py

key-decisions:
  - "Active invariant checking during detection (not passive polling)"
  - "One-shot invariant check per poll iteration"
  - "Detection within 2-4 seconds after fault injection"

patterns-established:
  - "Demo CLI namespace with typer.Typer()"
  - "asyncio.run() wrapper for CLI commands calling async code"

# Metrics
duration: 5min
completed: 2026-01-25
---

# Phase 6 Plan 02: Demo CLI Command Summary

**CLI command `operator demo chaos` with active invariant checking for fast fault detection (2-4 seconds)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-25T03:05:00Z
- **Completed:** 2026-01-25T03:10:00Z
- **Tasks:** 2 (1 auto + 1 checkpoint)
- **Files modified:** 3

## Accomplishments
- Demo CLI subcommand (`operator demo chaos`) with --timeout and --subject options
- Integration with ChaosDemo orchestrator via asyncio.run() bridge
- Active invariant checking during detection wait (fix for initial passive polling)
- Complete end-to-end demo verified by user: healthy cluster -> fault injection -> detection -> AI diagnosis -> cleanup

## Task Commits

Each task was committed atomically:

1. **Task 1: Create demo CLI subcommand** - `02e4416` (feat)
2. **Fix: Active invariant checking during detection** - `0db240b` (fix)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `packages/operator-core/src/operator_core/cli/demo.py` - Demo CLI with chaos command
- `packages/operator-core/src/operator_core/cli/main.py` - Added demo_app to main CLI
- `packages/operator-core/src/operator_core/demo/chaos.py` - Fixed detection to use active invariant checking

## Decisions Made
- **Active invariant checking:** Changed from passive ticket polling to active `invariants.check()` calls during detection wait loop - ensures immediate detection when fault occurs
- **One-shot check per iteration:** Single invariant check per 2-second poll cycle balances responsiveness with load
- **Detection timing:** Fault detection now occurs within 2-4 seconds of container kill, well within 30s timeout

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed passive polling to active invariant checking**
- **Found during:** Checkpoint verification (Task 2)
- **Issue:** Initial implementation waited for TicketDB entries but didn't trigger invariant checks - detection never occurred
- **Fix:** Added direct `invariants.check()` calls in detection wait loop to actively check for violations
- **Files modified:** packages/operator-core/src/operator_core/demo/chaos.py
- **Verification:** Detection now works within 2-4 seconds after fault injection
- **Committed in:** 0db240b

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Critical bug fix required for demo to function. Without active checking, detection would never trigger.

## Issues Encountered
None beyond the auto-fixed detection bug.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 6 (Chaos Demo) is now complete
- All project phases (1-6) complete
- Full demo experience available via `operator demo chaos`
- Project ready for production use or further enhancement

---
*Phase: 06-chaos-demo*
*Completed: 2026-01-25*
