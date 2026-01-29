# Roadmap: Operator

## Milestones

- v1.0 MVP - Phases 1-6 (shipped 2026-01-25)
- v1.1 TUI Demo - Phases 7-11 (shipped 2026-01-25)
- v2.0 Actions - Phases 12-15 (shipped 2026-01-26)
- v2.1 Protocols - Phases 16-20 (shipped 2026-01-27)
- v2.2 Agentic Loop - Phases 21-22 (shipped 2026-01-27)
- v3.0 Operator Laboratory - Phases 30-32 (shipped 2026-01-28)
- v3.1 Demo Update - Phases 33-34 (shipped 2026-01-29)
- v3.2 Evaluation Harness - Phases 35-39 (in progress)

## Phases

<details>
<summary>v1.0 MVP (Phases 1-6) - SHIPPED 2026-01-25</summary>

See: .planning/milestones/v1.0-ROADMAP.md

</details>

<details>
<summary>v1.1 TUI Demo (Phases 7-11) - SHIPPED 2026-01-25</summary>

See: .planning/milestones/v1.1-ROADMAP.md

</details>

<details>
<summary>v2.0 Actions (Phases 12-15) - SHIPPED 2026-01-26</summary>

See: .planning/milestones/v2.0-ROADMAP.md

</details>

<details>
<summary>v2.1 Protocols (Phases 16-20) - SHIPPED 2026-01-27</summary>

See: .planning/milestones/v2.1-ROADMAP.md

</details>

<details>
<summary>v2.2 Agentic Loop (Phases 21-22) - SHIPPED 2026-01-27</summary>

See: .planning/milestones/v2.2-ROADMAP.md

</details>

<details>
<summary>v3.0 Operator Laboratory (Phases 30-32) - SHIPPED 2026-01-28</summary>

See: .planning/milestones/v3.0-ROADMAP.md

</details>

<details>
<summary>v3.1 Demo Update (Phases 33-34) - SHIPPED 2026-01-29</summary>

See: .planning/milestones/v3.1-ROADMAP.md

</details>

### v3.2 Evaluation Harness (In Progress)

**Milestone Goal:** Build eval/ — a standalone harness that injects chaos, monitors agent problem-solving, grades performance, and provides historical analysis.

See: .planning/milestones/v3.2-ROADMAP.md

#### Phase 35: Runner Layer
**Goal**: Developer can run single-trial evaluations and see raw results stored in database

**Depends on**: Nothing (first phase of v3.2)

**Requirements**: RUN-01, RUN-02, RUN-03, RUN-04, RUN-05, RUN-06, SUBJ-01, SUBJ-02, SUBJ-03, CLI-01, CLI-02

**Success Criteria**:
  1. Developer can run `eval run --subject tikv --chaos node_kill` and trial executes
  2. Developer can run `eval run --baseline` and trial executes without agent
  3. Trial data persists in eval.db with timing data
  4. Trial data includes subject state before/after chaos and commands extracted from agent session
  5. TiKVEvalSubject implements EvalSubject protocol

**Plans**: 4 plans

Plans:
- [x] 35-01-PLAN.md — Package foundation with EvalSubject protocol and core types
- [x] 35-02-PLAN.md — TiKVEvalSubject with Docker Compose lifecycle and node_kill chaos
- [x] 35-03-PLAN.md — Database layer and campaign runner harness
- [x] 35-04-PLAN.md — CLI with run command for single-trial execution

---

#### Phase 36: Analysis Layer
**Goal**: Developer can compute scores and compare performance across trials/campaigns

**Depends on**: Phase 35

**Requirements**: ANAL-01, ANAL-02, ANAL-03, ANAL-04, ANAL-05, ANAL-06, CLI-04, CLI-05, CLI-06

**Success Criteria**:
  1. Developer can run `eval analyze <campaign_id>` and see scores
  2. Developer can run `eval compare-baseline <campaign_id>` and see agent vs self-healing
  3. Developer can run `eval compare <campaign_a> <campaign_b>` and see differences
  4. Analysis computes command metrics (count, unique, thrashing, destructive)
  5. Analysis is idempotent

**Plans**: 4 plans

Plans:
- [x] 36-01-PLAN.md — Analysis types and scoring module (ANAL-01, ANAL-06)
- [x] 36-02-PLAN.md — Command analysis with LLM classification (ANAL-02, ANAL-03)
- [x] 36-03-PLAN.md — Baseline and campaign comparison (ANAL-04, ANAL-05)
- [x] 36-04-PLAN.md — CLI commands analyze, compare, compare-baseline (CLI-04, CLI-05, CLI-06)

---

#### Phase 37: Viewer Layer
**Goal**: Developer can browse campaigns and drill into trial details via CLI and web UI

**Depends on**: Phase 36

**Requirements**: VIEW-01, VIEW-02, VIEW-03, VIEW-04, VIEW-05

