# Roadmap: Operator

## Milestones

- v1.0 MVP - Phases 1-6 (shipped 2026-01-25)
- v1.1 TUI Demo - Phases 7-11 (shipped 2026-01-25)
- v2.0 Actions - Phases 12-15 (shipped 2026-01-26)
- v2.1 Protocols - Phases 16-20 (shipped 2026-01-27)
- v2.2 Agentic Loop - Phases 21-22 (shipped 2026-01-27)
- v3.0 Operator Laboratory - Phases 30-32 (shipped 2026-01-28)
- v3.1 Demo Update - Phases 33-34 (in progress)

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

### v3.1 Demo Update (In Progress)

**Milestone Goal:** Fix TUI demo to work with v3.0 agent_lab architecture

#### Phase 33: Agent Database Integration
**Goal**: Agent subprocess handles database lifecycle correctly
**Depends on**: Phase 32
**Requirements**: DEMO-01, DEMO-02, DEMO-03, DEMO-07, ARCH-01, TEST-03
**Success Criteria** (what must be TRUE):
  1. Agent subprocess initializes schema on first connection (no "no such table" errors)
  2. Agent poll loop runs without errors when database is empty (no tickets yet)
  3. Demo script starts with clean database state (repeatable demo runs)
  4. Agent subprocess handles SIGTERM gracefully (marks session as escalated, cleans up)
  5. Agent code (operator_core) contains no demo-specific logic (clean separation of concerns)
  6. Unit test verifies agent schema initialization works correctly
**Plans**: 3 plans

Plans:
- [x] 33-01-PLAN.md - Create TicketOpsDB context manager with schema initialization
- [x] 33-02-PLAN.md - Add signal handling to agent loop with graceful shutdown
- [x] 33-03-PLAN.md - Unit tests for schema initialization (TEST-03)

#### Phase 34: Demo End-to-End Validation
**Goal**: Both demos run successfully with v3.0 agent
**Depends on**: Phase 33
**Requirements**: DEMO-04, DEMO-05, DEMO-06, TEST-01, TEST-02
**Success Criteria** (what must be TRUE):
  1. TiKV demo completes full flow: startup -> fault injection -> agent diagnosis -> autonomous resolution
  2. Rate limiter demo completes full flow: startup -> fault injection -> agent diagnosis -> autonomous resolution
  3. Agent panel displays subprocess output in real-time (verify existing TUI behavior)
  4. Demo chapters advance correctly with proper timing and state transitions
  5. Integration tests verify TiKV demo runs without errors
  6. Integration tests verify ratelimiter demo runs without errors
**Plans**: 2 plans

Plans:
- [ ] 34-01-PLAN.md - Manual validation of TiKV and rate limiter demos (DEMO-04, DEMO-05, DEMO-06)
- [ ] 34-02-PLAN.md - Create pytest integration tests (TEST-01, TEST-02)

## Progress

**Execution Order:**
Phases execute in numeric order: 33 -> 34

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
| 34. Demo End-to-End Validation | v3.1 | 0/2 | Not started | - |
