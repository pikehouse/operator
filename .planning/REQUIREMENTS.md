# Requirements: Operator

**Defined:** 2026-01-25
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

## v1.1 Requirements

Requirements for TUI Demo milestone. Each maps to roadmap phases.

### TUI Layout

- [x] **TUI-01**: Multi-panel layout with cluster, monitor, agent, workload, and narration panels
- [x] **TUI-02**: Color-coded health indicators (green ● for up, red ✗ for down) for all cluster nodes
- [ ] **TUI-03**: Workload panel with sparkline/histogram showing ops/sec that turns red when degraded
- [x] **TUI-04**: Detection highlighting — visual emphasis when monitor detects an issue

### Subprocess Management

- [x] **SUB-01**: Run monitor and agent as real subprocesses (not one-shot calls)
- [x] **SUB-02**: Live stdout capture — stream subprocess output to panels in real-time
- [x] **SUB-03**: Graceful shutdown — clean exit without orphan processes or broken terminal

### Demo Flow

- [x] **DEMO-01**: Key-press chapter progression — press key to advance demo stages
- [x] **DEMO-02**: Narration panel with story text explaining what's happening at each stage
- [ ] **DEMO-03**: Fault injection and recovery — kill node, watch diagnosis, restore to healthy
- [ ] **DEMO-04**: Countdown before fault injection — visual countdown before killing node

## Future Requirements

Deferred to later milestones.

### Additional Chaos Scenarios

- **CHAOS-02**: Hot region — concentrate load on narrow key range
- **CHAOS-03**: Latency injection — slow disk reads
- **CHAOS-04**: Network partition — isolate node from cluster

### Actions

- **ACT-01**: Action execution — actually perform recommended actions (transfer_leader, etc.)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| tmux dependency | Must work without external tools |
| Mouse navigation | Breaks presentation flow, keyboard-only |
| Scrolling log dumps | Defeats purpose of dashboard, use panels |
| More than 6 panels | Cognitive overload, keep focused |
| Windows support (v1.1) | Unix-first, Windows can be added later |
| Web dashboard | CLI/TUI for v1.x, web later |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TUI-01 | Phase 7 | Complete |
| TUI-02 | Phase 9 | Complete |
| TUI-03 | Phase 11 | Pending |
| TUI-04 | Phase 9 | Complete |
| SUB-01 | Phase 8 | Complete |
| SUB-02 | Phase 8 | Complete |
| SUB-03 | Phase 8 | Complete |
| DEMO-01 | Phase 10 | Complete |
| DEMO-02 | Phase 10 | Complete |
| DEMO-03 | Phase 11 | Pending |
| DEMO-04 | Phase 11 | Pending |

**Coverage:**
- v1.1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0

---
*Requirements defined: 2026-01-25*
*Last updated: 2026-01-25 (Phase 10 complete)*