**Success Criteria**:
  1. Developer can run `eval list` and see all campaigns
  2. Developer can run `eval show <campaign_id>` and see campaign summary
  3. Developer can run `eval show <trial_id>` and see trial detail
  4. Developer can open web UI and browse campaigns/trials
  5. Web UI displays trial reasoning and commands

**Plans**: 2 plans

Plans:
- [x] 37-01-PLAN.md — CLI list and show commands (VIEW-01, VIEW-02, VIEW-03)
- [x] 37-02-PLAN.md — Web viewer with FastAPI, templates, reasoning display (VIEW-04, VIEW-05)

---

#### Phase 38: Chaos Expansion
**Goal**: Developer can run batch campaigns with multiple chaos types

**Depends on**: Phase 37

**Requirements**: SUBJ-04, SUBJ-05, SUBJ-06, CLI-03

**Success Criteria**:
  1. TiKV supports latency chaos (tc netem)
  2. TiKV supports disk pressure chaos (fallocate)
  3. TiKV supports network partition chaos (iptables)
  4. Developer can define campaign config YAML
  5. Developer can run `eval run campaign config.yaml`

**Plans**: 2 plans

Plans:
- [ ] 38-01-PLAN.md — Chaos injection functions (latency, disk pressure, network partition)
- [ ] 38-02-PLAN.md — Campaign YAML config and batch runner with parallel support

---

#### Phase 39: Config Variants
**Goal**: Developer can test different agent configurations and compare performance

**Depends on**: Phase 38

**Requirements**: CONF-01, CONF-02, CONF-03

**Success Criteria**:
  1. Config variants define model, system_prompt, tools_config
  2. Campaign config can specify variant
  3. Analysis compares performance across variants
  4. Developer can see which configuration performs best

**Plans**: TBD

Plans:
- [ ] 39-01: TBD

---

## Progress

**Execution Order:**
Phases execute in numeric order: 35 -> 36 -> 37 -> 38 -> 39

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 3/3 | Complete | 2026-01-25 |
| 2. Monitoring | v1.0 | 2/2 | Complete | 2026-01-25 |
| 3. Subject Adapter | v1.0 | 2/2 | Complete | 2026-01-25 |
| 4. TiKV Integration | v1.0 | 3/3 | Complete | 2026-01-25 |
| 5. Diagnosis | v1.0 | 2/2 | Complete | 2026-01-25 |
| 6. Chaos | v1.0 | 1/1 | Complete | 2026-01-25 |
| 7. TUI Framework | v1.1 | 2/2 | Complete | 2026-01-25 |
| 8. Live Panels | v1.1 | 3/3 | Complete | 2026-01-25 |
| 9. Agent Panel | v1.1 | 2/2 | Complete | 2026-01-25 |
| 10. Chapter Flow | v1.1 | 2/2 | Complete | 2026-01-25 |
| 11. Demo Polish | v1.1 | 1/1 | Complete | 2026-01-25 |
| 12. Action Framework | v2.0 | 3/3 | Complete | 2026-01-26 |
| 13. Subject Actions | v2.0 | 2/2 | Complete | 2026-01-26 |
| 14. Approval Workflow | v2.0 | 3/3 | Complete | 2026-01-26 |
| 15. Workflows | v2.0 | 2/2 | Complete | 2026-01-26 |
| 16. Protocol Abstractions | v2.1 | 2/2 | Complete | 2026-01-27 |
| 17. Core Refactor | v2.1 | 3/3 | Complete | 2026-01-27 |
| 18. Rate Limiter Service | v2.1 | 3/3 | Complete | 2026-01-27 |
| 19. Rate Limiter Subject | v2.1 | 3/3 | Complete | 2026-01-27 |
| 20. Multi-Subject Integration | v2.1 | 2/2 | Complete | 2026-01-27 |
| 21. Agentic Loop | v2.2 | 2/2 | Complete | 2026-01-27 |
| 22. Execute Mode | v2.2 | 2/2 | Complete | 2026-01-27 |
| 30. Agent Container | v3.0 | 2/2 | Complete | 2026-01-28 |
| 31. Shell Tool | v3.0 | 2/2 | Complete | 2026-01-28 |
| 32. Audit System | v3.0 | 3/3 | Complete | 2026-01-28 |
| 33. Agent Database Integration | v3.1 | 3/3 | Complete | 2026-01-28 |
| 34. Demo End-to-End Validation | v3.1 | 2/2 | Complete | 2026-01-29 |
| 35. Runner Layer | v3.2 | 4/4 | Complete | 2026-01-29 |
| 36. Analysis Layer | v3.2 | 4/4 | Complete | 2026-01-29 |
| 37. Viewer Layer | v3.2 | 2/2 | Complete | 2026-01-29 |
| 38. Chaos Expansion | v3.2 | 0/2 | Not started | - |
| 39. Config Variants | v3.2 | 0/TBD | Not started | - |

---
*Updated: 2026-01-29 — Phase 38 planned*
