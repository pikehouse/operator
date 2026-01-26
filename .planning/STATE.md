# Project State: Operator

## Current Position

**Milestone:** v2.0 Agent Actions
**Phase:** 13 - TiKV Subject Actions (In progress)
**Plan:** 1 of 1 in current phase
**Status:** Plan 01 complete
**Last activity:** 2026-01-26 - Completed 13-01-PLAN.md

**Progress:** [█████████████████████] 100% (1/1 plans in Phase 13)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems - not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

**Current focus:** v2.0 Agent Actions - enabling the agent to execute its recommendations via PD API actions with human approval gates.

## v2.0 Phase Overview

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 12 | Action Foundation | 7 | COMPLETE |
| 13 | TiKV Subject Actions | 4 | COMPLETE |
| 14 | Approval Workflow | 3 | Pending |
| 15 | Workflow Actions | 3 | Pending |

**Total requirements:** 17
**Mapped:** 17/17

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | In progress | - |

See: .planning/MILESTONES.md

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | v1.0 roadmap (6 phases) |
| milestones/v1.0-REQUIREMENTS.md | v1.0 requirements (19 total) |
| milestones/v1.1-ROADMAP.md | v1.1 roadmap (5 phases) |
| milestones/v1.1-REQUIREMENTS.md | v1.1 requirements (11 total) |
| milestones/v1.1-MILESTONE-AUDIT.md | v1.1 audit report |

## Accumulated Context

**Decisions from prior milestones:**
- Observe-only first - proved AI diagnosis quality before action
- Protocol-based abstractions - Subject and DeploymentTarget extensible
- Subprocess isolation for TUI - daemons run as real processes
- httpx, Pydantic, aiosqlite stack - no new dependencies needed for v2.0

**Research findings (v2.0):**
- Safety infrastructure must exist before any action executes
- Structured action types prevent AI hallucination
- Risk-tiered approval prevents workflow bottlenecks
- PD API operators: transfer-leader, transfer-peer, set-store-state

**Decisions from Phase 12:**
- Pydantic BaseModel for action types (validation + serialization)
- Separate ACTIONS_SCHEMA_SQL for schema modularity
- cancel_all_pending cancels both proposed and validated statuses
- TYPE_CHECKING import guard for ActionDefinition forward reference in Subject
- Lazy cache in ActionRegistry built on first call
- ValidationError collects ALL errors before raising for complete user feedback
- Default to OBSERVE mode (safe by default, explicit opt-in for execution)
- Kill switch cancels pending AND switches to OBSERVE mode
- Lazy imports in safety.py and executor.py to break circular dependency with db.actions
- Optional executor parameter in AgentRunner preserves v1 observe-only behavior
- ActionRecommendation separate from existing recommended_action text field

**Decisions from Phase 13:**
- Fire-and-forget action semantics - return on API success, don't poll for completion
- Minimal validation - let PD API reject invalid requests
- Pass-through errors - don't transform PD error messages
- Hyphenated operator names in PD API (transfer-leader, not transfer_leader)
- Store ID type conversion (str to int) at Subject layer

## Session Continuity

**Last session:** 2026-01-26
**Stopped at:** Completed 13-01-PLAN.md (Phase 13 complete)
**Resume with:** `/gsd:execute-phase 14` to start Phase 14 (Approval Workflow)

## Open Issues

*None*

---
*State updated: 2026-01-26 (Phase 13 complete)*
