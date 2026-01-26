---
phase: 15
plan: 01
subsystem: actions
tags: [database, schema, workflow, scheduling, retry]
dependency-graph:
  requires: [14-01, 14-02]
  provides: [workflow-types, action-scheduling, retry-tracking]
  affects: [15-02, 15-03]
tech-stack:
  added: []
  patterns: [workflow-status-enum, pydantic-basemodel, sqlite-migrations]
key-files:
  created: []
  modified:
    - packages/operator-core/src/operator_core/actions/types.py
    - packages/operator-core/src/operator_core/db/schema.py
    - packages/operator-core/src/operator_core/db/actions.py
decisions:
  - id: WRK-SCHEMA-01
    choice: Add new columns to base schema AND migrations
    why: New databases get columns from CREATE TABLE, existing databases get them via ALTER TABLE
metrics:
  duration: 6m
  completed: 2026-01-26
---

# Phase 15 Plan 01: Schema Extensions for Workflows Summary

Extended database schema and action types for workflow chaining (WRK-01), scheduled execution (WRK-02), and retry tracking (WRK-03) using Pydantic models and SQLite migrations.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| b23df54 | feat | Extend ActionProposal with workflow and scheduling fields |
| e160680 | feat | Add workflows table and action proposal indexes |
| d0599ba | feat | Add database migrations for workflow/scheduling/retry columns |
| 0a34856 | fix | Include workflow/scheduling/retry fields in create_proposal INSERT |

## Changes Made

### types.py - Action Types

**Added WorkflowStatus enum:**
- `PENDING` - Workflow created, no actions started
- `IN_PROGRESS` - At least one action is executing
- `COMPLETED` - All actions completed successfully
- `FAILED` - At least one action failed
- `CANCELLED` - Workflow was cancelled

**Added WorkflowProposal model:**
- `id` - Database ID
- `name` - Workflow name (required)
- `description` - What this workflow accomplishes (required)
- `ticket_id` - Associated ticket for traceability
- `status` - Current WorkflowStatus
- `created_at` - When the workflow was created

**Extended ActionProposal with 8 new fields:**

Workflow fields (WRK-01):
- `workflow_id` - Parent workflow ID if part of a chain
- `execution_order` - Order within workflow (0-indexed)
- `depends_on_proposal_id` - Proposal ID that must complete first

Scheduling fields (WRK-02):
- `scheduled_at` - Execute at this time (None = immediate)

Retry fields (WRK-03):
- `retry_count` - Number of retry attempts so far
- `max_retries` - Maximum retry attempts (default 3)
- `next_retry_at` - When to retry next
- `last_error` - Error message from last failed attempt

### schema.py - Database Schema

**Added columns to action_proposals table definition:**
- workflow_id, execution_order, depends_on_proposal_id
- scheduled_at
- retry_count, max_retries, next_retry_at, last_error

**Added workflows table:**
- id, name, description, ticket_id, status, created_at, updated_at
- Foreign key to tickets table
- workflows_updated_at trigger

**Added indexes:**
- `idx_action_proposals_workflow` - Partial index on workflow_id
- `idx_action_proposals_scheduled` - Partial index on scheduled_at
- `idx_action_proposals_retry` - Partial index on next_retry_at

### actions.py - Database Operations

**Extended _ensure_schema():**
- Added migrations for all 8 new columns using try/except pattern
- Migrations are idempotent (safe to run on existing databases)

**Extended _row_to_proposal():**
- Parse scheduled_at and next_retry_at as datetime objects
- Map all new columns to ActionProposal fields with defaults

**Extended create_proposal():**
- Insert all new fields into database
- Convert datetime fields to ISO format strings

**Added imports:**
- WorkflowProposal, WorkflowStatus now imported

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] create_proposal not persisting new fields**
- **Found during:** Task 3 verification
- **Issue:** INSERT statement in create_proposal only included original fields, new workflow/scheduling/retry fields were not persisted
- **Fix:** Extended INSERT to include all 16 fields with proper datetime conversion
- **Files modified:** packages/operator-core/src/operator_core/db/actions.py
- **Commit:** 0a34856

## Decisions Made

### WRK-SCHEMA-01: Add columns to base schema AND migrations

**Context:** New columns need to exist for both new databases (CREATE TABLE) and existing databases (ALTER TABLE migrations).

**Options:**
1. Only add columns to base schema - breaks existing databases
2. Only add migrations - indexes referencing columns fail on new databases
3. Add to both base schema and migrations - works for all cases

**Choice:** Option 3 - Add columns to base schema (for new DBs) AND migrations (for existing DBs)

**Rationale:** SQLite partial indexes reference columns that must exist. The schema is executed first (creating table with columns), then migrations run (which no-op for new columns already present).

## Verification

All success criteria verified:
1. ActionProposal has 8 new fields
2. WorkflowStatus enum has 5 states
3. WorkflowProposal model exists with all attributes
4. ACTIONS_SCHEMA_SQL includes workflows table and 3 indexes
5. ActionDB migrations add columns without error on existing databases
6. _row_to_proposal correctly parses all new fields including datetime conversions

## Next Phase Readiness

**Ready for:**
- 15-02: Workflow chaining implementation (workflow_id, execution_order, depends_on_proposal_id)
- 15-03: Scheduled execution (scheduled_at field)
- Future: Retry with backoff (retry_count, max_retries, next_retry_at, last_error)

**Dependencies satisfied:**
- WorkflowProposal and WorkflowStatus types for workflow management
- Database schema for persisting workflow and action relationships
- Indexes for efficient queries on workflow_id, scheduled_at, next_retry_at
