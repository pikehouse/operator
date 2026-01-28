---
phase: 23
plan: 03
subsystem: actions
tags: [security, toctou, approval, audit, concurrency]
dependencies:
  requires: [23-01, 23-02]
  provides:
    - TOCTOU-resistant approval workflow
    - Token-based approval verification
    - Optimistic locking for concurrent modifications
    - Dual identity audit logging
  affects: [23-04, 24-docker-actions, 25-host-actions]
tech-stack:
  added: []
  patterns:
    - Double-check pattern for TOCTOU defense
    - Optimistic locking with version field
    - asyncio.Lock for execution serialization
    - Token expiration (60s window)
key-files:
  created:
    - packages/operator-core/src/operator_core/actions/exceptions.py
  modified:
    - packages/operator-core/src/operator_core/actions/types.py
    - packages/operator-core/src/operator_core/db/schema.py
    - packages/operator-core/src/operator_core/db/actions.py
    - packages/operator-core/src/operator_core/actions/executor.py
    - packages/operator-core/src/operator_core/actions/audit.py
decisions:
  - id: SAFE-01-implementation
    decision: Use asyncio.Lock + double-check pattern for TOCTOU defense
    rationale: Lock serializes execution attempts; double-check detects concurrent modifications that occurred while waiting
    alternatives: Database-level locks (more complex, less portable)
  - id: SAFE-02-token-expiry
    decision: 60-second approval token expiration window
    rationale: Balance between usability and security - long enough for execution but prevents stale approvals
    alternatives: 30s (too tight), 300s (too loose)
  - id: version-increment
    decision: Increment version on every proposal update, not just status changes
    rationale: Detect any concurrent modification, not just status changes
    alternatives: Version only on status change (misses parameter updates)
  - id: dual-identity-audit
    decision: Log both requester_id and agent_id in execution events
    rationale: Full authorization chain visibility for compliance and debugging
    alternatives: Single actor field (loses delegation context)
metrics:
  duration: "4m 19s"
  completed: "2026-01-28"
---

# Phase 23 Plan 03: TOCTOU-Resistant Approval Workflow Summary

**One-liner:** Cryptographic approval tokens with 60s expiry, asyncio.Lock-protected double-check execution, optimistic locking via version field, and dual identity audit logging

## What Was Built

Implemented comprehensive TOCTOU (Time-Of-Check Time-Of-Use) defense for the action approval and execution workflow. The system now prevents race conditions where proposal state changes between approval and execution through multiple defensive layers.

### Key Components

**1. Approval Token System (SAFE-02)**
- Cryptographic tokens generated via `secrets.token_urlsafe(32)` on approval
- 60-second expiration window to prevent stale approvals
- Token verification required before execution
- Raises `ApprovalExpiredError` if expired, `InvalidTokenError` if mismatch

**2. Optimistic Locking (SAFE-01)**
- Added `version` field to ActionProposal (default: 1)
- New `update_proposal_status_with_version()` method checks version in WHERE clause
- Version incremented atomically on successful update
- Returns boolean: True for success, False for concurrent modification detected

**3. Double-Check Execution Pattern (SAFE-01)**
Implemented in `ActionExecutor.execute_proposal()`:
1. **Pre-check outside lock**: Fast rejection of invalid states
2. **Acquire asyncio.Lock**: Serialize concurrent execution attempts
3. **Re-check inside lock**: Detect modifications that occurred while waiting
4. **Atomic update with version check**: Final TOCTOU defense via optimistic locking

**4. TOCTOU Exception Classes**
- `ApprovalExpiredError`: Token older than 60s
- `StateChangedError`: Concurrent modification detected (status, approval, version)
- `InvalidTokenError`: Token mismatch on execution

**5. Dual Identity Audit Logging (SAFE-04, SAFE-05)**
- Updated `log_execution_started()` to accept `requester_id` and `agent_id`
- Stores both identities in `event_data` for full authorization chain
- Supports OAuth delegation model (requester = resource owner, agent = client)

## Deviations from Plan

None - plan executed exactly as written.

## Files Modified

### Created
- `packages/operator-core/src/operator_core/actions/exceptions.py` (79 lines)
  - Three TOCTOU exception classes with context attributes

### Modified
- `packages/operator-core/src/operator_core/actions/types.py`
  - Added `approval_token` and `version` fields to ActionProposal

- `packages/operator-core/src/operator_core/db/schema.py`
  - Added `approval_token TEXT` and `version INTEGER DEFAULT 1` columns to schema

- `packages/operator-core/src/operator_core/db/actions.py`
  - Added migration logic for new columns
  - Updated `_row_to_proposal()` to read approval_token and version
  - Updated `create_proposal()` to insert approval_token and version
  - Modified `approve_proposal()` to generate and return token
  - Added `update_proposal_status_with_version()` for optimistic locking

