---
phase: 06-chaos-demo
plan: 01
subsystem: demo
tags: [rich, asyncio, docker, claude-api, chaos-engineering]

# Dependency graph
requires:
  - phase: 05-ai-diagnosis
    provides: AgentRunner, ContextGatherer, DiagnosisOutput patterns
  - phase: 04-monitor-loop
    provides: TicketDB, MonitorLoop patterns
  - phase: 03-local-cluster
    provides: docker-compose.yaml, YCSB container
provides:
  - ChaosDemo orchestrator class
  - Rich terminal output patterns for demos
  - Container-to-store ID mapping
  - One-shot diagnosis pattern (vs daemon loop)
affects: [06-02 demo CLI command]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rich Live display for countdown timers"
    - "Stage banners with console.rule()"
    - "Container name to store ID mapping via PD API"
    - "One-shot Claude diagnosis (bypass daemon loop)"

key-files:
  created:
    - packages/operator-core/src/operator_core/demo/__init__.py
    - packages/operator-core/src/operator_core/demo/chaos.py
  modified: []

key-decisions:
  - "One-shot diagnosis instead of AgentRunner daemon per RESEARCH.md Pitfall 5"
  - "Container-to-store mapping via PD API address matching"
  - "SIGKILL for realistic failure simulation (not graceful stop)"
  - "2-second detection polling interval"

patterns-established:
  - "Rich Live for async progress displays"
  - "Stage banner pattern for multi-step demos"
  - "try/finally cleanup for fault injection demos"

# Metrics
duration: 3min
completed: 2026-01-25
---

# Phase 6 Plan 01: ChaosDemo Summary

**ChaosDemo orchestrator with Rich terminal output, random TiKV kill, live detection countdown, and one-shot AI diagnosis**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-25T02:57:29Z
- **Completed:** 2026-01-25T03:00:08Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- ChaosDemo dataclass orchestrating full demo lifecycle (cluster health, YCSB load, fault injection, detection, diagnosis, cleanup)
- Rich terminal output with stage banners, colored status messages, and interactive prompts
- Live detection countdown using Rich Live display with 2-second polling
- One-shot Claude diagnosis integration following existing AgentRunner patterns
- Container-to-store ID mapping via PD API hostname matching

## Task Commits

Each task was committed atomically:

1. **Task 1: Create demo module with ChaosDemo class** - `4d69ac4` (feat)
2. **Task 2: Implement detection and diagnosis wiring** - `87b5016` (fix)

## Files Created/Modified
- `packages/operator-core/src/operator_core/demo/__init__.py` - Demo module exports (ChaosDemo)
- `packages/operator-core/src/operator_core/demo/chaos.py` - ChaosDemo orchestrator class (434 lines)

## Decisions Made
- **One-shot diagnosis:** Per RESEARCH.md Pitfall 5, don't run full AgentRunner loop - invoke Claude directly for single diagnosis in demo context
- **Container name parsing:** Extract service name (tikv0) from full container name (operator-tikv-tikv0-1) by splitting on hyphen and finding tikv* part
- **2-second polling:** Balance between responsiveness and not overwhelming the database during detection wait
- **SIGKILL not SIGTERM:** Use docker.kill() for immediate termination simulating sudden node crash

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Claude API parameter name**
- **Found during:** Task 2
- **Issue:** Used `output_schema` and `output_parsed` instead of `output_format` and `parsed_output`
- **Fix:** Aligned with existing AgentRunner patterns
- **Files modified:** packages/operator-core/src/operator_core/demo/chaos.py
- **Verification:** Import succeeds, method signatures match existing code
- **Committed in:** 87b5016

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** API consistency fix required for correctness. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ChaosDemo class ready for CLI integration
- Plan 02 will add `operator demo chaos` CLI command that instantiates and runs ChaosDemo
- All existing components (TicketDB, TiKVSubject, AgentRunner patterns) integrate cleanly

---
*Phase: 06-chaos-demo*
*Completed: 2026-01-25*
