# Project State: Operator

## Current Position

**Milestone:** v2.1 Multi-Subject Support (Rate Limiter)
**Phase:** 16 of 20 (Core Abstraction Refactoring)
**Plan:** — (ready to plan)
**Status:** Ready to plan Phase 16
**Last activity:** 2026-01-26 - Roadmap created for v2.1

Progress: [..........] 0% (0/5 phases)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-26)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — proving the abstraction works for novel, out-of-distribution systems.

**Current focus:** Phase 16 — Decouple operator-core from TiKV-specific types so any Subject can be monitored

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | IN PROGRESS | — |

See: .planning/MILESTONES.md

## v2.1 Phase Overview

| Phase | Goal | Requirements |
|-------|------|--------------|
| 16 | Core Abstraction Refactoring | CORE-01 through CORE-05 (5) |
| 17 | Rate Limiter Service Foundation | RLSVC-01 through RLSVC-04 (4) |
| 18 | Docker Compose Environment | RLSVC-05, DEMO-01 (2) |
| 19 | operator-ratelimiter Package | RLPKG-*, MON-*, ACT-* (11) |
| 20 | E2E Demo & Chaos | DEMO-02 through DEMO-04 (3) |

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

## Accumulated Context

**Decisions from prior milestones:**
- Observe-only first - proved AI diagnosis quality before action
- Protocol-based abstractions - Subject and DeploymentTarget extensible
- Subprocess isolation for TUI - daemons run as real processes
- httpx, Pydantic, aiosqlite stack - proven across 3 milestones

**Key decisions from v2.0:**
- Pydantic BaseModel for action types (validation + serialization)
- Default to OBSERVE mode (safe by default, explicit opt-in for execution)
- Kill switch cancels pending AND switches to OBSERVE mode
- Fire-and-forget action semantics for PD API calls
- Tools use same ActionDefinition model with action_type=ActionType.TOOL

**Research flags for v2.1:**
- Phase 16 (Core Refactoring): Complex architectural change - audit TiKV coupling first
- Phase 17 (Lua Scripts): Verify atomic patterns prevent race conditions

## Session Continuity

**Last session:** 2026-01-26
**Stopped at:** Roadmap created for v2.1 milestone
**Resume with:** `/gsd:plan-phase 16` to plan Core Abstraction Refactoring

## Open Issues

*None*

---
*State updated: 2026-01-26 (v2.1 roadmap created)*
