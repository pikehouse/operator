---
phase: 30-core-agent
plan: 01
subsystem: infra
tags: [docker, python, asyncio, shell, audit, json]

# Dependency graph
requires:
  - phase: none
    provides: greenfield v3.0 milestone
provides:
  - Agent container with Python 3.12 and SRE tooling (Docker CLI, curl, jq, networking tools)
  - shell() pure execution function with timeout handling
  - SessionAuditor class for conversation-level JSON audit logging
affects: [31-agent-loop, 32-integration-demo]

# Tech tracking
tech-stack:
  added: [python:3.12-slim, anthropic, httpx, redis, pyyaml, pandas, numpy, prometheus-client]
  patterns: [pure execution functions, session-based audit logging, asyncio subprocess execution]

key-files:
  created:
    - docker/agent/Dockerfile
    - packages/operator-core/src/operator_core/agent_lab/__init__.py
    - packages/operator-core/src/operator_core/agent_lab/tools.py
    - packages/operator-core/src/operator_core/agent_lab/audit.py
  modified: []

key-decisions:
  - "shell() is a pure execution function with no internal logging - Phase 31 agent loop handles audit logging"
  - "Session ID format: {timestamp}-{uuid4[:8]} for timestamped audit files"
  - "120 second default timeout for shell commands to allow longer operations like docker pulls"
  - "No command sanitization - direct subprocess shell execution (let Claude cook)"

patterns-established:
  - "Tool functions return structured dicts (stdout, stderr, exit_code, timed_out)"
  - "Audit logging separated from tool execution - integration point pattern for agent loop"
  - "Timeout handling with process kill and zombie prevention via await proc.wait()"

# Metrics
duration: 3min
completed: 2026-01-28
---

# Phase 30 Plan 01: Core Agent Summary

**Agent container with Python 3.12 slim, full SRE tooling, pure shell() execution function, and session-based JSON audit logging**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-28T09:40:09Z
- **Completed:** 2026-01-28T09:43:05Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Docker agent container builds successfully with all SRE tools (curl, wget, jq, vim, git, docker CLI, networking tools, Python packages)
- shell() tool executes arbitrary commands with structured output and timeout handling
- SessionAuditor logs complete conversation history to timestamped JSON files
- Clean integration point for Phase 31 agent loop via log_tool_call() method

## Task Commits

Each task was committed atomically:

1. **Task 1: Create agent container Dockerfile** - `98aaaa7` (feat)
2. **Task 2: Implement shell() tool** - `a8733eb` (feat)
3. **Task 3: Implement SessionAuditor** - `ccd1deb` (feat)

## Files Created/Modified
- `docker/agent/Dockerfile` - Agent container with Python 3.12-slim, CLI tools (curl, wget, jq, vim, git, networking tools, docker.io), Python packages (anthropic, httpx, redis, pyyaml, pandas, numpy, prometheus-client)
- `packages/operator-core/src/operator_core/agent_lab/__init__.py` - Package exports for shell and SessionAuditor
- `packages/operator-core/src/operator_core/agent_lab/tools.py` - Pure execution shell() function with asyncio subprocess, timeout handling, structured dict return
- `packages/operator-core/src/operator_core/agent_lab/audit.py` - SessionAuditor class for conversation history logging to JSON

## Decisions Made

**Architecture:**
- shell() is a pure execution function with no internal logging - Phase 31 agent loop will call SessionAuditor.log_tool_call() after each shell() execution
- This separation keeps tool functions simple and puts conversation management in the agent loop

**Session ID format:**
- Format: `{timestamp}-{uuid4[:8]}` (e.g., 2026-01-28T09-42-35-2886f5df)
- Timestamp provides chronological ordering, UUID component ensures uniqueness

**Timeout handling:**
- Default 120 seconds to allow longer operations like docker pulls
- On timeout: kill process, await proc.wait() for zombie prevention, return timed_out=True

**Command execution:**
- No sanitization or validation - commands passed directly to create_subprocess_shell
- "Let Claude cook" philosophy - container isolation is the safety boundary

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks executed smoothly with verification tests passing on first attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 31 (Agent Loop):**
- Agent container Dockerfile complete and builds successfully (675MB image)
- shell() tool ready for tool calling with structured return format
- SessionAuditor ready for agent loop integration via log_tool_call() method
- All verification criteria met

**No blockers.**

The foundation is in place for Phase 31 to implement the ~200 line agent loop that:
1. Detects unhealthy state from Prometheus
2. Runs Claude conversation loop with tool execution
3. Logs all interactions via SessionAuditor.log_tool_call()
4. Saves complete session as audit log JSON

---
*Phase: 30-core-agent*
*Completed: 2026-01-28*
