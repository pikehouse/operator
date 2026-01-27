---
phase: 20-e2e-demo-chaos
plan: 02
subsystem: demo
tags: [tikv, chaos, health-polling, docker, python-on-whales, httpx]

# Dependency graph
requires:
  - phase: 20-01
    provides: Shared demo infrastructure (Chapter, DemoRunner, HealthPollerProtocol)
provides:
  - TiKV demo entry point with 8-chapter flow
  - TiKVHealthPoller implementing HealthPollerProtocol
  - TiKV chaos functions (kill_random_tikv, restart_container)
affects: [20-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Health poller returns generic dict (not typed dataclass) for framework flexibility"
    - "Chaos functions as standalone async functions (not class methods)"
    - "Global state for killed container tracking in demo entry point"
    - "create_fault_chapter and create_recovery_chapter factories for chapter callbacks"

key-files:
  created:
    - demo/tikv_health.py
    - demo/tikv_chaos.py
    - demo/tikv.py
  modified: []

key-decisions:
  - "TiKVHealthPoller returns generic dict (not ClusterHealth dataclass) for framework flexibility"
  - "Chaos functions as standalone async functions (not class) for simplicity"
  - "Global _killed_container variable for recovery chapter callback"
  - "Countdown uses asyncio.sleep instead of Rich Live display"

patterns-established:
  - "Health poller pattern: async poll loop with asyncio.Event shutdown coordination"
  - "Chaos pattern: python-on-whales DockerClient with compose_files list"
  - "Chapter factory pattern: create_fault_chapter and create_recovery_chapter return Chapter with callbacks"

# Metrics
duration: 2min
completed: 2026-01-27
---

# Phase 20 Plan 02: TiKV Demo Integration Summary

**TiKV demo with 8-chapter flow, health polling via PD API, and container kill/restart chaos using shared demo framework**

## Performance

- **Duration:** 2min 23s
- **Started:** 2026-01-27T02:56:51Z
- **Completed:** 2026-01-27T02:59:14Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- TiKVHealthPoller polls PD API for cluster health and returns generic dict for framework flexibility
- TiKV chaos functions kill random TiKV containers and restart them using python-on-whales
- TiKV demo entry point with 8 chapters matching existing TUI flow, proving abstraction works

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TiKV health poller implementing HealthPollerProtocol** - `e954fbb` (feat)
2. **Task 2: Create TiKV chaos injection module** - `962f64c` (feat)
3. **Task 3: Create TiKV demo entry point with chapters** - `0eeabcb` (feat)

## Files Created/Modified

### Created
- `demo/tikv_health.py` (180 lines) - TiKVHealthPoller polls PD /stores and /health endpoints, returns generic dict with nodes list
- `demo/tikv_chaos.py` (89 lines) - kill_random_tikv and restart_container functions using python-on-whales, TIKV_CHAOS_CONFIG
- `demo/tikv.py` (204 lines) - TiKV demo entry point with 8 chapters (Welcome → Complete), fault/recovery chapter factories

## Decisions Made

**1. Health poller returns generic dict instead of typed ClusterHealth**
- Enables demo framework to work with any subject's health data
- Simplified from ClusterHealthPoller in operator_core/tui/health.py
- Dict structure: `{"nodes": [...], "has_issues": bool, "last_updated": datetime}`

**2. Chaos functions as standalone async functions (not class)**
- Simpler than class-based approach from operator_core/tui/fault.py
- Demo entry point wires them into chapter callbacks directly
- Global _killed_container tracks state for recovery

**3. Countdown uses asyncio.sleep instead of Rich Live**
- Simpler than TUI countdown with live updates
- Prints countdown messages with print() statements
- DemoRunner handles display, not chaos callbacks

**4. Chapter factory pattern for fault and recovery**
- create_fault_chapter returns Chapter with on_enter callback that runs countdown + kill
- create_recovery_chapter returns Chapter with on_enter callback that restarts container
- Closures capture compose_file and global _killed_container state

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready for Plan 20-03: Rate Limiter Demo Integration**
- TiKV demo proves the abstraction works for existing subject
- Same pattern can be applied to rate limiter (health poller + chaos + chapters)
- DemoRunner is subject-agnostic and tested with TiKV

**Concerns:**
- Demo requires manual cluster startup (not automated) - acceptable for demo
- Keyboard input uses blocking sys.stdin.read() in executor - acceptable for simple demo
- No subprocess monitors or AI diagnosis integration yet - deferred to full TUI integration

---
*Phase: 20-e2e-demo-chaos*
*Completed: 2026-01-27*
