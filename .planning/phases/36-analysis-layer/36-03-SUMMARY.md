---
phase: 36-analysis-layer
plan: 03
subsystem: analysis
tags: [evaluation, comparison, metrics, scoring]

# Dependency graph
requires:
  - phase: 36-01
    provides: Analysis types and scoring module
provides:
  - Baseline comparison showing agent vs self-healing with full metric breakdown
  - Campaign comparison with win rate as primary metric and resolution time tiebreaker
  - Auto-discovery of baseline campaigns by subject and chaos type
affects: [36-04, viewer-layer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Winner determination by primary metric (win rate) with tiebreaker (resolution time)"
    - "Campaign validation ensures matching subject_name and chaos_type"

key-files:
  created:
    - eval/src/eval/analysis/comparison.py
  modified:
    - eval/src/eval/analysis/__init__.py

key-decisions:
  - "Winner determined by higher win rate first, then faster resolution time as tiebreaker"
  - "Baseline campaigns auto-discovered by subject_name and chaos_type when not specified"
  - "Comparison validates campaigns have matching subject and chaos type before comparing"

patterns-established:
  - "Comparison functions are read-only (idempotent) - no database mutations"
  - "Delta computation shows agent - baseline for baseline comparison, B - A for campaign comparison"

# Metrics
duration: 2min
completed: 2026-01-29
---

# Phase 36 Plan 03: Comparison Module Summary

**Baseline and campaign comparison with win rate primary metric and resolution time tiebreaker**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-29T21:37:04Z
- **Completed:** 2026-01-29T21:38:38Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- BaselineComparison model for agent vs self-healing with full metric breakdown
- CampaignComparison model for campaign A vs B comparison
- Winner determination logic using win rate as primary metric, resolution time as tiebreaker
- Auto-discovery of baseline campaigns when not explicitly specified

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement comparison module** - `8856ca8` (feat)

## Files Created/Modified
- `eval/src/eval/analysis/comparison.py` - Baseline and campaign comparison functions with winner determination
- `eval/src/eval/analysis/__init__.py` - Export comparison types and functions

## Decisions Made

None - followed plan as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Comparison module complete. Ready for:
- Plan 36-04: Command analysis with LLM classification
- Phase 37: Viewer layer for CLI output formatting

All comparison functions are idempotent (read-only) and properly validate campaign compatibility before comparing.

---
*Phase: 36-analysis-layer*
*Completed: 2026-01-29*
