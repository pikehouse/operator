# Requirements: Operator v2.0

**Defined:** 2026-01-25
**Core Value:** AI demonstrates real diagnostic reasoning about distributed systems - not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

## v2.0 Requirements

Requirements for action execution milestone. Each maps to roadmap phases.

### Action Framework

- [x] **ACT-01**: Action framework supports multiple action sources (subject-defined, tools, workflows)
- [x] **ACT-02**: Subject can define domain-specific actions (e.g., TiKV transfer-leader)
- [x] **ACT-03**: Agent can use general tools beyond subject-defined actions (with approval)
- [x] **ACT-04**: Agent can request an action based on diagnosis (action proposal)
- [x] **ACT-05**: Action parameters are validated before execution
- [x] **ACT-06**: Action execution result is tracked (success/failure, timing, error details)
- [x] **ACT-07**: All actions are recorded in audit log (who requested, what action, when, outcome)

### Workflow Actions

- [x] **WRK-01**: Agent can chain multiple actions into a workflow
- [x] **WRK-02**: Agent can schedule follow-up actions (e.g., "check again in 5 minutes")
- [x] **WRK-03**: Agent can retry failed actions with backoff

### Approval Workflow

- [x] **APR-01**: Action approval is configurable (on/off, default off — agent executes autonomously)
- [x] **APR-02**: When approval enabled, user can approve/reject pending actions via CLI

### Safety

- [x] **SAF-01**: Kill switch can halt all pending/in-progress actions
- [x] **SAF-02**: Observe-only mode disables all action execution (fallback to v1 behavior)

### TiKV Subject Actions

- [x] **TKV-01**: TiKV subject defines transfer-leader action
- [x] **TKV-02**: TiKV subject defines transfer-peer action (move region replica)
- [x] **TKV-03**: TiKV subject defines drain-store action (evict all leaders from store)

## Future Requirements

Deferred to v2.1+. Tracked but not in current roadmap.

### Dry-Run Mode

- **DRY-01**: Actions can be executed in dry-run mode (validate without executing)
- **DRY-02**: Dry-run produces preview output showing what would happen

### Advanced Approval

- **APR-03**: Risk-tiered approvals (low-risk auto-approve, high-risk require explicit)
- **APR-04**: Approval timeout with escalation
- **APR-05**: Slack/PagerDuty integration for approval notifications

### Advanced Safety

- **SAF-03**: Single action at a time (no concurrent modifications)
- **SAF-04**: Blast radius limits (max regions affected per action)
- **SAF-05**: Action rate limiting
- **SAF-06**: Automatic rollback on failure (where possible)

### Extended Actions

- **TKV-04**: TiKV subject defines split-region action
- **TKV-05**: TiKV subject defines merge-region action
- **TKV-06**: TiKV subject defines compact-store action

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Free-form command execution | AI hallucination risk - must use structured action types |
| Automatic action execution | Human approval is mandatory safety gate for v2 |
| Multi-subject actions | TiKV first, extract patterns later |
| Web dashboard for approvals | CLI-first for v2 |
| Production deployment | Local Docker Compose demo environment |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ACT-01 | Phase 12 | Complete |
| ACT-02 | Phase 13 | Complete |
| ACT-03 | Phase 15 | Complete |
| ACT-04 | Phase 12 | Complete |
| ACT-05 | Phase 12 | Complete |
| ACT-06 | Phase 12 | Complete |
| ACT-07 | Phase 12 | Complete |
| WRK-01 | Phase 15 | Complete |
| WRK-02 | Phase 15 | Complete |
| WRK-03 | Phase 15 | Complete |
| APR-01 | Phase 14 | Complete |
| APR-02 | Phase 14 | Complete |
| SAF-01 | Phase 12 | Complete |
| SAF-02 | Phase 12 | Complete |
| TKV-01 | Phase 13 | Complete |
| TKV-02 | Phase 13 | Complete |
| TKV-03 | Phase 13 | Complete |

**Coverage:**
- v2.0 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-01-25*
*Last updated: 2026-01-26 (Phase 15 requirements complete - v2.0 milestone complete)*
