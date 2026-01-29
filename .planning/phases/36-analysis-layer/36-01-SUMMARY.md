---
phase: 36-analysis-layer
plan: 01
subsystem: evaluation
tags: [pydantic, scoring, analysis, metrics]

# Dependency graph
requires:
  - phase: 35-runner-layer
    provides: Trial dataclass with ISO8601 timestamps and JSON state snapshots
provides:
  - TrialScore dataclass for computed metrics (outcome, detection/resolution times, command counts)
  - CampaignSummary dataclass for aggregated campaign metrics (win rate, averages)
  - score_trial() function for idempotent trial scoring from raw Trial data
  - analyze_campaign() function for campaign-level aggregation
affects: [36-02-commands, 36-03-visualize, 37-viewer-layer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pydantic BaseModel for JSON-serializable analysis types"
    - "ISO8601 timestamp parsing with datetime.fromisoformat()"
    - "Subject-specific health checks (TiKV stores state)"
    - "Idempotent analysis functions (read-only, no database mutations)"

key-files:
  created:
    - eval/src/eval/analysis/__init__.py
    - eval/src/eval/analysis/types.py
    - eval/src/eval/analysis/scoring.py
  modified: []

key-decisions:
  - "Resolution requires both resolved_at timestamp AND healthy final state"
  - "TiKV health check: all stores in 'Up' state"
  - "Time calculations in seconds using timedelta.total_seconds()"
  - "Separate score_trial() (fast) and score_trial_with_commands() (full analysis)"

patterns-established:
  - "Analysis functions are pure: read Trial data, return dataclass, no mutations"
  - "Subject-specific health logic in is_final_state_healthy()"
  - "Lazy import of commands module to avoid circular dependency"

# Metrics
duration: 1min 46sec
completed: 2026-01-29
---

# Phase 36 Plan 01: Analysis Types and Scoring Summary

**Pydantic-based scoring types with time-to-detect/resolve calculations from ISO8601 Trial timestamps, subject-specific health checks for TiKV clusters**

## Performance

- **Duration:** 1min 46sec
- **Started:** 2026-01-29T21:31:42Z
- **Completed:** 2026-01-29T21:33:28Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- TrialScore, CampaignSummary, TrialOutcome types using Pydantic for JSON serialization
- score_trial() computes time-to-detect (chaos->ticket) and time-to-resolve (chaos->resolution) from ISO8601 timestamps
- TiKV-specific health check validates all stores in 'Up' state for resolution success
- analyze_campaign() aggregates metrics across trials (win rate, average times, command counts)
- All analysis functions are idempotent (read-only, no database mutations)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create analysis types module** - `3d54449` (feat)
2. **Task 2: Implement scoring module** - `1afb692` (feat)

## Files Created/Modified
- `eval/src/eval/analysis/__init__.py` - Module exports for analysis types and functions
- `eval/src/eval/analysis/types.py` - TrialScore, CampaignSummary, TrialOutcome dataclasses
- `eval/src/eval/analysis/scoring.py` - Idempotent scoring and aggregation functions

## Decisions Made

**Resolution criteria:** Ticket must be both resolved (resolved_at timestamp) AND cluster must be healthy (final_state check). This prevents false positives where ticket closes but cluster remains unhealthy.

**TiKV health logic:** Health check parses final_state JSON and validates all stores have state_name='Up'. Other subjects default to healthy if final_state exists (baseline trials may not create tickets).

**Time calculations:** Use datetime.fromisoformat() for ISO8601 parsing (preserves timezone), compute duration with timedelta.total_seconds() for float seconds.

**Two scoring functions:** score_trial() provides fast timing metrics only. score_trial_with_commands() adds full command analysis (requires LLM for destructive count). Split allows performance optimization when command details not needed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for plan 36-02 (command analysis). Scoring foundation established:
- TrialScore captures all required metrics (outcome, times, command counts)
- score_trial_with_commands() prepared for integration with analyze_commands() from plan 36-02
- analyze_campaign() ready for viewer layer aggregation

No blockers. Requirements ANAL-01 (trial scoring) and ANAL-06 (idempotent analysis) satisfied.

---
*Phase: 36-analysis-layer*
*Completed: 2026-01-29*
