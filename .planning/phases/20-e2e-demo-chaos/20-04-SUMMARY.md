---
phase: 20-e2e-demo-chaos
plan: 04
subsystem: demo
tags: [rich, tui, asyncio, subprocess, keyboard, demo]

# Dependency graph
requires:
  - phase: 20-02
    provides: TiKV demo integration with chapters and health poller
  - phase: 20-03
    provides: Rate limiter demo integration with chapters and health poller
  - phase: 11-02
    provides: Existing TUI infrastructure (layout, subprocess, keyboard)
provides:
  - TUIDemoController combining TUI infrastructure with demo framework
  - Subject-agnostic health panel formatting (TiKV and rate limiter)
  - Shell script for running demos with subject selection
  - Main entry point for python -m demo invocation
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Protocol-based health formatting (detect subject from dict structure)
    - Subject CLI argument routing in shell script and Python main
    - TaskGroup coordination for subprocess + health + keyboard tasks

key-files:
  created:
    - demo/tui_integration.py
    - scripts/run-demo.sh
    - demo/__main__.py
  modified: []

key-decisions:
  - "Detect subject type from health dict structure (not explicit subject parameter)"
  - "Health panel formatting switches on presence of type='tikv'/'pd' in nodes"
  - "Shell script auto-starts rate limiter cluster if not running"
  - "Both demos use same TUI layout (5 panels) via TUIDemoController"

patterns-established:
  - "TUIDemoController parameterized by subject_name, chapters, health_poller"
  - "Monitor/agent subprocesses use --subject flag for subject selection"
  - "Subject-specific health formatting without subject-specific code in controller"

# Metrics
duration: 3min
completed: 2026-01-27
---

# Phase 20 Plan 04: TUI Integration Summary

**Full TUI integration with 5-panel layout works for both TiKV and rate limiter demos via protocol-based health formatting**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-27T03:05:03Z
- **Completed:** 2026-01-27T03:07:46Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- TUIDemoController combines existing TUI infrastructure with demo framework
- Subject-agnostic health panel formatting detects TiKV vs rate limiter from dict structure
- Shell script allows easy demo invocation: `./scripts/run-demo.sh [tikv|ratelimiter]`
- Python entry point supports `python -m demo [subject]` invocation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TUI-integrated demo controller** - `c32469a` (feat)
2. **Task 2: Create demo runner shell script** - `2672bd1` (feat)
3. **Task 3: Create main entry point** - `090e406` (feat)

## Files Created/Modified

- `demo/tui_integration.py` - TUIDemoController with 5-panel layout, subprocess management, health formatting
- `scripts/run-demo.sh` - Shell script for running demos with subject selection and cluster checks
- `demo/__main__.py` - Python main entry point routing to TUI controller based on subject

## Decisions Made

- **Detect subject type from health dict structure**: Rather than passing subject name to formatting functions, inspect health dict keys (presence of "type" field with "tikv"/"pd" indicates TiKV, otherwise rate limiter). This keeps controller truly subject-agnostic.

- **Shell script auto-starts rate limiter cluster**: For better UX, `run-demo.sh` checks if rate limiter cluster is running and starts it if needed. TiKV only prints instructions (less aggressive).

- **Both demos use same TUI layout**: TiKVHealthPoller and RateLimiterHealthPoller both return generic dicts, enabling the same TUIDemoController to render either subject's health in the cluster panel.

- **Monitor/agent subprocesses use --subject flag**: Subprocesses spawned with correct `--subject tikv` or `--subject ratelimiter` flag, ensuring they use appropriate subject factories.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

Phase 20 complete! v2.1 milestone ready for release.

The full demo infrastructure is now in place:
- Subject-agnostic abstractions (chapters, health polling, chaos)
- TiKV demo (8 chapters with node kill/recovery)
- Rate limiter demo (11 chapters with counter drift and ghost allowing)
- Full TUI integration (5-panel layout with subprocesses)
- Easy invocation via shell script or Python module

Next: Human verification of demos (Plan 05).

---
*Phase: 20-e2e-demo-chaos*
*Completed: 2026-01-27*