- `packages/operator-core/src/operator_core/actions/executor.py`
  - Added `asyncio.Lock` to `__init__`
  - Added `_is_approval_expired()` helper method
  - Rewrote `execute_proposal()` with double-check pattern and TOCTOU defenses
  - Added `approval_token` parameter to execute_proposal

- `packages/operator-core/src/operator_core/actions/audit.py`
  - Updated `log_execution_started()` to accept and log dual identity

## Testing & Verification

All verification tests passed:

1. **Task 1**: Approval token generation and storage
   - Verified 43-char token from `secrets.token_urlsafe(32)`
   - Confirmed token stored in database and retrieved correctly

2. **Task 2**: Optimistic locking
   - Correct version update succeeds
   - Stale version update fails (returns False)
   - Version increments atomically

3. **Task 3**: Exception classes
   - All three exception types instantiate correctly
   - Context attributes (proposal_id, age_seconds, reason) work as expected

4. **Task 4**: Executor structure
   - `_execution_lock` initialized in `__init__`
   - `_is_approval_expired` method exists
   - `execute_proposal` accepts `approval_token` parameter

5. **Task 5**: Concurrent modification detection (key link verification)
   - Two concurrent reads get same version
   - First update succeeds
   - Second update fails with version mismatch
   - Version incremented only once
   - **This test explicitly verified the optimistic locking key link works under concurrent access**

6. **Task 6**: Dual identity audit logging
   - Both `requester_id` and `agent_id` stored in event_data
   - Retrieved correctly from audit log

## Key Links Verified

The must_haves specified three key links, all verified:

1. **executor.py execute_proposal → asyncio.Lock**
   - Pattern: `async with self._execution_lock`
   - Implementation: Lock acquired before re-check and atomic update

2. **executor.py → db update with version**
   - Pattern: `expected_version` parameter
   - Implementation: `update_proposal_status_with_version()` called with read_version

3. **audit.py → dual identity logging**
   - Pattern: `requester_id.*agent_id` in event_data
   - Implementation: Both identities passed to and stored by log_execution_started()

## Decisions Made

**D1: Double-check pattern implementation**
- Chose asyncio.Lock over database-level locks for portability and simplicity
- Four-phase approach (pre-check, lock, re-check, atomic update) provides defense-in-depth

**D2: 60-second token expiration**
- Balance between usability (enough time for execution) and security (prevents stale approvals)
- Alternative 30s too tight for user workflows, 300s too loose for safety

**D3: Version increment strategy**
- Increment on every update, not just status changes
- Catches parameter modifications and other concurrent changes

**D4: Dual identity in audit events**
- Separate requester_id and agent_id fields rather than single actor
- Preserves OAuth delegation context for compliance and debugging

## Requirements Satisfied

- **SAFE-01**: TOCTOU defense via double-check pattern + optimistic locking
- **SAFE-02**: Token expiration (60s) and cryptographic token generation
- **SAFE-04**: Dual authorization support (requester + agent identities)
- **SAFE-05**: Audit logging with both requester_id and agent_id

## Integration Points

**Upstream dependencies:**
- Builds on 23-01 (dual identity fields in ActionProposal)
- Uses secret redaction from 23-02 for audit event_data

**Downstream impacts:**
- 23-04 (session risk scoring) will use audit events with dual identity
- 24-docker-actions will inherit TOCTOU-resistant execution
- 25-host-actions will inherit TOCTOU-resistant execution

## Next Phase Readiness

**Ready for Phase 23-04 (Session Risk Scoring):**
- Audit logs include dual identity for risk attribution
- Execution events logged with full context

**Blockers:** None

**Concerns:** None

## Commits

| Commit | Description |
|--------|-------------|
| e67c945 | feat(23-03): add approval_token and version fields for TOCTOU defense |
| 078402c | feat(23-03): implement optimistic locking for concurrent modification detection |
| b23e42e | feat(23-03): add TOCTOU exception classes |
| c6f1d8e | feat(23-03): implement TOCTOU-resistant execute_proposal with lock |
| 24a75e8 | feat(23-03): add dual identity logging to execution audit events |

## Lessons Learned

**What worked well:**
- Four-phase execution pattern (pre-check, lock, re-check, atomic update) is clear and testable
- Optimistic locking with version field is simple and effective
- Test-driven verification caught edge cases early

**What could improve:**
- Consider adding metrics for lock contention and version conflicts
- May need to tune 60s expiration window based on production usage

**Technical insights:**
- asyncio.Lock is sufficient for this use case - no need for distributed locks yet
- Double-check pattern essential even with lock due to async gap between read and lock acquisition
- Optimistic locking test (Task 5) validates the critical path under concurrent access
