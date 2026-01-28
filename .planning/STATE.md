# Project State: Operator

## Current Position

**Milestone:** v3.1 Demo Update
**Phase:** 33 - Agent Database Integration
**Plan:** 02 of 4
**Status:** In progress
**Last activity:** 2026-01-28 — Completed 33-02-PLAN.md (Agent loop signal handling)

Progress: ██░░ (Phase 33: 2/4 plans complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-28 after v3.0)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — and autonomous action without predefined playbooks.

**Philosophy:** "Give Claude a full kitchen, not a menu of 10 dishes."

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | SHIPPED | 2026-01-27 |
| v2.2 | SHIPPED | 2026-01-27 |
| v2.3 | ARCHIVED | 2026-01-28 |
| v3.0 | SHIPPED | 2026-01-28 |
| v3.1 | IN PROGRESS | 2026-01-28 |

See: .planning/MILESTONES.md

## v3.0 Delivered

**Philosophy:** Give Claude autonomy and a well-equipped environment. Safety via isolation (Docker container), not restrictions. Audit everything, approve nothing.

**Key deliverables:**
- Agent container with Python 3.12, Docker CLI, SRE tools
- shell(command, reasoning) tool with 120s timeout
- Core agent loop (198 lines) using tool_runner
- Database audit logging with reasoning, tool_call, tool_result entries
- Haiku summarization for concise audit trail
- Docker Compose integration with TiKV network
- CLI audit commands (operator audit list/show)
- Autonomous diagnosis and remediation validated (TiKV failure scenario)

**Evidence:** Session 2026-01-28T20-54-48-3a029c12 shows Claude diagnosing and fixing TiKV failure autonomously.

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
| milestones/v3.0-ROADMAP.md | v3.0 roadmap (3 phases) |
| milestones/v3.0-REQUIREMENTS.md | v3.0 requirements (14 total) |
| milestones/v3.0-MILESTONE-AUDIT.md | v3.0 audit report |

## Current Milestone: v3.1 Demo Update

**Goal:** Fix TUI demo to work with v3.0 agent_lab architecture

**Target features:**
- TUI demo works with v3.0 agent_lab (not old tickets table)
- Agent panel shows autonomous agent output
- Both TiKV and ratelimiter demos functional
- Demo chapters flow correctly with new architecture

**Roadmap:**
- Phase 33: Agent Database Integration (4 requirements)
- Phase 34: Demo End-to-End Validation (3 requirements)

**Next:** `/gsd:plan-phase 33`

## Session Continuity

**Last session:** 2026-01-28T23:46:14Z
**Stopped at:** Completed 33-02-PLAN.md
**Resume file:** None
**Next:** Execute 33-03-PLAN.md or continue Phase 33 planning

---
*State updated: 2026-01-28 (33-02 complete)*

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |
