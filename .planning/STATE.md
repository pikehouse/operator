# Project State: Operator

## Current Position

**Milestone:** v3.0 Operator Laboratory
**Phase:** Phase 30 - Core Agent (IN PROGRESS)
**Plan:** 30-01 complete (1 of 1)
**Status:** Phase 30 complete - ready for Phase 31
**Last activity:** 2026-01-28 — Completed 30-01-PLAN.md (agent container, shell tool, audit logging)

Progress: [███░░░░░░░] 33% (Phase 1 of 3 complete)

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
| 31 | Agent Loop | Pending |
| 32 | Integration & Demo | Pending |

**Total:** 3 phases

### Phase 30: Core Agent
- Agent container Dockerfile (Python 3.12, Docker CLI, standard tools)
- `shell(command, reasoning)` — execute any command, log with reasoning
- `web_search(query, reasoning)` — search for docs/solutions
- `web_fetch(url, reasoning)` — read specific pages
- Audit log format (JSON, per-session)

### Phase 31: Agent Loop
- Health check trigger (poll Prometheus or receive alerts)
- Claude conversation loop with tool execution
- Session management (start, execute, save audit log)
- System prompt for SRE agent
- Core loop < 200 lines

### Phase 32: Integration & Demo
- Docker Compose with agent container alongside subjects
- Agent can reach Prometheus, subjects, internet
- TiKV failure scenario validated
- Audit log review tooling

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

**Path to production:**
- Lab → Production: shell(cmd) → propose(cmd) → approve() → shell(cmd)
- The audit layer carries forward unchanged

## Session Continuity

**Last session:** 2026-01-28T09:43:05Z
**Stopped at:** Completed 30-01-PLAN.md - agent container, shell() tool, SessionAuditor
**Resume file:** None
**Next:** Phase 31 - Agent Loop implementation

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |

---
*State updated: 2026-01-28 (Phase 30 complete)*
