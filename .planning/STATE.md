# Project State: Operator

## Current Position

**Milestone:** v3.2 SHIPPED
**Phase:** —
**Plan:** —
**Status:** Awaiting next milestone definition
**Last activity:** 2026-01-30 — v3.2 Evaluation Harness shipped

Progress: ████████████████████ 100%

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
| v3.2 | SHIPPED | 2026-01-30 |

See: .planning/MILESTONES.md

## v3.2 Delivered

**Philosophy:** Evaluate how well Claude operates through chaos events — compare to baseline, detect regressions, analyze trends.

**Key deliverables:**
- EvalSubject protocol with TiKV implementation (reset, inject, capture state)
- 4 chaos types: node_kill, latency, disk_pressure, network_partition
- Trial scoring with time-to-detect, time-to-resolve, command analysis
- Campaign YAML config with matrix expansion and parallel execution
- Config variants for A/B testing different agent configurations
- Managed operator mode (auto-start/stop monitor and agent)
- Web viewer for browsing campaigns and trial reasoning

**Stats:**
- 21 Python files, 3,703 lines in eval/
- 5 phases, 16 plans
- 32 requirements shipped

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
| milestones/v3.2-ROADMAP.md | v3.2 roadmap (5 phases) |
| milestones/v3.2-REQUIREMENTS.md | v3.2 requirements (32 total) |
| milestones/v3.2-MILESTONE-AUDIT.md | v3.2 audit report |

## Session Continuity

**Last session:** 2026-01-30
**Stopped at:** v3.2 milestone shipped
**Resume file:** None
**Next:** /gsd:new-milestone to define v3.3 or v4.0

---
*State updated: 2026-01-30 (v3.2 Evaluation Harness shipped)*

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
| 39-02 | Schema migration pattern with PRAGMA checks | Idempotent migrations safe to run multiple times, backward compatible |
| 39-02 | Variant defaults to "default" | Backward compatibility with existing campaigns and YAMLs |
| 39-02 | Variant loading in harness | Load variant early to fail fast if variant not found |
| 39-02 | Defensive variant_name reads with getattr() | Compatible with old databases created before variant_name column |
| 39-03 | Balanced scorecard approach for variant comparison | User requirement specified no winner determination, show all metrics equally |
| 39-03 | Filter non-baseline campaigns for comparison | Baseline campaigns test self-healing, not agent variants |
| 39-03 | Sort variants by name | Consistent output order for reproducible comparisons |
| 39-03 | Aggregate across campaigns per variant | Single variant may have multiple campaigns (re-runs, different dates) |
| 39-04 | Store variant config in tickets table for cross-process communication | Agent runs in separate process, polls operator.db. Environment variables won't work across process boundary |
| 39-04 | Harness writes variant via SQL UPDATE after ticket creation | Variant config is eval-harness-specific, not part of monitor loop. Direct SQL keeps monitor unchanged |
| 39-04 | Agent reads variant from ticket with graceful fallbacks | ticket.variant_model or default preserves backward compatibility with existing tickets |
| 39-04 | Write variant config after chaos injection, before agent polls | 2-second sleep gives monitor time to create ticket, update before agent reads ensures config is present |

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |
