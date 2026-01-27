---
phase: 20-e2e-demo-chaos
plan: 01
subsystem: demo-infra
tags: [demo, chaos-engineering, tui, asyncio, rich, protocols]

# Dependency graph
requires:
  - phase: 11-tui-integration
    provides: Chapter dataclass pattern for demo progression
  - phase: 16-core-abstraction-refactoring
    provides: Protocol-based abstraction pattern
provides:
  - Generic demo infrastructure with Chapter/ChaosConfig types
  - DemoRunner accepting subject-specific chapters and health pollers
  - HealthPollerProtocol for subject-agnostic health polling
  - ChaosType enum for type-safe chaos injection scenarios
affects: [20-02-tikv-demo, 20-03-ratelimiter-demo]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Protocol-based health polling for subject abstraction
    - Chapter-driven demo progression with callbacks
    - Auto-advance and blocks_advance for automated chapter flow

key-files:
  created:
    - demo/__init__.py
    - demo/types.py
    - demo/runner.py
  modified: []

key-decisions:
  - "Chapter dataclass duplicated (not imported) to keep demo/ self-contained"
  - "ChaosType enum includes CONTAINER_KILL, REDIS_PAUSE, BURST_TRAFFIC for multi-subject support"
  - "HealthPollerProtocol enables subject-specific health implementations"
  - "DemoRunner simplified vs TUIController (no subprocess monitors, no 5-panel layout)"
  - "Full TUI integration deferred to Plans 02 and 03"

patterns-established:
  - "Pattern 1: Generic demo runner accepting chapters + health poller protocol"
  - "Pattern 2: ChaosConfig dataclass for declarative chaos scenario definition"
  - "Pattern 3: Signal handlers for graceful demo shutdown"

# Metrics
duration: 2min
completed: 2026-01-27
---

# Phase 20 Plan 01: Shared Demo Infrastructure Summary

**Generic demo framework with Chapter progression, ChaosType enum, and DemoRunner accepting subject-specific health pollers**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-27T02:51:18Z
- **Completed:** 2026-01-27T02:53:09Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created demo/ package with Chapter, DemoState, ChaosType, ChaosConfig types
- Implemented generic DemoRunner orchestrating chapter progression with keyboard input
- Defined HealthPollerProtocol for subject-agnostic health polling
- Established foundation for multi-subject chaos demonstrations

## Task Commits

Each task was committed atomically:

1. **Task 1: Create demo package with Chapter and Chaos types** - `f58ca0f` (feat)
2. **Task 2: Create generic DemoRunner class** - `1c8e1cb` (feat)

## Files Created/Modified
- `demo/__init__.py` - Package initialization and docstring
- `demo/types.py` - Chapter, DemoState, ChaosType, ChaosConfig, HealthPollerProtocol definitions
- `demo/runner.py` - Generic DemoRunner class with keyboard-driven chapter progression

## Decisions Made

**1. Chapter dataclass duplicated from operator_core/tui/chapters.py**
- **Rationale:** Keeps demo/ self-contained and independent from operator-core internals
- **Impact:** Easier to maintain demo package separately, no coupling to TUI package

**2. ChaosType enum includes three chaos scenarios**
- **Values:** CONTAINER_KILL (TiKV), REDIS_PAUSE (rate limiter drift), BURST_TRAFFIC (ghost allowing)
- **Rationale:** Type safety for chaos injection, extensible for future subjects
- **Impact:** Enables declarative chaos configuration across different distributed systems

**3. HealthPollerProtocol for subject-specific implementations**
- **Methods:** run(), get_health(), stop()
- **Rationale:** DemoRunner doesn't need to know subject health details
- **Impact:** TiKV and rate limiter demos can provide their own health polling logic

**4. DemoRunner simplified vs TUIController**
- **NOT included:** Subprocess monitors/agents, 5-panel layout, workload metrics
- **Rationale:** This runner tests chapter/chaos abstraction before full TUI integration
- **Impact:** Full TUI integration deferred to Plans 02 (TiKV) and 03 (rate limiter)

**5. on_enter callbacks and auto_advance support**
- **Pattern:** Chapter callbacks run when entering chapter, auto_advance progresses automatically
- **Rationale:** Enables automated demo flow for fault injection and recovery
- **Impact:** Follows existing FaultWorkflow countdown/callback patterns from Phase 11

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Demo infrastructure complete and ready for subject-specific integration
- Plan 02 (TiKV demo) can create TiKV-specific chapters and health poller
- Plan 03 (rate limiter demo) can reuse same DemoRunner with rate limiter chapters
- ChaosType enum supports both container kills and Redis pauses for dual-subject demos

**Ready to proceed:** All types importable, DemoRunner accepts generic chapters list

---
*Phase: 20-e2e-demo-chaos*
*Completed: 2026-01-27*
