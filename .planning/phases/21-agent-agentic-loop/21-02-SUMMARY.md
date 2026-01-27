---
phase: 21
plan: 02
status: complete
subsystem: agent
tags: [subprocess, environment, safety-mode, executor]

dependency-graph:
  requires: [21-01]
  provides: ["EXECUTE mode in demo", "env var configuration for agent"]
  affects: [22-01, 22-02]

tech-stack:
  added: []
  patterns: ["environment variable configuration", "subprocess env merging"]

key-files:
  created: []
  modified:
    - demo/tui_integration.py
    - packages/operator-core/src/operator_core/cli/agent.py
    - packages/operator-core/src/operator_core/tui/subprocess.py

decisions:
  - id: "ENV-01"
    choice: "Environment variables for mode configuration"
    reason: "Per research recommendation, env vars simplify subprocess configuration"
    alternatives: ["CLI flags", "config files"]

metrics:
  duration: "~4 min"
  completed: "2026-01-27"
---

# Phase 21 Plan 02: Demo EXECUTE Mode Configuration Summary

Agent subprocess in demo now runs with EXECUTE mode enabled and autonomous execution (no approval required).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add environment variables to agent subprocess spawn | a8ea784 | demo/tui_integration.py |
| 2 | Update CLI to honor safety mode environment variable | 65899d4 | cli/agent.py |
| 3 | Update SubprocessManager to support environment variables | 4455120 | tui/subprocess.py |

## What Was Built

### 1. SubprocessManager Environment Support
Added `env` parameter to `SubprocessManager.spawn()` method:
- Accepts `dict[str, str]` of environment variables
- Merges caller env vars with `os.environ.copy()` (preserves PATH, HOME, etc.)
- Uses merged `subprocess_env` for `asyncio.create_subprocess_exec()`

### 2. Agent CLI Environment Variable Handling
Updated `agent start` command to read safety configuration from environment:
- `OPERATOR_SAFETY_MODE`: "execute" enables action execution, "observe" (default) is read-only
- `OPERATOR_APPROVAL_MODE`: "true" requires approval, "false" (default) is autonomous
- When EXECUTE mode: Creates full action infrastructure (SafetyController, ActionRegistry, ActionAuditor, ActionExecutor)
- Passes executor to AgentRunner to enable complete agentic loop
- Logs mode at startup: "Agent starting in EXECUTE mode (approval_mode=False)"

### 3. Demo Agent Subprocess Configuration
Updated `TUIDemoController.run()` to spawn agent with environment:
```python
agent_proc = await self._subprocess_mgr.spawn(
    "agent",
    [...],
    buffer_size=50,
    env={
        "OPERATOR_SAFETY_MODE": "execute",
        "OPERATOR_APPROVAL_MODE": "false",
    },
)
```

## Key Patterns

### Environment Variable Flow
```
TUIDemoController.run()
    |
    v
SubprocessManager.spawn(env={"OPERATOR_SAFETY_MODE": "execute", ...})
    |
    v
asyncio.create_subprocess_exec(env=subprocess_env)
    |
    v
Agent subprocess reads os.environ["OPERATOR_SAFETY_MODE"]
    |
    v
Creates ActionExecutor with SafetyMode.EXECUTE + approval_mode=False
    |
    v
AgentRunner receives executor, can propose/validate/execute/verify actions
```

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Covered

| ID | Requirement | Status |
|----|-------------|--------|
| DEMO-01 | Demo shows complete agentic loop | Enabled |

## Verification

All verifications passed:
- SubprocessManager.spawn() has `env` parameter
- Environment variable parsing logic correct (EXECUTE mode, approval_mode=False)
- All imports successful
- Code compiles without errors

## Next Phase Readiness

Phase 22 (Demo Integration) is ready:
- Agent subprocess configured for autonomous execution
- Complete agentic loop enabled (propose -> validate -> execute -> verify)
- Both TiKV and rate limiter demos will benefit from this configuration
