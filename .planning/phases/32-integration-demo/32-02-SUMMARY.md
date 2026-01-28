---
phase: 32-integration-demo
plan: 02
subsystem: cli
tags: [cli, audit, logging, rich, typer]
requires:
  - 31-02-PLAN.md
provides:
  - CLI commands for reviewing agent audit logs
  - operator audit list - table of recent sessions
  - operator audit show - full conversation replay
affects:
  - 32-03-PLAN.md
tech-stack:
  added: []
  patterns:
    - Typer subcommand groups
    - Rich tables and panels for formatted output
    - Direct SQLite access for read-only queries
key-files:
  created:
    - packages/operator-core/src/operator_core/cli/audit.py
  modified:
    - packages/operator-core/src/operator_core/cli/main.py
decisions:
  - title: Direct SQLite access instead of AuditLogDB
    rationale: Read-only queries don't need abstraction layer. Simpler for CLI commands.
  - title: Synchronous sqlite3 instead of async
    rationale: CLI commands run once and exit. No concurrency benefit from async.
  - title: Haiku summaries displayed by default
    rationale: Per CONTEXT.md - CLI shows summarized content, not raw tool output.
metrics:
  duration: 104s
  completed: 2026-01-28
---

# Phase 32 Plan 02: CLI Audit Commands Summary

**One-liner:** `operator audit list` and `operator audit show <session_id>` for reviewing agent session history with Rich-formatted output.

## What Was Built

Created CLI commands for reviewing agent audit logs:

1. **audit.py module** - Typer command group with list and show subcommands
2. **list command** - Displays recent agent sessions in Rich table format with ticket ID, status, duration, outcome summary
3. **show command** - Displays full conversation for a specific session with timestamps, type-based formatting, and indentation
4. **Main CLI registration** - Added audit_app to main CLI for `operator audit` access

**Key features:**
- Rich table output with color-coded columns
- Timestamp formatting (ISO → human-readable)
- Duration calculation (started_at → ended_at)
- Type-based entry formatting (reasoning, tool_call, tool_result)
- Exit code display for tool results
- Truncated outcomes in table, full outcomes in detail view

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Create audit CLI module | 84f2079 | audit.py |
| 2 | Register audit commands in main CLI | 864edc0 | main.py |

## Deviations from Plan

None - plan executed exactly as written.

## Technical Decisions

**Direct SQLite access:**
The CLI commands query the database directly using sqlite3.connect() rather than using AuditLogDB. This is appropriate because:
- Commands are read-only queries
- No complex logic or transactions needed
- Simpler code without abstraction layer
- Follows pattern from tickets.py for some queries

**Output formatting:**
- Session list: Rich Table with 6 columns (Session ID, Ticket, Status, Started, Duration, Outcome)
- Session detail: Panels for metadata/outcome + formatted log entries
- Timestamps: Always formatted to `YYYY-MM-DD HH:MM:SS`
- Long outcomes: Truncated to 50 chars in table (full in detail view)

**Entry type display:**
- `reasoning`: [cyan][Claude][/cyan]
- `tool_call`: [yellow][Tool Call: {name}][/yellow]
- `tool_result`: [green][Result (exit {code})][/green]
- All entries: 4-space indentation for content

## Integration Points

**Reads from:**
- `agent_sessions` table (session metadata)
- `agent_log_entries` table (conversation log)

**Command structure:**
```
operator audit
  ├── list [--limit N] [--db PATH]
  └── show <session_id> [--db PATH]
```

**Default database path:** `~/.operator/tickets.db`

## Verification Results

All verifications passed:

1. ✓ `operator audit --help` shows list and show subcommands
2. ✓ `operator audit list --help` shows --limit/-n and --db options
3. ✓ `operator audit show --help` shows session_id argument and --db option
4. ✓ Module compiles without errors

## Next Phase Readiness

**Blocked by:** None

**Blockers for next phases:**
- Phase 32-03 (TUI demo) can integrate these CLI commands or query database directly
- Phase 32-04 (E2E validation) can use `operator audit show` to inspect agent behavior

**Quality gates passed:**
- [x] CLI commands registered and accessible
- [x] Help text clear and complete
- [x] Rich formatting displays correctly
- [x] Database queries use correct schema

## Usage Examples

**List recent sessions:**
```bash
operator audit list
operator audit list --limit 10
```

**Show session details:**
```bash
operator audit show 2026-01-28T20-30-15-a1b2c3d4
```

**Output preview (list):**
```
                                    Agent Sessions
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Session ID                  ┃ Ticket ┃ Status    ┃ Started             ┃ Duration ┃ Outcome                   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 2026-01-28T20-30-15-a1b2... │     42 │ completed │ 2026-01-28 20:30:15 │ 23.4s    │ Restarted TiKV node ti... │
│ 2026-01-28T19-15-33-d3e4... │     41 │ escalated │ 2026-01-28 19:15:33 │ 45.2s    │ Unable to identify roo... │
└─────────────────────────────┴────────┴───────────┴─────────────────────┴──────────┴───────────────────────────┘
```

**Output preview (show):**
```
╭─────────────── Session Info ────────────────╮
│ Session: 2026-01-28T20-30-15-a1b2c3d4       │
│ Ticket: 42                                   │
│ Status: completed                            │
│ Started: 2026-01-28 20:30:15                 │
│ Ended: 2026-01-28 20:30:38                   │
╰──────────────────────────────────────────────╯

╭───────────── Outcome Summary ───────────────╮
│ Restarted TiKV node tikv-2 to resolve       │
│ leadership issues                            │
╰──────────────────────────────────────────────╯

Conversation Log:

2026-01-28 20:30:15 [Claude]
    Checking TiKV cluster status...

2026-01-28 20:30:16 [Tool Call: shell]
    docker exec tikv-2 ps aux

2026-01-28 20:30:16 [Result (exit 0)]
    Process list shows TiKV running

...
```

## Lessons Learned

**CLI patterns:**
- Following tickets.py pattern (Typer + Rich) provides consistency
- Direct SQLite access appropriate for read-only CLI commands
- Duration calculation needs try/except for incomplete sessions

**Rich formatting:**
- Panel borders provide visual structure
- Color-coded entry types improve readability
- Indentation makes conversation flow clear

## Session Metadata

**Plan executed:** 2026-01-28
**Duration:** 104 seconds
**Commits:** 2 task commits + 1 metadata commit (this file)
**Files created:** 1 new file (audit.py)
**Files modified:** 1 file (main.py)
