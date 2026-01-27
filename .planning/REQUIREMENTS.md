# Requirements: Operator v2.2 Agentic Remediations Demo

**Defined:** 2026-01-27
**Core Value:** AI demonstrates complete agentic loop — detect issue, diagnose root cause, execute remediation, verify fix

## v2.2 Requirements

Requirements for agentic remediation demo. Builds on v2.0 action framework and v2.1 multi-subject support.

### Demo Configuration

- [x] **DEMO-01**: Demo runs in EXECUTE mode (autonomous execution, no approval workflow)

### Agent Agentic Loop

- [x] **AGENT-01**: Agent executes recommended action immediately after diagnosis
- [x] **AGENT-02**: Agent waits fixed delay (5s) after action execution before verification
- [x] **AGENT-03**: Agent queries subject metrics to verify fix after delay
- [x] **AGENT-04**: Agent outputs verification result (success/failure) to log

### TiKV Demo Chapters

- [x] **TIKV-01**: Chapter narratives updated to describe agentic remediation flow
- [x] **TIKV-02**: Node kill chaos -> transfer-leader action -> verify regions rebalanced
- [x] **TIKV-03**: Demo shows complete loop in agent panel (diagnosis + action + verification)

### Rate Limiter Demo Chapters

- [x] **RLIM-01**: Chapter narratives updated to describe agentic remediation flow
- [x] **RLIM-02**: Counter drift chaos -> reset_counter action -> verify counters aligned
- [x] **RLIM-03**: Demo shows complete loop in agent panel (diagnosis + action + verification)

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
| Observe-only mode flag | Simplify - one mode only (EXECUTE) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEMO-01 | 21 | Complete |
| AGENT-01 | 21 | Complete |
| AGENT-02 | 21 | Complete |
| AGENT-03 | 21 | Complete |
| AGENT-04 | 21 | Complete |
| TIKV-01 | 22 | Complete |
| TIKV-02 | 22 | Complete |
| TIKV-03 | 22 | Complete |
| RLIM-01 | 22 | Complete |
| RLIM-02 | 22 | Complete |
| RLIM-03 | 22 | Complete |

**Coverage:**
- v2.2 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0

---
*Requirements defined: 2026-01-27*
*Last updated: 2026-01-27 after roadmap creation*
