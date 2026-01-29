---
phase: 37-viewer-layer
plan: 01
subsystem: cli
tags: [typer, aiosqlite, cli, viewer, json]

# Dependency graph
requires:
  - phase: 36-analysis-layer
    provides: analyze_campaign function for campaign scoring
  - phase: 35-runner-layer
    provides: EvalDB with get_campaign and get_trials methods
provides:
  - CLI viewer commands (eval list, eval show) for browsing evaluation data
  - Database query methods for listing campaigns and retrieving trials
  - JSON output mode for machine-readable data export
affects: [future-reporting, ci-integration, historical-analysis]

# Tech tracking
tech-stack:
  added: []
  patterns: [CLI table formatting with fixed-width columns, JSON output flag pattern]

key-files:
  created: []
  modified:
    - eval/src/eval/cli.py
    - eval/src/eval/runner/db.py

key-decisions:
  - "Plain text tables with fixed-width columns instead of Rich tables for portability"
  - "Unified show command with --trial flag instead of separate commands"
  - "Integrate analysis layer for aggregate scores in campaign view"

patterns-established:
  - "CLI pattern: async def run() inside command, asyncio.run(run())"
  - "Database query pattern: aiosqlite.Row factory for dict-like access"
  - "JSON output: --json flag returns machine-readable data, plain text for humans"

# Metrics
duration: 2min 26sec
completed: 2026-01-29
---

# Phase 37 Plan 01: Viewer Layer Summary

**CLI viewer commands for browsing campaigns and trials with plain text tables and JSON export**

## Performance

- **Duration:** 2 minutes 26 seconds
- **Started:** 2026-01-29T23:01:03Z
- **Completed:** 2026-01-29T23:03:29Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Database query methods for listing campaigns and retrieving individual trials
- `eval list` command displays campaigns in paginated table with JSON export
- `eval show` command displays campaign details with aggregate scores and trial list
- `eval show --trial` command displays trial details with commands and state info
- All commands support custom database paths and handle empty/missing data gracefully

## Task Commits

Each task was committed atomically:

1. **Task 1: Add database query methods for campaign listing and trial retrieval** - `3227bb6` (feat)
2. **Task 2: Add eval list command** - `6a9fa7c` (feat)
3. **Task 3: Add eval show command for campaigns and trials** - `2900009` (feat)

## Files Created/Modified
- `eval/src/eval/runner/db.py` - Added get_all_campaigns(), get_trial(), count_campaigns() methods
- `eval/src/eval/cli.py` - Added list and show commands with JSON output support

## Decisions Made

**1. Plain text tables instead of Rich tables**
- Rationale: Fixed-width column formatting works in any terminal without rich formatting
- Impact: More portable output, simpler code, consistent with rest of CLI

**2. Unified show command with --trial flag**
- Rationale: Single command with flag is simpler than separate show-campaign and show-trial commands
- Impact: Better UX, follows standard CLI conventions

**3. Integration with analysis layer**
- Rationale: Campaign view should show aggregate scores (win rate, avg times) from analyze_campaign
- Impact: More useful campaign details without requiring separate analyze command

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed without issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Viewer layer complete. Developers can now browse evaluation data from CLI.

Ready for Phase 38 (Chaos Expansion) to add more chaos types beyond node_kill.

All core eval harness functionality (runner, analysis, viewer) is operational.

---
*Phase: 37-viewer-layer*
*Completed: 2026-01-29*
