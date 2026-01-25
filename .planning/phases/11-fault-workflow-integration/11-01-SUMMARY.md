---
phase: 11-fault-workflow-integration
plan: 01
subsystem: tui
tags: [sparklines, ycsb, throughput, visualization, rich]

# Dependency graph
requires:
  - phase: 07-tui-foundation
    provides: Multi-panel layout structure with create_layout
  - phase: 08-subprocess-management
    provides: SubprocessManager for daemon output capture
provides:
  - WorkloadTracker class for throughput parsing and sparkline generation
  - make_workload_panel helper with degradation-aware styling
  - TUIController.update_workload() method for external throughput injection
affects:
  - 11-02 (countdown and fault injection will use workload panel)
  - 11-03 (recovery detection uses workload normalization)

# Tech tracking
tech-stack:
  added: [sparklines>=0.4.2]
  patterns: [sliding-window-deque, baseline-detection, unicode-sparklines]

key-files:
  created:
    - packages/operator-core/src/operator_core/tui/workload.py
  modified:
    - packages/operator-core/src/operator_core/tui/layout.py
    - packages/operator-core/src/operator_core/tui/controller.py
    - packages/operator-core/src/operator_core/tui/__init__.py
    - packages/operator-core/pyproject.toml

key-decisions:
  - "sparklines library over hand-rolled Unicode bars"
  - "Baseline from first 5 samples (warm-up period)"
  - "50% threshold for degradation detection"
  - "0.1 floor for zero values to avoid sparkline artifacts"

patterns-established:
  - "WorkloadTracker: sliding window + baseline + threshold detection"
  - "make_workload_panel: degradation-aware panel styling pattern"
  - "update_workload: external injection pattern for throughput data"

# Metrics
duration: 8min
completed: 2026-01-25
---

# Phase 11 Plan 01: WorkloadTracker and Sparkline Visualization Summary

**WorkloadTracker module with Unicode sparkline generation, YCSB output parsing, degradation detection, and TUIController integration**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-25T19:50:00Z
- **Completed:** 2026-01-25T19:58:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- WorkloadTracker class parses YCSB status output for ops/sec values
- Unicode sparkline visualization using sparklines library
- Degradation detection when throughput falls below 50% of baseline
- TUIController integration with update_workload() for external injection
- Workload panel displays color-coded status (green normal, red degraded)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create WorkloadTracker module with sparkline generation** - `7504c85` (feat)
2. **Task 2: Add make_workload_panel helper to layout.py** - `0c964fe` (feat)
3. **Task 3: Integrate WorkloadTracker into TUIController** - `cced4b9` (feat)

## Files Created/Modified

- `packages/operator-core/src/operator_core/tui/workload.py` - WorkloadTracker class with YCSB parsing, sparkline generation, degradation detection
- `packages/operator-core/src/operator_core/tui/layout.py` - make_workload_panel helper for degradation-aware styling
- `packages/operator-core/src/operator_core/tui/controller.py` - WorkloadTracker integration and update_workload() method
- `packages/operator-core/src/operator_core/tui/__init__.py` - Export WorkloadTracker
- `packages/operator-core/pyproject.toml` - Add sparklines>=0.4.2 dependency

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| sparklines library over hand-rolled | Library handles scaling, edge cases; MIT license, pure Python |
| 5 samples for baseline warm-up | Sufficient to establish stable baseline without long delay |
| 50% threshold for degradation | Conservative default; tunable via constructor parameter |
| max(0.1, value) floor | Prevents sparkline artifacts with zero values per RESEARCH.md Pitfall 1 |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed successfully.

## User Setup Required

None - sparklines installed automatically via pip.

## Next Phase Readiness

- WorkloadTracker ready for Plan 02 (countdown and fault injection)
- update_workload() method available for external throughput injection
- Degradation detection will enable auto-advance when throughput recovers
- No blockers for next plan

---
*Phase: 11-fault-workflow-integration*
*Completed: 2026-01-25*
