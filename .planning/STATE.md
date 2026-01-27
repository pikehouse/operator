# Project State: Operator

## Current Position

**Milestone:** v2.2 Agentic Remediations Demo
**Phase:** 22 - Demo Integration
**Plan:** Complete
**Status:** Phase 22 complete, milestone complete
**Last activity:** 2026-01-27 - Phase 22 executed and verified

Progress: [██████████] 100%

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-27)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — and now complete agentic loop with auto-remediation.

**Current focus:** v2.2 milestone complete — both demos show complete agentic loop (detect -> diagnose -> act -> verify).

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | SHIPPED | 2026-01-27 |
| v2.2 | COMPLETE | 2026-01-27 |

See: .planning/MILESTONES.md

## v2.2 Phase Overview

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 21 | Agent Agentic Loop | DEMO-01, AGENT-01, AGENT-02, AGENT-03, AGENT-04 (5) | Complete |
| 22 | Demo Integration | TIKV-01, TIKV-02, TIKV-03, RLIM-01, RLIM-02, RLIM-03 (6) | Complete |

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

## Accumulated Context

**Decisions from prior milestones:**
- Observe-only first - proved AI diagnosis quality before action
- Protocol-based abstractions - Subject and DeploymentTarget extensible
- Subprocess isolation for TUI - daemons run as real processes
- httpx, Pydantic, aiosqlite stack - proven across 4 milestones

**Key decisions from v2.0:**
- Pydantic BaseModel for action types (validation + serialization)
- Default to OBSERVE mode (safe by default, explicit opt-in for execution)
- Kill switch cancels pending AND switches to OBSERVE mode
- Fire-and-forget action semantics for PD API calls
- Tools use same ActionDefinition model with action_type=ActionType.TOOL

**Key decisions from v2.1:**
- Protocol-based abstractions (SubjectProtocol, InvariantCheckerProtocol) in zero-dependency operator-protocols package
- Factory returns tuple[Subject, Checker] for convenience
- Lazy import in subject_factory.py prevents loading operator-ratelimiter unless needed
- TiKVHealthPoller and RateLimiterHealthPoller return generic dict for framework flexibility
- Both demos use same TUI layout (5 panels) via TUIDemoController
- Monitor/agent subprocesses use --subject flag for subject selection

**Key decisions from v2.2 (Phase 21):**
- Fixed 5s delay for verification (not adaptive polling) - sufficient for demo
- Simplified verification logs success if metrics observed (full invariant re-check is future work)
- Propose -> Validate -> Execute -> Verify agentic flow in AgentRunner
- Environment variables for mode configuration (OPERATOR_SAFETY_MODE, OPERATOR_APPROVAL_MODE)
- SubprocessManager.spawn() accepts env dict, merges with os.environ

**Key decisions from v2.2 (Phase 22):**
- Renamed "AI Diagnosis" stages to "AI Remediation" to reflect full agentic loop
- Explicit action names in narratives (transfer_leader, reset_counter) for viewer understanding
- Consistent narration pattern: "Watch Agent panel for complete agentic loop" + numbered steps

## Session Continuity

**Last session:** 2026-01-27
**Stopped at:** v2.2 milestone complete
**Resume with:** `/gsd:audit-milestone` or `/gsd:complete-milestone`

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |

---
*State updated: 2026-01-27 (v2.2 milestone complete)*
