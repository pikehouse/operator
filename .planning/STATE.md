# Project State: Operator

## Current Position

**Milestone:** v3.0 Operator Laboratory
**Phase:** Phase 32 - Integration & Demo (IN PROGRESS)
**Plan:** 32-01, 32-02, 32-03 complete (3 of 4)
**Status:** Phase 32 in progress
**Last activity:** 2026-01-28 — Completed 32-01-PLAN.md (Agent container configuration)

Progress: [███████░░░] 75% (Phase 2 of 3 complete, Phase 3 in progress)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-27)

**Philosophy shift:** Give Claude autonomy and a well-equipped environment, rather than constraining it to predefined actions. Safety via isolation (Docker), not restrictions. Audit everything, approve nothing.

**Core principle:** The difference between giving someone a menu of 10 dishes vs giving them a full kitchen. We want the kitchen.

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | SHIPPED | 2026-01-27 |
| v2.2 | SHIPPED | 2026-01-27 |
| v2.3 | ARCHIVED | 2026-01-28 |
| v3.0 | IN PROGRESS | — |

See: .planning/MILESTONES.md

## v3.0 Phase Overview

| Phase | Goal | Status |
|-------|------|--------|
| 30 | Core Agent | ✓ Complete |
| 31 | Agent Loop | ✓ Complete |
| 32 | Integration & Demo | Pending |

**Total:** 3 phases

### Phase 30: Core Agent
- Agent container Dockerfile (Python 3.12, Docker CLI, standard tools)
- `shell(command, reasoning)` — execute any command, log with reasoning
- `web_search(query, reasoning)` — search for docs/solutions
- `web_fetch(url, reasoning)` — read specific pages
- Audit log format (JSON, per-session)

### Phase 31: Agent Loop ✓
- Core ~198 line agent loop using tool_runner
- Polls database for tickets every 1 second
- Synchronous shell() with @beta_tool decorator
- Haiku summarization for audit logs
- Database audit logging (agent_sessions, agent_log_entries)
- Tool call and tool result logging with exit codes
- SRE system prompt for autonomous operation
- Ticket status updates (resolved/escalated)

### Phase 32: Integration & Demo (In Progress)
- Docker Compose with agent container alongside subjects
- Agent can reach Prometheus, subjects, internet
- TiKV failure scenario validated
- Audit log review tooling
- ✓ 32-03: TUI spawns agent_lab subprocess with real-time streaming

## What's Being Eliminated

| Component | Reason |
|-----------|--------|
| ActionRegistry | Claude knows what commands exist |
| Action definitions with schemas | Claude knows docker/bash syntax |
| Parameter validation | Errors are feedback, not gates |
| DockerExecutor, HostExecutor, ScriptExecutor | Just shell |
| Approval workflows | Lab doesn't need approval |
| Structured DiagnosisOutput | Claude explains in natural language |
| SubjectProtocol abstraction | Claude queries metrics directly |

## What's Being Kept

| Component | Reason |
|-----------|--------|
| Audit logging | Visibility into what happened |
| Monitor/alerting | Need to know something's wrong |
| Docker Compose environment | The lab itself |
| Prometheus | Metrics Claude can query |

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | v1.0 roadmap (6 phases) |
| milestones/v1.0-REQUIREMENTS.md | v1.0 requirements (19 total) |
| milestones/v1.1-ROADMAP.md | v1.1 roadmap (5 phases) |
| milestones/v1.1-REQUIREMENTS.md | v1.1 requirements (11 total) |
| milestones/v1.1-MILESTONE-AUDIT.md | v1.1 audit report |
| milestones/v2.0-ROADMAP.md | v2.0 roadmap (4 phases) |
| milestones/v2.0-REQUIREMENTS.md | v2.0 requirements (17 total) |
| milestones/v2.1-ROADMAP.md | v2.1 roadmap (5 phases) |
| milestones/v2.2-ROADMAP.md | v2.2 roadmap (2 phases) |
| milestones/v2.3-ROADMAP.md | v2.3 roadmap (7 phases, 4 complete) |

## v3.0 Design Decisions

**The Tool:**
1. `shell(command, reasoning)` — Execute any bash command, pure execution function (agent loop handles logging)

**Container environment:**
- Python 3.12 base image (python:3.12-slim)
- Docker CLI (docker.io package)
- Standard tools: curl, wget, jq, vim, git, netcat, dig, ping, htop, tcpdump, traceroute, nmap
- Python packages: anthropic, httpx, redis, pyyaml, pandas, numpy, prometheus-client

**Audit logging:**
- SessionAuditor class logs full conversation history to JSON
- Session ID format: {timestamp}-{uuid4[:8]}
- Integration point: agent loop calls SessionAuditor.log_tool_call() after each shell() execution

**Safety model:**
- Container is the sandbox
- If Claude breaks everything, docker-compose down/up resets
- Audit everything, restrict nothing

**Architecture decisions (Phase 30):**
- shell() is a pure execution function with no internal logging
- Phase 31 agent loop owns conversation management and audit logging
- No command sanitization - direct subprocess execution ("let Claude cook")
- 120 second default timeout for longer operations like docker pulls

**Architecture decisions (Phase 31):**
- Synchronous shell() for tool_runner compatibility (tool_runner requires sync tools)
- Haiku summarization before database logging for concise audit trail
- 1-second polling interval balances responsiveness and database load
- Database audit logging instead of JSON files for queryability
- Separate sync and async shell functions (async in tools.py for compatibility, sync in loop.py for tool_runner)
- Global state for tool result capture (_last_shell_result) since tool_runner doesn't yield results separately
- Tool calls logged on ToolUseBlock detection, results logged after execution completes

**Architecture decisions (Phase 32-02):**
- Direct SQLite access for read-only CLI audit queries (simpler than abstraction layer)
- Synchronous sqlite3 for CLI commands (no concurrency benefit from async)
- Haiku summaries displayed by default (per CONTEXT.md)


**Architecture decisions (Phase 32-01):**
- Agent container uses external network (tikv_default) to join TiKV network
- Docker socket mounted for container control (sibling access pattern)
- ~/.operator volume mount for shared database between host and container
- operator-core and operator-protocols installed in development mode



- Increased agent buffer size to 100 lines for verbose reasoning/tool output
- Demo chapters emphasize autonomous operation (no playbook, no approval)
- Agent panel streams real-time Claude reasoning and tool execution

**Path to production:**
- Lab → Production: shell(cmd) → propose(cmd) → approve() → shell(cmd)
- The audit layer carries forward unchanged

## Session Continuity

**Last session:** 2026-01-28T20:41:27Z
**Stopped at:** Completed 32-02-PLAN.md (CLI audit commands)
**Resume file:** None
**Next:** 32-04 - End-to-end validation
*State updated: 2026-01-28 (Phase 32 in progress - 32-01, 32-02, 32-03 complete)*
## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |

---
*State updated: 2026-01-28 (Phase 32 in progress - 32-03 complete)*
