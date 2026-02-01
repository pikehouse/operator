# Project State: Operator

## Current Position

**Milestone:** v3.3 Extended TiKV Chaos
**Phase:** Not started (defining requirements)
**Plan:** —
**Status:** Defining requirements
**Last activity:** 2026-02-01 — Milestone v3.3 started

Progress: ░░░░░░░░░░░░░░░░░░░░ 0%

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-01)

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
| v3.3 | IN PROGRESS | — |

See: .planning/MILESTONES.md

## v3.3 Goals

**Philosophy:** Extend chaos repertoire with resource pressure failures that trigger different TiKV behaviors than simple node kills or network issues.

**Target chaos types:**
- cpu_pressure — SIGSTOP or stress-ng triggers Raft election stalls
- memory_pressure — cgroups limit triggers OOM behavior
- io_latency — tc on block device triggers slow store detection

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

**Last session:** 2026-02-01
**Stopped at:** Milestone initialization
**Resume file:** None
**Next:** Define requirements and create roadmap

---
*State updated: 2026-02-01 (v3.3 milestone started)*

## Decisions Made

| Phase | Decision | Rationale |
|-------|----------|-----------|
| — | Selected cpu_pressure, memory_pressure, io_latency for v3.3 | High realism, medium difficulty, avoids clock_skew complexity |

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |
| 002 | Enhance eval CLI and web viewer with chaos details | 2026-01-30 | a650a17 | [002-enhance-eval-cli-and-web-viewer-with-chaos-details](./quick/002-enhance-eval-cli-and-web-viewer-with-chaos-details/) |
| 003 | True parallel campaign execution | 2026-01-30 | ee7ef6d | [003-true-parallel-campaign-execution](./quick/003-true-parallel-campaign-execution/) |
