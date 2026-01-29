# Project State: Operator

## Current Position

**Milestone:** v3.2 Evaluation Harness
**Phase:** 35 - Runner Layer (COMPLETE)
**Plan:** 4/4 complete
**Status:** Phase 35 verified, ready for Phase 36
**Last activity:** 2026-01-29 — Phase 35 complete

Progress: ████░░░░░░░░░░░░░░░░ (v3.2: 20%)

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
| v3.1 | SHIPPED | 2026-01-29 |
| v3.2 | IN PROGRESS | 2026-01-29 |

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
| milestones/v3.1-ROADMAP.md | v3.1 roadmap (2 phases) |

## Current Milestone: v3.2 Evaluation Harness

**Milestone Goal:** Build eval/ — a standalone harness that injects chaos, monitors agent problem-solving, grades performance, and provides historical analysis.

**Roadmap:** .planning/milestones/v3.2-ROADMAP.md
**Requirements:** .planning/REQUIREMENTS.md (30 requirements)

**Phases:**
- Phase 35: Runner Layer (11 requirements)
- Phase 36: Analysis Layer (9 requirements)
- Phase 37: Viewer Layer (5 requirements)
- Phase 38: Chaos Expansion (4 requirements)
- Phase 39: Config Variants (3 requirements)

**Status:** Phase 35 complete, ready for Phase 36

**Next:** `/gsd:plan-phase 36` to plan Analysis Layer

## Session Continuity

**Last session:** 2026-01-29
**Stopped at:** Phase 35 complete
**Resume file:** None
**Next:** `/gsd:plan-phase 36` to plan Analysis Layer

---
*State updated: 2026-01-29 (Phase 35 complete)*

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |
