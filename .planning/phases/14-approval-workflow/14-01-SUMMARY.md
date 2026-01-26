---
phase: 14
plan: 01
subsystem: actions
tags: [approval, database, schema, pydantic]

dependency-graph:
  requires:
    - phase-12 action infrastructure (ActionProposal, ActionDB, ActionStatus)
  provides:
    - approval columns in action_proposals table
    - approve_proposal/reject_proposal/is_approved methods in ActionDB
    - approval fields in ActionProposal model with is_approved computed property
  affects:
    - 14-02 (executor approval gate)
    - 14-03 (CLI approve/reject commands)

tech-stack:
  added: []
  patterns:
    - try/except ALTER TABLE migration pattern for schema evolution
    - computed_field decorator for derived properties in Pydantic models

key-files:
  created: []
  modified:
    - packages/operator-core/src/operator_core/db/schema.py
    - packages/operator-core/src/operator_core/db/actions.py
    - packages/operator-core/src/operator_core/actions/types.py

decisions:
  - id: D14-01-01
    choice: Five separate columns for approval state
    rationale: Complete audit trail - approved_at/by, rejected_at/by, rejection_reason
  - id: D14-01-02
    choice: Rejection also sets status to CANCELLED
    rationale: Rejected proposals should not be executable; aligns with existing lifecycle
  - id: D14-01-03
    choice: approve_proposal/reject_proposal require VALIDATED status
    rationale: Only validated proposals should be approvable; prevents approving incomplete proposals

metrics:
  duration: 8m
  completed: 2026-01-26
---

# Phase 14 Plan 01: Approval Infrastructure Summary

Approval columns in schema, ActionDB approval methods, ActionProposal model with is_approved property.

## What Was Built

### 1. Schema Changes (schema.py)

Added 5 approval columns to `action_proposals` table in `ACTIONS_SCHEMA_SQL`:
- `approved_at TEXT` - ISO8601 timestamp when approved
- `approved_by TEXT` - Who approved (typically "user")
- `rejected_at TEXT` - ISO8601 timestamp when rejected
- `rejected_by TEXT` - Who rejected
- `rejection_reason TEXT` - Why rejected

### 2. ActionDB Methods (actions.py)

Added migration logic in `_ensure_schema()` using try/except ALTER TABLE pattern (one column at a time with individual try/except blocks for robustness).

Added three new methods:
- `is_approved(proposal_id: int) -> bool` - Returns True if approved_at is not None
- `approve_proposal(proposal_id: int, approved_by: str = "user") -> None` - Sets approved_at/approved_by for VALIDATED proposals
- `reject_proposal(proposal_id: int, rejected_by: str = "user", reason: str = "") -> None` - Sets rejection fields and updates status to CANCELLED

Updated `_row_to_proposal()` to parse new fields from database rows.

### 3. ActionProposal Model (types.py)

Added 5 optional fields:
- `approved_at: datetime | None`
- `approved_by: str | None`
- `rejected_at: datetime | None`
- `rejected_by: str | None`
- `rejection_reason: str | None`

Added computed property:
- `is_approved` - Returns `self.approved_at is not None`

## Decisions Made

| ID | Decision | Context | Rationale |
|----|----------|---------|-----------|
| D14-01-01 | Five separate columns | Could have used single approval_status enum | Complete audit trail with timestamps and actors for both approve and reject |
| D14-01-02 | Rejection cancels proposal | Could leave status unchanged | Rejected proposals should not be executable; consistent with existing lifecycle |
| D14-01-03 | Require VALIDATED status | Could allow approval of any status | Only validated proposals have verified parameters; prevents approving incomplete work |

## Deviations from Plan

None - plan executed exactly as written.

## Commit Log

| Hash | Type | Description |
|------|------|-------------|
| faca52e | feat | Add approval columns and methods to ActionDB |
| 849ea35 | feat | Add approval fields to ActionProposal model |

## Next Phase Readiness

**Ready for 14-02:** Approval infrastructure in place. Next plan adds:
- Approval gate in ActionExecutor.execute_proposal
- ApprovalRequiredError exception
- Check both global approval_mode and per-action requires_approval

**No blockers.** All approval state persistence is complete.
