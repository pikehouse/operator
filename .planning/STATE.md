# Project State: Operator

## Current Position

**Milestone:** v3.2 Evaluation Harness
**Phase:** 39 - Config Variants (IN PROGRESS)
**Plan:** 1/2 complete
**Status:** Pydantic-validated YAML variant system with discovery and CLI listing
**Last activity:** 2026-01-30 — Completed 39-01-PLAN.md

Progress: █████████████░░░░░░░ (v3.2: 65%)

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

**Status:** Phase 35 complete, Phase 36 complete, Phase 37 complete, Phase 38 complete, Phase 39 in progress (1/2 plans)

**Next:** Plan 39-02 (Campaign Variant Integration)

## Session Continuity

**Last session:** 2026-01-30T01:59:33Z
**Stopped at:** Completed 39-01-PLAN.md (Phase 39 in progress - 1/2 plans)
**Resume file:** None
**Next:** Plan 39-02 (Campaign Variant Integration)

---
*State updated: 2026-01-30 (Phase 39 in progress - 1/2 plans)*

## Decisions Made

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 37-02 | Use FastAPI + Jinja2 for web viewer with server-side rendering | Simple static views, no need for complex frontend framework |
| 37-02 | Use Tailwind CDN for styling | No build step needed, fast prototyping with modern utility classes |
| 37-02 | Query operator.db by timerange for reasoning entries | Trial timestamps define the relevant agent session window |
| 38-01 | Use tc netem for latency injection | tc netem is built into Linux kernel, provides precise control over delay/jitter without additional containers |
| 38-01 | Use fallocate for disk pressure | fallocate is instant (allocates space without writing), simpler than dd or filesystem quotas |
| 38-01 | Use iptables for network partition | iptables allows selective blocking of specific peer IPs, better than coarse docker network disconnect |
| 38-01 | Chaos metadata contains cleanup fields | Makes cleanup stateless - inject_chaos returns all fields needed by cleanup_chaos for reversibility |
| 38-02 | Campaign matrix expansion uses Cartesian product | itertools.product generates subjects x chaos_types x trials_per_combination efficiently |
| 38-02 | Cleanup chaos after final_state capture | Ensures final_state snapshot reflects during-chaos conditions before reverting |
| 38-02 | run_campaign_from_config is NEW function | Preserves backward compatibility - existing run_campaign() unchanged for CLI |
| 39-01 | No runtime model validation in VariantConfig | Allows testing with new models without code changes, runtime errors acceptable for eval harness |
| 39-01 | Inline system prompts in YAML | Self-contained variant files, easier version control than file path references |
| 39-01 | tools_config structure: tool_choice and enabled_tools | Maps to Anthropic API parameters, extensible for future options |
| 39-01 | Variant discovery via glob in eval/variants/ | One YAML file per variant, skips invalid files silently |

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |
