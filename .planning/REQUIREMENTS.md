# Requirements: Operator v2.2 Agentic Remediations Demo

**Defined:** 2026-01-27
**Core Value:** AI demonstrates complete agentic loop — detect issue, diagnose root cause, execute remediation, verify fix

## v2.2 Requirements

Requirements for agentic remediation demo. Builds on v2.0 action framework and v2.1 multi-subject support.

### Demo Configuration

- [ ] **DEMO-01**: Demo runs in EXECUTE mode by default (not OBSERVE)
- [ ] **DEMO-02**: Approval workflow disabled during demo (autonomous execution)
- [ ] **DEMO-03**: Demo script supports --observe flag to fall back to observe-only mode

### Agent Agentic Loop

- [ ] **AGENT-01**: Agent executes recommended action immediately after diagnosis
- [ ] **AGENT-02**: Agent waits fixed delay (5s) after action execution before verification
- [ ] **AGENT-03**: Agent queries subject metrics to verify fix after delay
- [ ] **AGENT-04**: Agent outputs verification result (success/failure) to log

### TiKV Demo Chapters

- [ ] **TIKV-01**: Chapter narratives updated to describe agentic remediation flow
- [ ] **TIKV-02**: Node kill chaos → transfer-leader action → verify regions rebalanced
- [ ] **TIKV-03**: Demo shows complete loop in agent panel (diagnosis + action + verification)

### Rate Limiter Demo Chapters

- [ ] **RLIM-01**: Chapter narratives updated to describe agentic remediation flow
- [ ] **RLIM-02**: Counter drift chaos → reset_counter action → verify counters aligned
- [ ] **RLIM-03**: Demo shows complete loop in agent panel (diagnosis + action + verification)

## Future Requirements

### Extended Verification

- **VERIFY-01**: Poll until resolved with timeout (instead of fixed delay)
- **VERIFY-02**: Different wait times per action type
- **VERIFY-03**: Verification failure triggers secondary action

### Demo Recording

- **REC-01**: Export demo session as video/GIF
- **REC-02**: Generate demo transcript

## Out of Scope

| Feature | Reason |
|---------|--------|
| Human approval during demo | Defeats purpose of "agentic" demo |
| Verification via invariant re-check | Metrics more direct, faster for demo |
| Production safety for autonomous mode | Demo only, not production deployment |
| Multi-action workflows in demo | Keep demo simple, single action per fault |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEMO-01 | TBD | Pending |
| DEMO-02 | TBD | Pending |
| DEMO-03 | TBD | Pending |
| AGENT-01 | TBD | Pending |
| AGENT-02 | TBD | Pending |
| AGENT-03 | TBD | Pending |
| AGENT-04 | TBD | Pending |
| TIKV-01 | TBD | Pending |
| TIKV-02 | TBD | Pending |
| TIKV-03 | TBD | Pending |
| RLIM-01 | TBD | Pending |
| RLIM-02 | TBD | Pending |
| RLIM-03 | TBD | Pending |

**Coverage:**
- v2.2 requirements: 13 total
- Mapped to phases: 0
- Unmapped: 13 ⚠️

---
*Requirements defined: 2026-01-27*
*Last updated: 2026-01-27 after initial definition*
