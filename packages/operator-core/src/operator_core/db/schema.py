"""
SQLite schema for ticket and agent session persistence.

This module defines the database schema for:
- Ticket management (monitoring tickets for invariant violations)
- Agent session audit logging (v3 agent_lab)

The schema supports:
- Ticket lifecycle management (status transitions)
- Deduplication via violation_key
- Flap detection via occurrence tracking
- Auto-resolve protection via held flag
- Agent session tracking with tool call/result logging
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
    subject_context TEXT,                  -- Subject-specific agent prompt context
    variant_model TEXT,                    -- Variant model override (e.g., claude-sonnet-4-20250514)
    variant_system_prompt TEXT,            -- Variant system prompt override
    variant_tools_config TEXT,             -- Variant tools config JSON
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

AGENT_SCHEMA_SQL = """
-- Agent session audit tables
CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,        -- Format: {timestamp}-{uuid[:8]}
    ticket_id INTEGER,                      -- FK to tickets (NULL if not ticket-related)
    status TEXT NOT NULL DEFAULT 'running', -- running, completed, failed, escalated
    started_at TEXT NOT NULL,               -- ISO8601 timestamp
    ended_at TEXT,                          -- ISO8601 timestamp when session ended
    outcome_summary TEXT,                   -- Claude's final summary (Haiku-summarized)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

CREATE TABLE IF NOT EXISTS agent_log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,               -- FK to agent_sessions.session_id
    entry_type TEXT NOT NULL,               -- reasoning, tool_call, tool_result
    content TEXT NOT NULL,                  -- The summarized content
    raw_content TEXT,                       -- Optional: full content before summarization
    tool_name TEXT,                         -- For tool_call/tool_result entries
    tool_params TEXT,                       -- JSON for tool_call
    exit_code INTEGER,                      -- For tool_result entries
    timestamp TEXT NOT NULL,                -- ISO8601 timestamp
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
);

-- Indexes for agent audit tables
CREATE INDEX IF NOT EXISTS idx_agent_sessions_ticket
ON agent_sessions(ticket_id);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_status
ON agent_sessions(status);

CREATE INDEX IF NOT EXISTS idx_agent_log_entries_session
ON agent_log_entries(session_id);
"""
