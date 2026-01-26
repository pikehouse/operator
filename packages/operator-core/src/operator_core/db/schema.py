"""
SQLite schema for ticket and action persistence.

This module defines the database schema for:
- Ticket management (monitoring tickets for invariant violations)
- Action management (proposed and executed agent actions)

The schema supports:
- Ticket lifecycle management (status transitions)
- Deduplication via violation_key
- Flap detection via occurrence tracking
- Auto-resolve protection via held flag
- Action proposal lifecycle (proposed -> validated -> executing -> completed)
- Action execution records with audit trail
"""

SCHEMA_SQL = """
-- Ticket table with status transitions and deduplication
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    violation_key TEXT NOT NULL,           -- invariant_name:store_id for dedup
    invariant_name TEXT NOT NULL,
    store_id TEXT,                         -- NULL for cluster-wide violations
    status TEXT NOT NULL DEFAULT 'open',   -- open, acknowledged, diagnosed, resolved
    held BOOLEAN NOT NULL DEFAULT 0,       -- Prevent auto-resolve
    batch_key TEXT,                        -- Group related violations
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,           -- ISO8601 timestamp
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    message TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    diagnosis TEXT,                        -- Attached by AI in Phase 5
    metric_snapshot TEXT,                  -- JSON blob of metrics at violation time
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for finding open tickets by violation_key (deduplication)
CREATE INDEX IF NOT EXISTS idx_tickets_open_violation
ON tickets(violation_key) WHERE status != 'resolved';

-- Index for flap detection (recent tickets for same violation)
CREATE INDEX IF NOT EXISTS idx_tickets_violation_time
ON tickets(violation_key, resolved_at);

-- Trigger to update updated_at on modification
CREATE TRIGGER IF NOT EXISTS tickets_updated_at
AFTER UPDATE ON tickets
BEGIN
    UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""

ACTIONS_SCHEMA_SQL = """
-- Action proposals table for proposed agent actions
CREATE TABLE IF NOT EXISTS action_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,                      -- Optional link to ticket
    action_name TEXT NOT NULL,              -- Action method name (e.g., transfer_leader)
    action_type TEXT NOT NULL DEFAULT 'subject',  -- subject, tool, workflow
    parameters TEXT NOT NULL,               -- JSON blob of action arguments
    reason TEXT NOT NULL,                   -- Why this action is proposed
    status TEXT NOT NULL DEFAULT 'proposed', -- proposed, validated, executing, completed, failed, cancelled
    proposed_at TEXT NOT NULL,              -- ISO8601 timestamp
    proposed_by TEXT NOT NULL DEFAULT 'agent',  -- agent or user
    validated_at TEXT,                      -- When parameters were validated
    cancelled_at TEXT,                      -- When action was cancelled
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

-- Action execution records
CREATE TABLE IF NOT EXISTS action_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL,           -- Links to action_proposals
    started_at TEXT,                        -- Execution start time
    completed_at TEXT,                      -- Execution end time
    success INTEGER,                        -- 1=success, 0=failure, NULL=executing
    error_message TEXT,                     -- Error details if failed
    result_data TEXT,                       -- JSON blob of execution output
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (proposal_id) REFERENCES action_proposals(id)
);

-- Index for finding pending actions by status
CREATE INDEX IF NOT EXISTS idx_action_proposals_status
ON action_proposals(status);

-- Index for finding actions by ticket
CREATE INDEX IF NOT EXISTS idx_action_proposals_ticket
ON action_proposals(ticket_id);

-- Index for finding execution records by proposal
CREATE INDEX IF NOT EXISTS idx_action_records_proposal
ON action_records(proposal_id);

-- Trigger to update updated_at on action_proposals modification
CREATE TRIGGER IF NOT EXISTS action_proposals_updated_at
AFTER UPDATE ON action_proposals
BEGIN
    UPDATE action_proposals SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""
