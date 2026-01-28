---
phase: 32-integration-demo
plan: 03
subsystem: demo
tags: [tui, agent_lab, autonomous-agent, demo-integration]

# Dependency graph
requires:
  - phase: 31-agent-loop
    provides: agent_lab module with polling loop and tool execution
  - phase: 30-core-agent
    provides: shell() tool and audit infrastructure
provides:
  - TUI demo spawns agent_lab subprocess instead of old agent CLI
  - Real-time streaming of Claude's reasoning and tool calls to Agent panel
  - Demo chapters describe autonomous agent behavior
affects: [32-04, demo-validation, agent-lab-observability]

# Tech tracking
tech-stack:
  added: []
  patterns: ["agent_lab subprocess integration with TUI", "autonomous demo narration"]

key-files:
  created: []
  modified:
    - demo/tui_integration.py
    - demo/tikv.py

key-decisions:
  - "Use agent_lab module directly instead of CLI wrapper"
  - "Increased buffer size to 100 for verbose agent output"
  - "Updated demo chapters to emphasize autonomous operation (no playbook, no approval)"

patterns-established:
  - "TUI spawns agent_lab with database path argument"
  - "Demo narration describes autonomous agent workflow (shell, diagnose, fix, verify)"

# Metrics
duration: 1min
completed: 2026-01-28
---

# Phase 32 Plan 03: TUI Agent Lab Integration Summary

**TUI demo now spawns agent_lab subprocess streaming Claude's autonomous operation to Agent panel in real-time**

## Performance

- **Duration:** 1 min
- **Started:** 2026-01-28T20:41:25Z
- **Completed:** 2026-01-28T20:43:01Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- TUI spawns agent_lab module instead of deprecated agent CLI daemon
- Agent panel displays Claude's reasoning, tool calls, and results as they happen
- Demo chapters updated to describe autonomous workflow (ticket polling, shell investigation, diagnosis, fix, verify)
- Buffer size increased to 100 lines for verbose agent output

## Task Commits

Each task was committed atomically:

1. **Task 1: Update TUI to spawn agent_lab subprocess** - `ac9f9b4` (feat)
2. **Task 2: Update TiKV demo chapters for autonomous agent** - `39fd0ef` (feat)

## Files Created/Modified
- `demo/tui_integration.py` - Updated agent subprocess spawn to use agent_lab module with ~/.operator/tickets.db
- `demo/tikv.py` - Updated Stage 5, 6, 7 chapters to describe autonomous agent operation

## Decisions Made

**1. Use agent_lab module directly**
- Spawns `python -m operator_core.agent_lab <db_path>` instead of CLI wrapper
- More direct, fewer layers of indirection
- Matches how agent_lab is intended to run (module entry point)

**2. Increased buffer size to 100**
- Agent output is verbose (reasoning, commands, results)
- 50-line buffer was too small for multi-step operations
- 100 lines provides better context visibility in TUI panel

**3. Simplified environment variables**
- Removed `OPERATOR_APPROVAL_MODE` (not relevant for lab)
- Kept `OPERATOR_SAFETY_MODE=execute` for agent behavior

**4. Updated demo narration for autonomous flow**
- Stage 5: Mentions ticket creation and agent_lab polling
- Stage 6: Describes autonomous operation flow (investigate, diagnose, fix, verify)
- Stage 7: Notes that agent may restart container itself
- Emphasizes "no playbook" approach - Claude figures it out

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - straightforward integration of existing components.

## Next Phase Readiness

**Ready for Phase 32-04 (Docker Compose integration):**
- TUI now expects agent_lab to be running
- Agent panel will stream real-time output
- Demo chapters accurately describe autonomous operation

**Note for Phase 32-04:**
- Ensure tickets.db is accessible to agent container
- Verify agent_lab output format matches TUI expectations
- Test fault injection → ticket creation → agent pickup → resolution flow

**Blockers:** None

**Concerns:** None

---
*Phase: 32-integration-demo*
*Completed: 2026-01-28*
