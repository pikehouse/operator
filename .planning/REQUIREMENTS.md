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
| DEMO-01 | TBD | Pending |
| DEMO-02 | TBD | Pending |
| DEMO-03 | TBD | Pending |
| DEMO-04 | TBD | Pending |
| DEMO-05 | TBD | Pending |
| DEMO-06 | TBD | Pending |
| DEMO-07 | TBD | Pending |

**Coverage:**
- v3.1 requirements: 7 total
- Mapped to phases: 0
- Unmapped: 7

---
*Requirements defined: 2026-01-28*
*Last updated: 2026-01-28 after initial definition*
