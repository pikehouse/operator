# Project State: Operator

## Current Position

**Phase:** 11 of 11 (Fault Workflow Integration)
**Plan:** 2 of 2 in current phase
**Status:** Phase complete
**Last activity:** 2026-01-25 - Completed Phase 11 (all plans verified)

**Progress:** [████████████████████] 100% (v1.1 TUI Demo)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-25)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

**Current focus:** v1.1 TUI Demo complete. Ready for milestone audit.

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | COMPLETE | 2026-01-25 |

See: .planning/MILESTONES.md

## v1.1 Phase Summary

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 7. TUI Foundation | Multi-panel layout with terminal management | TUI-01 | Complete (2/2) |
| 8. Subprocess Management | Real daemons with live output capture | SUB-01, SUB-02, SUB-03 | Complete (2/2) |
| 9. Cluster Health Display | Health indicators and detection highlighting | TUI-02, TUI-04 | Complete (2/2) |
| 10. Demo Flow Control | Key-press chapters and narration | DEMO-01, DEMO-02 | Complete (1/1) |
| 11. Fault Workflow Integration | Workload viz, countdown, fault injection | TUI-03, DEMO-03, DEMO-04 | Complete (2/2) |

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | Full roadmap with all 6 phases |
| milestones/v1.0-REQUIREMENTS.md | 19 requirements (all complete) |
| milestones/v1-MILESTONE-AUDIT.md | Audit report with integration check |

## Session Continuity

**Last session:** 2026-01-25
**Stopped at:** Completed Phase 11 - all plans verified
**Resume with:** `/gsd:audit-milestone` (verify requirements and E2E flows)

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
| sparklines library for workload viz | Handles scaling, edge cases; pure Python, MIT license |
| 5 samples for baseline warm-up | Sufficient to establish stable baseline without long delay |
| 50% threshold for degradation | Conservative default; tunable via constructor parameter |
| Chapter on_enter callbacks | Async callbacks for automated actions during chapter entry |
| FaultWorkflow with DockerClient | Reuse python-on-whales pattern from chaos.py |
| blocks_advance during countdown | Prevent user from advancing while action in progress |

## Research Flags

From research/SUMMARY.md:
- **Phase 8:** Complex edge cases in subprocess buffering and signal handling
- **Phase 10:** Platform-specific keyboard input (Windows vs Unix)

## Open Issues

*None*

---
*State updated: 2026-01-25 (Phase 11 complete - v1.1 milestone complete)*
