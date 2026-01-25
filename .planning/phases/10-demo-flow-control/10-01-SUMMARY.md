---
phase: 10-demo-flow-control
plan: 01
subsystem: tui
tags: [keyboard, chapters, demo-flow, asyncio, termios, select]

# Dependency graph
requires:
  - phase: 09-cluster-health-display
    provides: TUIController with TaskGroup and panel layout
provides:
  - KeyboardTask for async keyboard input
  - Chapter/DemoState dataclasses for demo progression
  - 7-chapter demo flow with narration
  - Progress indicator [X/7] for visual feedback
affects: [11-fault-workflow-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Direct stdin reading with select() timeout
    - cbreak terminal mode for single keypress detection
    - Chapter state machine with advance/get_current

key-files:
  created:
    - packages/operator-core/src/operator_core/tui/keyboard.py
    - packages/operator-core/src/operator_core/tui/chapters.py
  modified:
    - packages/operator-core/src/operator_core/tui/controller.py

key-decisions:
  - "Direct stdin reading over readchar library to avoid terminal mode conflicts"
  - "select() with 0.3s timeout for responsive shutdown without blocking"
  - "cbreak mode (not raw) for proper keypress detection while preserving Ctrl+C"
  - "Progress indicator [X/7] for visual chapter navigation feedback"

patterns-established:
  - "Keyboard input via select() timeout + direct stdin read in executor"
  - "Chapter state machine: frozen Chapter dataclass + mutable DemoState"

# Metrics
duration: ~45min
completed: 2026-01-25
---

# Phase 10 Plan 01: Demo Flow Control Summary

**KeyboardTask with direct stdin reading and 7-chapter demo progression with progress indicator [X/7]**

## Performance

- **Duration:** ~45 min (including debugging iterations)
- **Started:** 2026-01-25
- **Completed:** 2026-01-25
- **Tasks:** 2 auto + 1 checkpoint
- **Files modified:** 3

## Accomplishments

- KeyboardTask class with direct stdin reading (avoiding readchar terminal conflicts)
- Chapter/DemoState dataclasses with 7 demo chapters matching ChaosDemo stages
- TUIController integration with keyboard task in TaskGroup
- Progress indicator [X/7] for visual feedback on chapter position
- Clean shutdown via Q key without terminal hang

## Task Commits

Each task was committed atomically:

1. **Task 1: Create keyboard.py and chapters.py modules** - `dd287c9` (feat)
2. **Task 2: Integrate keyboard and narration into TUIController** - `9a83111` (feat)

**Bug fixes during development:**
3. **Use script file for TUI input** - `beb4e7f` (fix)
4. **Add progress indicator** - `ee755a4` (fix)
5. **Use select() timeout for shutdown** - `c817af7` (fix)
6. **Set cbreak mode for keypress detection** - `48636f2` (fix)
7. **Read stdin directly** - `03a2663` (fix)

## Files Created/Modified

- `packages/operator-core/src/operator_core/tui/keyboard.py` - KeyboardTask with select-based timeout and direct stdin reading
- `packages/operator-core/src/operator_core/tui/chapters.py` - Chapter/DemoState dataclasses with 7 DEMO_CHAPTERS
- `packages/operator-core/src/operator_core/tui/controller.py` - Integrated keyboard task and narration updates

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Direct stdin reading over readchar | readchar's terminal mode changes conflicted with Rich Live context |
| select() with 0.3s timeout | Allows responsive shutdown without CPU-intensive polling |
| cbreak mode (not raw) | Enables single keypress detection while preserving Ctrl+C signal |
| Progress indicator [X/7] | Provides visual feedback for presenter to know chapter position |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] readchar terminal mode conflicts**
- **Found during:** Task 2 (TUIController integration testing)
- **Issue:** readchar's terminal mode changes conflicted with Rich Live context, causing no keypress detection
- **Fix:** Replaced readchar with direct stdin reading using select() and termios
- **Files modified:** keyboard.py
- **Verification:** Keypresses now detected reliably
- **Committed in:** `03a2663`

**2. [Rule 1 - Bug] Keyboard hangs on Ctrl+C**
- **Found during:** Task 2 verification
- **Issue:** Blocking readkey call prevented clean shutdown on Ctrl+C
- **Fix:** Used select() with timeout so executor thread returns quickly
- **Files modified:** keyboard.py
- **Verification:** Ctrl+C exits cleanly without hanging
- **Committed in:** `c817af7`

**3. [Rule 2 - Missing Critical] No visual progress feedback**
- **Found during:** Checkpoint verification
- **Issue:** Presenter had no indication of current chapter position
- **Fix:** Added get_progress() method returning "[X/7]" and integrated into narration panel
- **Files modified:** chapters.py, controller.py
- **Verification:** Progress indicator visible in narration panel
- **Committed in:** `ee755a4`

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 missing critical)
**Impact on plan:** All fixes necessary for correct keyboard operation. readchar library proved incompatible with Rich Live context, requiring direct implementation.

## Issues Encountered

- **readchar incompatibility:** The readchar library's terminal mode handling conflicted with Rich Live context. Solved by implementing direct stdin reading with select() and termios.
- **Keyboard input requires TTY:** TUI keyboard input only works when run with a real terminal (not piped stdin). This is expected behavior for interactive demos.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 11:**
- Keyboard input and chapter progression working
- TUIController has demo state management
- Foundation ready for fault injection workflow integration

**No blockers identified.**

---
*Phase: 10-demo-flow-control*
*Completed: 2026-01-25*
