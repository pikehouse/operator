---
phase: 15-workflow-actions
plan: 03
subsystem: actions
tags: [retry, backoff, jitter, tenacity, workflow, executor]

# Dependency graph
requires:
  - phase: 15-01
    provides: "Schema extensions for workflow_id, retry_count, next_retry_at, last_error columns"
provides:
  - "RetryConfig class with exponential backoff and jitter calculation"
  - "propose_workflow method for multi-action workflow proposals"
  - "schedule_next_retry method for failed action retry scheduling"
affects: [15-04, agent-runner, action-execution]

# Tech tracking
tech-stack:
  added: [tenacity>=8.2.0]
  patterns: [exponential-backoff-with-jitter, workflow-proposal]

key-files:
  created:
    - packages/operator-core/src/operator_core/actions/retry.py
  modified:
    - packages/operator-core/pyproject.toml
    - packages/operator-core/src/operator_core/actions/__init__.py
    - packages/operator-core/src/operator_core/actions/executor.py

key-decisions:
  - "RetryConfig uses dataclass for simplicity over Pydantic"
  - "Default max_attempts=3, min_wait=1s, max_wait=60s, base=2, jitter=0.5"
  - "schedule_next_retry uses RetryConfig.max_attempts not proposal.max_retries"

patterns-established:
  - "Exponential backoff formula: min(max_wait, min_wait * base^attempt) + jitter"
  - "Jitter calculated as random(0, wait * jitter_fraction)"

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 15 Plan 03: Retry Configuration and Workflow Extension Summary

**RetryConfig with exponential backoff + jitter, ActionExecutor extended with propose_workflow and schedule_next_retry methods**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T17:42:34Z
- **Completed:** 2026-01-26T17:45:10Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added tenacity>=8.2.0 dependency for future retry decoration
- Created RetryConfig dataclass with exponential backoff and jitter calculation
- Added propose_workflow method to create multi-action workflow proposals
- Added schedule_next_retry method for retry scheduling with audit logging

## Task Commits

Each task was committed atomically:

1. **Task 1: Add tenacity dependency and create retry configuration module** - `67d6c4e` (feat)
2. **Task 2: Add workflow proposal method to ActionExecutor** - `f5b55d8` (feat)
3. **Task 3: Add retry scheduling method to ActionExecutor** - `05d396f` (feat)

## Files Created/Modified
- `packages/operator-core/pyproject.toml` - Added tenacity>=8.2.0 dependency
- `packages/operator-core/src/operator_core/actions/retry.py` - RetryConfig with backoff calculation
- `packages/operator-core/src/operator_core/actions/__init__.py` - Export RetryConfig
- `packages/operator-core/src/operator_core/actions/executor.py` - propose_workflow and schedule_next_retry methods

## Decisions Made
- Used dataclass for RetryConfig (simpler than Pydantic for config-only class)
- Default retry config: 3 attempts, 1-60s wait range, base 2 exponential, 50% jitter
- schedule_next_retry uses executor's retry_config, not proposal's max_retries field

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- RetryConfig ready for use in agent runner (Plan 04)
- propose_workflow ready for multi-action workflow creation
- schedule_next_retry integrates with ActionDB retry methods from Plan 02
- Database methods (increment_retry_count, update_next_retry) available from Plan 02

---
*Phase: 15-workflow-actions*
*Completed: 2026-01-26*
