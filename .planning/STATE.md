# Project State: Operator

## Current Position

**Phase:** 10 of 11 (Demo Flow Control)
**Plan:** 1 of 1 in current phase
**Status:** Phase complete
**Last activity:** 2026-01-25 - Completed 10-01-PLAN.md

**Progress:** [████████████████░░░░] 80% (v1.1 TUI Demo)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

**Current focus:** v1.1 TUI Demo - Multi-panel dashboard with real daemon output and key-press driven demo flow

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | IN PROGRESS | - |

See: .planning/MILESTONES.md

## v1.1 Phase Summary

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 7. TUI Foundation | Multi-panel layout with terminal management | TUI-01 | Complete (2/2) |
| 8. Subprocess Management | Real daemons with live output capture | SUB-01, SUB-02, SUB-03 | Complete (2/2) |
| 9. Cluster Health Display | Health indicators and detection highlighting | TUI-02, TUI-04 | Complete (2/2) |
| 10. Demo Flow Control | Key-press chapters and narration | DEMO-01, DEMO-02 | Complete (1/1) |
| 11. Fault Workflow Integration | Workload viz, countdown, fault injection | TUI-03, DEMO-03, DEMO-04 | Not started |

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | Full roadmap with all 6 phases |
| milestones/v1.0-REQUIREMENTS.md | 19 requirements (all complete) |
| milestones/v1-MILESTONE-AUDIT.md | Audit report with integration check |

## Session Continuity

**Last session:** 2026-01-25
**Stopped at:** Completed 10-01-PLAN.md (Phase 10 complete)
**Resume with:** `/gsd:plan-phase 11` (Fault Workflow Integration)

## Key Decisions (v1.1)

| Decision | Rationale |
|----------|-----------|
| Subprocess isolation over direct import | Signal isolation, output capture, clean lifecycle, realistic demo |
| Rich Live (no Textual) | Already in use, no rewrite needed, Textual adds complexity |
| 5 panels (cluster, monitor, agent, workload, narration) | Research-validated layout, avoids cognitive overload |
| Key-press chapters over automatic timers | Presenter controls pacing |
| Signal handlers BEFORE Live context | Prevents Pitfall 2 (rapid Ctrl+C during startup) |
| screen=False for Rich Live | Demo output stays visible in terminal history |
| PYTHONUNBUFFERED=1 over PTY | Zero code changes to daemons, simpler than PTY |
| 0.1s readline timeout | Balances responsiveness with CPU efficiency |
| 5-second daemon intervals | Demo visibility (frequent updates without flooding) |
| 20-line panel display | Balances context with readability |
| Immutable ClusterHealth snapshots | Thread-safe reads without locks |
| Synthetic node names (tikv-1, pd-1) | Consistency across demo runs |
| Direct stdin reading over readchar | readchar's terminal mode changes conflict with Rich Live |
| select() with 0.3s timeout | Responsive shutdown without CPU-intensive polling |
| Progress indicator [X/7] | Visual feedback for presenter chapter position |

## Research Flags

From research/SUMMARY.md:
- **Phase 8:** Complex edge cases in subprocess buffering and signal handling
- **Phase 10:** Platform-specific keyboard input (Windows vs Unix)

## Open Issues

*None*

---
*State updated: 2026-01-25 (Phase 10 complete)*
