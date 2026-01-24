---
phase: 04-monitor-loop
plan: 02
subsystem: daemon
tags: [asyncio, signal-handling, daemon, monitoring, invariants]

# Dependency graph
requires:
  - phase: 04-01
    provides: TicketDB async context manager for ticket persistence
  - phase: 02-05
    provides: InvariantChecker with stores_up, latency, disk_space checks
provides:
  - MonitorLoop daemon class with asyncio event loop
  - Signal handlers for graceful shutdown (SIGINT/SIGTERM)
  - Check cycle integrating InvariantChecker with TicketDB
  - Auto-resolve when violations clear
  - Periodic heartbeat logging
affects: [04-03-cli-commands, 05-ai-diagnosis]

# Tech tracking
tech-stack:
  added: []
  patterns: [asyncio.Event for shutdown coordination, functools.partial for signal handlers, wait_for with timeout for interruptible sleep]

key-files:
  created:
    - packages/operator-core/src/operator_core/monitor/loop.py
  modified:
    - packages/operator-core/src/operator_core/monitor/__init__.py

key-decisions:
  - "Use asyncio.Event for shutdown coordination, not busy polling"
  - "Register signal handlers inside run() via get_running_loop()"
  - "Use wait_for with timeout for interruptible sleep per RESEARCH.md"
  - "TicketDB as async context manager wrapping the entire loop"

patterns-established:
  - "Daemon loop with signal handling per RESEARCH.md Pattern 2"
  - "Check cycle queries subject -> checks invariants -> creates tickets -> auto-resolves"

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 04 Plan 02: Monitor Loop Summary

**MonitorLoop daemon with asyncio, signal handling, InvariantChecker integration, and auto-resolve logic**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T23:13:17Z
- **Completed:** 2026-01-24T23:15:12Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- MonitorLoop daemon class with configurable interval
- Graceful shutdown via SIGINT/SIGTERM signal handlers
- asyncio.Event for shutdown coordination (not busy polling)
- wait_for with timeout for interruptible sleep
- Check cycle integrating stores, metrics, and invariant checks
- Tickets created/updated for violations via TicketDB
- Auto-resolve for cleared violations
- Heartbeat logging showing invariant count and status

## Task Commits

Each task was committed atomically:

1. **Task 1: Create MonitorLoop class with daemon logic** - `093a74b` (feat)
2. **Task 2: Wire loop to InvariantChecker and add heartbeat** - `21ba0dc` (feat)

## Files Created/Modified

- `packages/operator-core/src/operator_core/monitor/loop.py` - MonitorLoop daemon class with full implementation (176 lines)
- `packages/operator-core/src/operator_core/monitor/__init__.py` - Added MonitorLoop export

## Decisions Made

- **asyncio.Event for shutdown:** Per RESEARCH.md Pattern 2, using Event.wait() with timeout rather than asyncio.sleep() allows immediate response to shutdown signals
- **Signal handlers in run():** Registered via loop.add_signal_handler() inside the async run() method to ensure main thread context
- **TicketDB wrapping loop:** Database connection opened once at start, closed on shutdown, ensuring consistent state across all check cycles

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all verification scripts passed on first attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MonitorLoop provides the daemon for continuous monitoring
- Ready for CLI commands (04-03) to expose `operator monitor` command
- Ready for AI diagnosis (Phase 5) to attach diagnoses to tickets

---
*Phase: 04-monitor-loop*
*Completed: 2026-01-24*
