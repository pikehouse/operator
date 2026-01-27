# Roadmap: Operator

## Milestones

- [x] **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- [x] **v1.1 TUI Demo** - Phases 7-11 (shipped 2026-01-25)
- [x] **v2.0 Agent Actions** - Phases 12-15 (shipped 2026-01-26)
- [x] **v2.1 Multi-Subject Support** - Phases 16-20 (shipped 2026-01-27)
- [ ] **v2.2 Agentic Remediations Demo** - Phases 21-22 (in progress)

## Current Milestone: v2.2 Agentic Remediations Demo

**Overview:** Upgrade both TiKV and rate limiter demos to show the complete agentic loop: fault injection leads to AI detection, diagnosis, auto-execute remediation action, and verification that the fix resolved the issue. This proves the operator can act autonomously, not just observe.

### Phase 21: Agent Agentic Loop

**Goal:** Agent can execute recommended actions autonomously and verify the fix resolved the issue

**Dependencies:** v2.0 action framework, v2.1 multi-subject support

**Requirements:**
- DEMO-01: Demo runs in EXECUTE mode (autonomous, no approval)
- AGENT-01: Agent executes action immediately after diagnosis
- AGENT-02: Agent waits 5s after action before verification
- AGENT-03: Agent queries subject metrics to verify fix
- AGENT-04: Agent outputs verification result to log

**Plans:** 2 plans

Plans:
- [x] 21-01-PLAN.md — AgentRunner agentic execution with immediate validate/execute and verification
- [x] 21-02-PLAN.md — Demo configuration for EXECUTE mode and autonomous execution

**Success Criteria:**
1. Agent executes recommended action without human approval in EXECUTE mode
2. Agent waits configurable delay (5s) then queries subject for verification metrics
3. Agent logs verification outcome (success: issue resolved, failure: issue persists)

### Phase 22: Demo Integration

**Goal:** Both demos show complete agentic remediation loop in action

**Dependencies:** Phase 21 (agent agentic loop)

**Requirements:**
- TIKV-01: TiKV chapter narratives updated for agentic flow
- TIKV-02: Node kill -> transfer-leader -> verify regions rebalanced
- TIKV-03: TiKV demo shows complete loop in agent panel
- RLIM-01: Rate limiter chapter narratives updated for agentic flow
- RLIM-02: Counter drift -> reset_counter -> verify counters aligned
- RLIM-03: Rate limiter demo shows complete loop in agent panel

**Plans:** 1 plan

Plans:
- [ ] 22-01-PLAN.md — Update demo chapter narratives for agentic remediation flow

**Success Criteria:**
1. TiKV demo chapter narratives describe agentic remediation (not just observation)
2. TiKV demo: after node kill, agent executes transfer-leader and verifies region rebalance
3. Rate limiter demo chapter narratives describe agentic remediation (not just observation)
4. Rate limiter demo: after counter drift, agent executes reset_counter and verifies alignment
5. Both demos display diagnosis + action + verification sequence in agent panel

## Archived Milestones

<details>
<summary>v1.0 MVP (Phases 1-6) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.0-ROADMAP.md

**Summary:** 6 phases, 22 plans total. Delivered end-to-end chaos demo with fault injection, live detection, and AI diagnosis.

</details>

<details>
<summary>v1.1 TUI Demo (Phases 7-11) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.1-ROADMAP.md

**Summary:** 5 phases, 9 plans total. Rich-based live dashboard with real daemon output, cluster health visualization, and key-press driven demo chapters.

</details>

<details>
<summary>v2.0 Agent Actions (Phases 12-15) - SHIPPED 2026-01-26</summary>

Archived in milestones/v2.0-ROADMAP.md

**Summary:** 4 phases, 12 plans total. Action execution framework with safety controls, approval workflows, TiKV actions, workflow chaining, scheduled execution, and retry logic.

</details>

<details>
<summary>v2.1 Multi-Subject Support (Phases 16-20) - SHIPPED 2026-01-27</summary>

Archived in milestones/v2.1-ROADMAP.md

**Summary:** 5 phases, 21 plans total. Protocol-based abstractions, custom rate limiter service, operator-ratelimiter package, multi-subject CLI, unified demo framework. AI diagnoses rate limiter anomalies without system-specific prompts.

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7-11 | v1.1 | 9/9 | Complete | 2026-01-25 |
| 12-15 | v2.0 | 12/12 | Complete | 2026-01-26 |
| 16-20 | v2.1 | 21/21 | Complete | 2026-01-27 |
| 21 | v2.2 | 2/2 | Complete | 2026-01-27 |
| 22 | v2.2 | 0/1 | Pending | — |

---
*Roadmap created: 2026-01-25*
*v1.0 archived: 2026-01-25*
*v1.1 archived: 2026-01-25*
*v2.0 archived: 2026-01-26*
*v2.1 archived: 2026-01-27*
*v2.2 phases added: 2026-01-27*
*Phase 21 planned: 2026-01-27*
*Phase 21 completed: 2026-01-27*
