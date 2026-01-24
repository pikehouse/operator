"""
SQLite schema for ticket persistence.

This module defines the database schema for storing monitoring tickets.
The schema supports:
- Ticket lifecycle management (status transitions)
- Deduplication via violation_key
- Flap detection via occurrence tracking
- Auto-resolve protection via held flag
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
