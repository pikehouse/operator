---
phase: 35-runner-layer
plan: 02
subsystem: testing
tags: [eval, tikv, docker-compose, chaos, python-on-whales, httpx, protocol]

# Dependency graph
requires:
  - phase: 35-01
    provides: EvalSubject protocol and Campaign/Trial dataclasses
provides:
  - TiKVEvalSubject class implementing EvalSubject protocol
  - kill_random_tikv() chaos injection function
  - Docker Compose lifecycle management for TiKV cluster
  - PD API state capture with store/region metrics
affects: [35-03, 35-04, 36-analysis-layer]

# Tech tracking
tech-stack:
  added: [TiKVEvalSubject, tikv chaos functions]
  patterns: [asyncio.to_thread for sync docker calls, PD API verification beyond container health]

key-files:
  created:
    - eval/src/eval/subjects/__init__.py
    - eval/src/eval/subjects/tikv/__init__.py
    - eval/src/eval/subjects/tikv/subject.py
    - eval/src/eval/subjects/tikv/chaos.py
  modified: []

key-decisions:
  - "Wrapped all python-on-whales calls with asyncio.to_thread() to avoid blocking async loop"
  - "Verify cluster health via PD API (3 stores Up) not just Docker healthchecks"
  - "Default compose file path calculated relative to repo root from subject.py location"

patterns-established:
  - "EvalSubject implementation pattern: DockerClient with compose_files, async lifecycle"
  - "Chaos injection pattern: Separate chaos.py module with async functions taking DockerClient"
  - "Health verification pattern: Container health + service-specific API checks"

# Metrics
duration: 3min
completed: 2026-01-29
---

# Phase 35 Plan 02: TiKV Eval Subject Summary

**TiKVEvalSubject implementing EvalSubject protocol with Docker Compose lifecycle, PD API state capture, and node_kill chaos injection**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-29T20:02:33Z
- **Completed:** 2026-01-29T20:05:49Z
- **Tasks:** 3
- **Files created:** 4

## Accomplishments

- Implemented TiKVEvalSubject class satisfying @runtime_checkable EvalSubject protocol
- Created chaos.py with kill_random_tikv() async function using SIGKILL
- Docker Compose lifecycle via reset() (down with volumes + up with wait)
- PD API state capture with store count, region count, and per-store health
- Health verification checks both Docker status and PD API (3 stores Up)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create eval subjects directory structure** - `7e4dbc2` (feat)
2. **Task 2: Implement TiKV chaos injection** - `56b1a58` (feat)
3. **Task 3: Implement TiKVEvalSubject** - `0f89116` (feat)

**Deviation commit:** `7d33498` (chore - unnecessary import reordering)
**Plan metadata:** (to be committed)

## Files Created/Modified

- `eval/src/eval/subjects/__init__.py` - Subjects package root
- `eval/src/eval/subjects/tikv/__init__.py` - TiKV subject exports (TiKVEvalSubject)
- `eval/src/eval/subjects/tikv/chaos.py` - kill_random_tikv() chaos injection with asyncio.to_thread
- `eval/src/eval/subjects/tikv/subject.py` - TiKVEvalSubject class with reset, wait_healthy, capture_state, inject_chaos

## Decisions Made

- **asyncio.to_thread wrapper:** All python-on-whales calls wrapped with asyncio.to_thread() because python-on-whales is synchronous and would block async event loop
- **PD API verification:** wait_healthy() checks PD API for 3 stores in Up state, not just Docker container health - ensures cluster formation, not just container running
- **Path calculation:** compose_file defaults to Path(__file__).parents[5] / "subjects" / "tikv" / "docker-compose.yaml" for repo-relative path
- **httpx for PD API:** Used httpx.AsyncClient for PD API calls (already async, no thread wrapper needed)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created eval package foundation**
- **Found during:** Task 1 startup (eval package didn't exist)
- **Issue:** eval package (pyproject.toml, types.py, __init__.py) was missing - couldn't import EvalSubject protocol
- **Fix:** Created minimal eval package with Protocol and dataclasses (later discovered plan 35-01 had already run concurrently)
- **Files created:** eval/pyproject.toml, eval/src/eval/types.py, eval/src/eval/__init__.py
- **Verification:** `uv pip install -e eval/` succeeded, `from eval import EvalSubject` worked
- **Committed in:** 7d33498 (separate commit - though turned out to be unnecessary as 35-01 had already created these files)

---

**Total deviations:** 1 perceived blocking issue (turned out plan 35-01 ran concurrently, deviation commit only reordered imports)
**Impact on plan:** No actual impact - plan executed as written. Deviation commit harmless (import ordering).

## Issues Encountered

- **Concurrent plan execution:** Plan 35-01 was executing concurrently. I didn't see its commits initially, so created eval package foundation thinking it was missing. Discovered later via git log that 35-01 commits 7c7bae9 and 8a7c31f had already created the foundation. My "deviation" commit 7d33498 only changed import order in __init__.py (alphabetizing).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for 35-03 (Trial runner). TiKVEvalSubject provides concrete implementation of EvalSubject protocol that runner can use.

Key deliverables for next phase:
- TiKVEvalSubject can reset() cluster (docker-compose down/up)
- TiKVEvalSubject.wait_healthy() confirms cluster formation (3 stores Up via PD API)
- TiKVEvalSubject.capture_state() returns store/region metrics as JSON dict
- TiKVEvalSubject.inject_chaos("node_kill") kills random TiKV container with SIGKILL
- Protocol verification: isinstance(TiKVEvalSubject(), EvalSubject) returns True

**Pattern established:** All python-on-whales calls use asyncio.to_thread() wrapper. All health checks verify service APIs, not just container status.

---
*Phase: 35-runner-layer*
*Completed: 2026-01-29*
