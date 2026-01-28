# Requirements: Operator v3.1 Demo Update

**Defined:** 2026-01-28
**Core Value:** Demo showcases v3.0 autonomous agent in action

## v3.1 Requirements

Fix TUI demo to work with v3.0 agent_lab architecture.

### Demo Infrastructure

- [ ] **DEMO-01**: Agent subprocess initializes database schema before first query
- [ ] **DEMO-02**: Agent poll loop handles empty database gracefully (no tickets yet)
- [ ] **DEMO-03**: Demo script ensures clean database state before starting
- [ ] **DEMO-04**: TiKV demo runs end-to-end (startup → fault injection → agent diagnosis → resolution)
- [ ] **DEMO-05**: Rate limiter demo runs end-to-end (same flow as TiKV)

### Agent Lifecycle

- [ ] **DEMO-06**: Agent panel displays subprocess output (verify existing behavior works)
- [ ] **DEMO-07**: Agent subprocess handles SIGTERM gracefully (marks session escalated on shutdown)

### Architecture

- [ ] **ARCH-01**: Agent code (operator_core) contains no demo-specific logic (clean separation)

### Tests

- [ ] **TEST-01**: Integration test verifies TiKV demo runs without errors (startup, fault, recovery)
- [ ] **TEST-02**: Integration test verifies ratelimiter demo runs without errors (startup, fault, recovery)
- [ ] **TEST-03**: Unit test verifies agent schema initialization works correctly

## Future Requirements

Deferred enhancements (not in v3.1):

- Display structured audit session info in TUI panel
- Show agent reasoning summaries in real-time
- Replay agent sessions via TUI

## Out of Scope

| Feature | Reason |
|---------|--------|
| New TUI design | Keep existing Rich panels, just fix internals |
| Additional subjects | Focus on TiKV and ratelimiter only |
| Production approval layer | Separate milestone |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEMO-01 | Phase 33 | Pending |
| DEMO-02 | Phase 33 | Pending |
| DEMO-03 | Phase 33 | Pending |
| DEMO-07 | Phase 33 | Pending |
| ARCH-01 | Phase 33 | Pending |
| TEST-03 | Phase 33 | Pending |
| DEMO-04 | Phase 34 | Pending |
| DEMO-05 | Phase 34 | Pending |
| DEMO-06 | Phase 34 | Pending |
| TEST-01 | Phase 34 | Pending |
| TEST-02 | Phase 34 | Pending |

**Coverage:**
- v3.1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0

**Phase Distribution:**
- Phase 33 (Agent Database Integration): 6 requirements (DEMO-01, DEMO-02, DEMO-03, DEMO-07, ARCH-01, TEST-03)
- Phase 34 (Demo End-to-End Validation): 5 requirements (DEMO-04, DEMO-05, DEMO-06, TEST-01, TEST-02)

---
*Requirements defined: 2026-01-28*
*Last updated: 2026-01-28 after roadmap creation*
