# Roadmap: Operator

## Milestones

- ✅ **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- 🚧 **v1.1 TUI Demo** - Phases 7-11 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-6) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.0-ROADMAP.md

**Summary:** 6 phases, 22 plans total. Delivered end-to-end chaos demo with fault injection, live detection, and AI diagnosis.

</details>

### v1.1 TUI Demo (In Progress)

**Milestone Goal:** Upgrade the demo to a Rich-based live dashboard showing the operator actually running with real daemon output, cluster health visualization, and key-press driven demo chapters.

#### Phase 7: TUI Foundation
**Goal**: Establish multi-panel layout with proper terminal management and async coordination
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: TUI-01
**Success Criteria** (what must be TRUE):
  1. TUI displays 5 distinct panels (cluster, monitor, agent, workload, narration)
  2. Layout renders without flicker using Rich Live context
  3. Ctrl+C cleanly exits without corrupted terminal state
  4. Signal handlers restore terminal before exit
**Plans**: 2 plans

Plans:
- [x] 07-01-PLAN.md — OutputBuffer and 5-panel layout factory
- [x] 07-02-PLAN.md — TUIController with signal handling and verification

#### Phase 8: Subprocess Management
**Goal**: Run monitor and agent as real subprocesses with live output capture and graceful shutdown
**Depends on**: Phase 7
**Requirements**: SUB-01, SUB-02, SUB-03
**Success Criteria** (what must be TRUE):
  1. Monitor daemon runs as subprocess (not one-shot call)
  2. Agent daemon runs as subprocess (not one-shot call)
  3. Subprocess stdout streams to TUI panels in real-time (no buffering delay)
  4. Ctrl+C terminates all subprocesses cleanly (no orphans)
  5. No zombie processes remain after TUI exit
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

#### Phase 9: Cluster Health Display
**Goal**: Show live cluster status with color-coded health indicators and detection highlighting
**Depends on**: Phase 8
**Requirements**: TUI-02, TUI-04
**Success Criteria** (what must be TRUE):
  1. Cluster panel shows all 6 nodes (3 TiKV, 3 PD) with health status
  2. Healthy nodes display green indicator
  3. Down nodes display red indicator
  4. When monitor detects an issue, visual emphasis appears (color change or highlight)
**Plans**: TBD

Plans:
- [ ] 09-01: TBD

#### Phase 10: Demo Flow Control
**Goal**: Enable key-press chapter progression with narration explaining each stage
**Depends on**: Phase 9
**Requirements**: DEMO-01, DEMO-02
**Success Criteria** (what must be TRUE):
  1. Demo advances to next chapter on key press (not automatic timer)
  2. Narration panel displays story text for current chapter
  3. Chapter text explains what is happening and what to watch for
  4. Available key commands are visible to presenter
**Plans**: TBD

Plans:
- [ ] 10-01: TBD

#### Phase 11: Fault Workflow Integration
**Goal**: Complete end-to-end demo with fault injection, workload degradation visualization, and recovery
**Depends on**: Phase 10
**Requirements**: TUI-03, DEMO-03, DEMO-04
**Success Criteria** (what must be TRUE):
  1. Workload panel shows ops/sec sparkline or histogram
  2. Workload visualization turns red when performance degrades
  3. Key press triggers countdown before fault injection
  4. Countdown is visually displayed (e.g., "Injecting fault in 3... 2... 1...")
  5. Node kill occurs after countdown completes
  6. Recovery chapter restores node and workload returns to green
**Plans**: TBD

Plans:
- [ ] 11-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 7 → 8 → 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7. TUI Foundation | v1.1 | 2/2 | Complete | 2026-01-25 |
| 8. Subprocess Management | v1.1 | 0/TBD | Not started | - |
| 9. Cluster Health Display | v1.1 | 0/TBD | Not started | - |
| 10. Demo Flow Control | v1.1 | 0/TBD | Not started | - |
| 11. Fault Workflow Integration | v1.1 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-25*
*v1.1 milestone: Phases 7-11 (5 phases, 11 requirements)*
