---
phase: 15
plan: 02
subsystem: actions
tags: [database, workflow, scheduling, retry, query-methods]
dependency-graph:
  requires: [15-01]
  provides: [workflow-crud, scheduling-queries, retry-queries]
  affects: [15-03, 15-04]
tech-stack:
  added: []
  patterns: [async-context-manager, row-factory, iso8601-datetime]
key-files:
  created: []
  modified:
    - packages/operator-core/src/operator_core/db/actions.py
decisions:
  - id: WRK-DB-01
    choice: Workflow actions include approved_at check OR workflow_id check
    why: Workflow-level approval can cover all actions, or individual approval applies
metrics:
  duration: 3m
  completed: 2026-01-26
---

# Phase 15 Plan 02: Workflow Database Methods Summary

Extended ActionDB with methods for workflow management (WRK-01), scheduled action queries (WRK-02), and retry tracking (WRK-03) to enable executor and agent runner to work with workflows.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| ff8be6f | feat | Add workflow CRUD methods to ActionDB |
| 16a0ba6 | feat | Add scheduling query methods to ActionDB |
| 53dedaa | feat | Add retry query and update methods to ActionDB |

## Changes Made

### actions.py - Workflow Operations (WRK-01)

**Added _row_to_workflow helper:**
- Converts database row to WorkflowProposal
- Parses created_at as datetime
- Maps WorkflowStatus enum

**Added create_workflow method:**
- Creates workflow row in workflows table
- Creates each action proposal with workflow_id and execution_order
- Returns the created workflow ID
- Commits transaction atomically

**Added list_workflow_actions method:**
- Returns actions for a workflow ordered by execution_order ASC
- Uses _row_to_proposal for conversion

**Added get_workflow method:**
- Fetches WorkflowProposal by ID
- Returns None if not found

**Added update_workflow_status method:**
- Updates workflow status to any WorkflowStatus value
- Commits change immediately

### actions.py - Scheduling Operations (WRK-02)

**Added list_ready_scheduled method:**
- Returns validated actions ready for scheduled execution
- Filters: status='validated', scheduled_at <= now
- Requires approved_at IS NOT NULL OR workflow_id IS NOT NULL
- Orders by scheduled_at ASC for FIFO processing

**Added update_scheduled_at method:**
- Sets or clears scheduled_at timestamp
- Accepts datetime or None

### actions.py - Retry Operations (WRK-03)

**Added list_retry_eligible method:**
- Returns failed actions eligible for retry
- Filters: status='failed', retry_count < max_retries, next_retry_at <= now
- Orders by next_retry_at ASC for FIFO processing

**Added increment_retry_count method:**
- Increments retry_count by 1
- Records error message in last_error

**Added update_next_retry method:**
- Sets or clears next_retry_at timestamp
- Used by retry scheduler to set exponential backoff times

**Added reset_for_retry method:**
- Sets status back to 'validated'
- Clears next_retry_at
- Called before retrying an action

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

### WRK-DB-01: Scheduling query includes workflow check

**Context:** list_ready_scheduled needs to determine if an action is approved.

**Options:**
1. Only check approved_at - requires individual approval for each action
2. Only check workflow_id - assumes all workflow actions are auto-approved
3. Check approved_at OR workflow_id - flexible approval model

**Choice:** Option 3 - Check both conditions

**Rationale:** Actions can be approved individually (approved_at set) OR implicitly via workflow membership. This supports both single-action approval and batch workflow approval.

## Verification

All 10 success criteria verified:

1. create_workflow creates workflow row and links actions with execution_order
2. list_workflow_actions returns actions for workflow in execution_order
3. get_workflow returns WorkflowProposal with correct status
4. update_workflow_status changes workflow status
5. list_ready_scheduled returns validated+scheduled+approved actions where scheduled_at <= now
6. update_scheduled_at sets/clears scheduled_at timestamp
7. list_retry_eligible returns failed actions with retry_count < max_retries where next_retry_at <= now
8. increment_retry_count increases count and records error
9. update_next_retry sets/clears next_retry_at timestamp
10. reset_for_retry sets status back to validated and clears next_retry_at

## Next Phase Readiness

**Ready for:**
- 15-03: ActionExecutor can use create_workflow, list_workflow_actions for workflow execution
- 15-03: ActionExecutor can use list_retry_eligible, reset_for_retry for retry handling
- 15-04: Scheduler can use list_ready_scheduled, update_scheduled_at for timed execution

**Exports available:**
- `create_workflow(name, description, actions, ticket_id)` - Create workflow with actions
- `list_workflow_actions(workflow_id)` - Get actions in execution order
- `get_workflow(workflow_id)` - Fetch workflow by ID
- `update_workflow_status(workflow_id, status)` - Change workflow status
- `list_ready_scheduled()` - Find scheduled actions past due
- `update_scheduled_at(proposal_id, scheduled_at)` - Set/clear schedule
- `list_retry_eligible()` - Find failed actions ready for retry
- `increment_retry_count(proposal_id, error_message)` - Record retry attempt
- `update_next_retry(proposal_id, next_retry_at)` - Set next retry time
- `reset_for_retry(proposal_id)` - Reset action for retry execution
