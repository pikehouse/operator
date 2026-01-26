# Roadmap: Operator

## Milestones

- [x] **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- [x] **v1.1 TUI Demo** - Phases 7-11 (shipped 2026-01-25)
- [ ] **v2.0 Agent Actions** - Phases 12-15 (in progress)

## v2.0 Agent Actions

Enable the agent to execute its recommendations, not just observe and diagnose. Four phases deliver action execution with safety-first architecture.

### Phase 12: Action Foundation

**Goal:** Infrastructure exists for proposing, validating, executing, and auditing actions safely.

**Dependencies:** None (first phase of v2.0)

**Plans:** 4 plans

Plans:
- [ ] 12-01-PLAN.md — Action types and database schema
- [ ] 12-02-PLAN.md — Action registry and parameter validation
- [ ] 12-03-PLAN.md — Safety controls and audit logging
- [ ] 12-04-PLAN.md — Agent integration and CLI commands

**Requirements:**
- ACT-01: Action framework supports multiple action sources
- ACT-04: Agent can request an action based on diagnosis
- ACT-05: Action parameters are validated before execution
- ACT-06: Action execution result is tracked
- ACT-07: All actions are recorded in audit log
- SAF-01: Kill switch can halt all pending/in-progress actions
- SAF-02: Observe-only mode disables all action execution

**Success Criteria:**
1. Action proposal can be created with typed parameters and stored in database
2. Agent discovers available actions from subject at runtime (no hard-coded subject logic in core)
3. Kill switch immediately halts all pending actions
4. Observe-only mode flag prevents any action execution
5. All action lifecycle events (proposed, validated, executed, completed/failed) are recorded in audit log

---

### Phase 13: TiKV Subject Actions

**Goal:** TiKV subject can execute leader transfer, peer transfer, and store drain operations via PD API.

**Dependencies:** Phase 12 (action foundation must exist)

**Requirements:**
- ACT-02: Subject can define domain-specific actions
- TKV-01: TiKV subject defines transfer-leader action
- TKV-02: TiKV subject defines transfer-peer action
- TKV-03: TiKV subject defines drain-store action

**Success Criteria:**
1. Agent can execute transfer-leader action that moves region leader to specified store
2. Agent can execute transfer-peer action that moves region replica to different store
3. Agent can execute drain-store action that evicts all leaders from a store
4. Each action validates target exists and is in valid state before execution

---

### Phase 14: Approval Workflow

**Goal:** Configurable approval gate for action execution (default: autonomous).

**Dependencies:** Phase 13 (actions must exist to approve)

**Requirements:**
- ACT-03: Agent can use general tools beyond subject-defined actions
- APR-01: Action approval is configurable (on/off, default off)
- APR-02: When approval enabled, user can approve/reject via CLI

**Success Criteria:**
1. Approval mode is configurable via config (default: off — agent executes autonomously)
2. With approval off, agent executes actions immediately after proposing
3. With approval on, actions remain pending until human approves
4. User can approve/reject pending actions via CLI when approval is enabled

---

### Phase 15: Workflow Actions

**Goal:** Agent can chain actions, schedule follow-ups, and retry failures.

**Dependencies:** Phase 14 (approval workflow must exist for multi-action approval)

**Requirements:**
- WRK-01: Agent can chain multiple actions into a workflow
- WRK-02: Agent can schedule follow-up actions
- WRK-03: Agent can retry failed actions with backoff

**Success Criteria:**
1. Agent can propose a sequence of actions as a single workflow
2. Agent can schedule a verification action to run after specified delay
3. Failed action retries automatically with exponential backoff (configurable limit)

---

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

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7-11 | v1.1 | 9/9 | Complete | 2026-01-25 |
| 12 | v2.0 | 0/4 | Planned | - |
| 13 | v2.0 | 0/? | Pending | - |
| 14 | v2.0 | 0/? | Pending | - |
| 15 | v2.0 | 0/? | Pending | - |

---
*Roadmap created: 2026-01-25*
*v2.0 roadmap added: 2026-01-26*
*Phase 12 planned: 2026-01-26*
