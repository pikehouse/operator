# Phase 33: Agent Database Integration - Research

**Researched:** 2026-01-28
**Domain:** Internal codebase patterns - database lifecycle, schema initialization, graceful shutdown
**Confidence:** HIGH

## Summary

This research investigates the existing codebase patterns for database lifecycle management, particularly how to fix the agent subprocess to initialize schema before first query. The problem is that `agent_lab/ticket_ops.py` uses raw `sqlite3.connect()` without schema initialization, causing "no such table" errors when the demo deletes tickets.db.

The research reveals clear patterns already established in the codebase:
1. **Schema Initialization Pattern**: `AuditLogDB` provides the canonical example - uses context manager with `_ensure_schema()` method that calls `executescript(SCHEMA_SQL)` on connection
2. **Graceful Shutdown Pattern**: `MonitorLoop` demonstrates signal handling with `asyncio.Event` and `loop.add_signal_handler()`
3. **Testing Pattern**: `test_loop_audit.py` shows how to test database operations with tempfile and schema initialization

The solution is straightforward: create a synchronous `TicketOpsDB` context manager (mirroring `AuditLogDB` pattern) and integrate signal handling into `run_agent_loop()` (mirroring `MonitorLoop` pattern).

**Primary recommendation:** Follow the existing `AuditLogDB` pattern for schema initialization in `ticket_ops.py`, and mirror `MonitorLoop`'s signal handling in `loop.py` for graceful shutdown.

## Standard Stack

This is internal codebase research - no external libraries needed beyond what's already in use.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3 | stdlib | Synchronous database operations | Already used in ticket_ops.py |
| aiosqlite | Current | Async database operations | Already used in TicketDB |
| signal | stdlib | SIGTERM/SIGINT handling | Already used in MonitorLoop |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tempfile | stdlib | Test database creation | Testing schema initialization |
| pytest | Current | Unit testing | Verifying agent schema init |

## Architecture Patterns

### Pattern 1: Schema Initialization with Context Manager (from AuditLogDB)

**What:** Synchronous context manager that ensures schema exists on connection
**When to use:** Any database operation module that needs schema guarantees
**Source:** `packages/operator-core/src/operator_core/db/audit_log.py`

**Example:**
```python
# Source: packages/operator-core/src/operator_core/db/audit_log.py (lines 24-63)
class AuditLogDB:
    """Synchronous context manager for agent audit logging."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "AuditLogDB":
        """Open database connection and ensure schema exists."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        from operator_core.db.schema import SCHEMA_SQL, ACTIONS_SCHEMA_SQL
        self._conn.executescript(SCHEMA_SQL)
        self._conn.executescript(ACTIONS_SCHEMA_SQL)
        self._conn.commit()
```

**Key insight:**
- `_ensure_schema()` is idempotent - safe to call on every connection
- Uses `executescript()` to run multiple statements with CREATE IF NOT EXISTS
- Commits after schema creation to ensure persistence
- Context manager pattern ensures proper cleanup

### Pattern 2: Graceful Shutdown with Signal Handling (from MonitorLoop)

**What:** Async daemon that responds to SIGINT/SIGTERM by setting shutdown event
**When to use:** Long-running daemon processes that need clean shutdown
**Source:** `packages/operator-core/src/operator_core/monitor/loop.py`

**Example:**
```python
# Source: packages/operator-core/src/operator_core/monitor/loop.py (lines 84-123)
async def run(self) -> None:
    """Run the monitor loop until shutdown signal."""
    loop = asyncio.get_running_loop()

    # Register signal handlers per RESEARCH.md Pattern 2
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            functools.partial(self._handle_signal, sig),
        )

    print(f"Monitor loop starting...")

    async with TicketDB(self.db_path) as db:
        while not self._shutdown.is_set():
            await self._check_cycle(db)
            self._log_heartbeat()

            # Wait for interval or shutdown signal
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.interval,
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop

    print("Monitor loop stopped")

def _handle_signal(self, sig: signal.Signals) -> None:
    """Handle shutdown signal by setting shutdown event."""
    print(f"Received {sig.name}, shutting down...")
    self._shutdown.set()
```

**Key insight:**
- Register signal handlers INSIDE the run() method using `asyncio.get_running_loop()`
- Use `asyncio.Event` for shutdown coordination, not global flags
- `_shutdown.set()` breaks the loop, letting cleanup code in context manager run
- Context manager pattern ensures database connection closes properly

### Pattern 3: Mixed Sync/Async in Agent Loop

**What:** Agent loop is synchronous (not async) because tool_runner and Anthropic client are sync
**Current state:** `run_agent_loop()` in `loop.py` is synchronous function with `while True` loop
**Challenge:** Signal handlers need `asyncio.get_running_loop()` but agent loop isn't async

**Solution approach:**
```python
# For synchronous loops, use threading-based signal handling
import signal
import threading

def run_agent_loop(db_path: Path, audit_dir: Path | None = None) -> None:
    shutdown_event = threading.Event()
    current_session: tuple[str, int] | None = None  # (session_id, ticket_id)

    def handle_signal(sig, frame):
        print(f"\nReceived {signal.Signals(sig).name}, shutting down gracefully...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    client = anthropic.Anthropic()

    while not shutdown_event.is_set():
        ticket = poll_for_open_ticket(db_path)

        if ticket:
            with AuditLogDB(db_path) as audit_db:
                session_id = audit_db.create_session(ticket.id)
                current_session = (session_id, ticket.id)

                try:
                    status, summary = process_ticket(client, ticket, audit_db, session_id)
                    audit_db.complete_session(session_id, status, summary)
                    # Update ticket...
                except KeyboardInterrupt:
                    # Mark session as escalated on interrupt
                    audit_db.complete_session(session_id, "escalated", "Interrupted by shutdown signal")
                    update_ticket_escalated(db_path, ticket.id, "Agent shutdown during processing")
                    break
                finally:
                    current_session = None

        if shutdown_event.wait(timeout=1.0):
            break

    print("Agent loop stopped")
```

**Key insight:**
- Synchronous loops use `signal.signal()` not `loop.add_signal_handler()`
- Use `threading.Event` not `asyncio.Event` for sync coordination
- Track current session state so signal handler knows what to clean up
- Use `event.wait(timeout=1.0)` instead of `time.sleep()` for interruptible sleep

### Pattern 4: Test Pattern for Database Initialization

**What:** Test that schema initialization works correctly using tempfile
**Source:** `packages/operator-core/tests/test_loop_audit.py`

**Example:**
```python
# Source: packages/operator-core/tests/test_loop_audit.py (lines 15-23)
def test_process_ticket_logs_complete_audit_trail():
    """Verify that process_ticket logs reasoning, tool_call, and tool_result entries."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # ... test code that uses the database ...

        # Create audit DB and session (schema auto-initialized)
        with AuditLogDB(db_path) as audit_db:
            session_id = audit_db.create_session(1)
            # ... test operations ...
    finally:
        # Cleanup
        db_path.unlink(missing_ok=True)
```

**Key insight:**
- Use `tempfile.NamedTemporaryFile(delete=False)` to get a path but not auto-delete
- Context manager automatically initializes schema on first use
- Explicit cleanup in `finally` block ensures no test pollution

### Anti-Patterns to Avoid

- **Raw sqlite3.connect() without schema init**: Current problem in ticket_ops.py - leads to "no such table" errors
- **Global state for signal handling**: Don't use module-level flags - use Event objects for clean coordination
- **Forgetting to mark sessions as escalated**: DEMO-07 requirement - must update session/ticket status on SIGTERM
- **Using time.sleep() in daemon loops**: Makes shutdown slow - use Event.wait(timeout) for interruptible sleep
- **Mixing async/sync patterns incorrectly**: Agent loop is sync, monitor loop is async - don't try to make agent loop async just for signals

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema initialization | Custom SQL version checking | `CREATE IF NOT EXISTS` + idempotent executescript | SQL DDL is already idempotent, no need for version tables |
| Signal handling coordination | Global boolean flags | `threading.Event` or `asyncio.Event` | Events provide clean coordination and are interruptible |
| Database context management | Manual try/finally blocks | Context manager (`__enter__`/`__exit__`) | Guarantees cleanup even on exceptions |
| Session cleanup on shutdown | Custom signal handler logic | Leverage existing context manager cleanup + explicit escalation | Context managers already handle connection cleanup |

**Key insight:** The codebase already has all the patterns needed - don't invent new approaches. Follow `AuditLogDB` for schema init, follow `MonitorLoop` concepts (adapted for sync) for shutdown.

## Common Pitfalls

### Pitfall 1: Async Signal Handlers in Sync Code
**What goes wrong:** Trying to use `loop.add_signal_handler()` in non-async code
**Why it happens:** MonitorLoop uses async pattern, agent loop is synchronous
**How to avoid:** Use `signal.signal()` for synchronous code, `loop.add_signal_handler()` only in async
**Warning signs:** `RuntimeError: no running event loop` when registering signal handlers

### Pitfall 2: Missing Schema Before First Query
**What goes wrong:** "sqlite3.OperationalError: no such table: tickets" on first query
**Why it happens:** Raw `sqlite3.connect()` doesn't ensure schema exists
**How to avoid:** Use context manager pattern with `_ensure_schema()` in `__enter__`
**Warning signs:** Works after first run, fails on fresh database or after deletion

### Pitfall 3: Not Marking Sessions as Escalated on Shutdown
**What goes wrong:** Session remains in "running" state forever after SIGTERM
**Why it happens:** Signal handler breaks loop but doesn't update session status
**How to avoid:** Track current session in module state, update in signal handler or cleanup
**Warning signs:** DEMO-07 requirement failing, sessions stuck in "running" status

### Pitfall 4: Non-Interruptible Sleep
**What goes wrong:** Agent takes up to 1 second to respond to SIGTERM
**Why it happens:** `time.sleep(1)` blocks and can't be interrupted
**How to avoid:** Use `event.wait(timeout=1.0)` which returns immediately on signal
**Warning signs:** Slow shutdown, need to send multiple SIGTERM signals

### Pitfall 5: Nested Context Manager Deadlock
**What goes wrong:** Opening `TicketOpsDB` context inside `AuditLogDB` context on same db_path
**Why it happens:** SQLite has complex locking behavior with multiple connections
**How to avoid:** Use same connection for related operations, or ensure operations are serialized
**Warning signs:** Database locked errors, timeouts on queries

## Code Examples

### Example 1: TicketOpsDB Context Manager (NEW - modeled on AuditLogDB)

```python
# Location: packages/operator-core/src/operator_core/agent_lab/ticket_ops.py
# Pattern: Schema initialization context manager (from AuditLogDB)

import sqlite3
from pathlib import Path
from typing import Any

class TicketOpsDB:
    """
    Synchronous context manager for ticket operations with schema initialization.

    Ensures tickets table exists before any query. Mirrors AuditLogDB pattern.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "TicketOpsDB":
        """Open connection and ensure schema exists."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        from operator_core.db.schema import SCHEMA_SQL, ACTIONS_SCHEMA_SQL
        self._conn.executescript(SCHEMA_SQL)
        self._conn.executescript(ACTIONS_SCHEMA_SQL)
        self._conn.commit()

    def poll_for_open_ticket(self) -> Ticket | None:
        """Poll for first open ticket."""
        cursor = self._conn.execute(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None
        # ... convert row to Ticket ...

    def update_ticket_resolved(self, ticket_id: int, summary: str) -> None:
        """Mark ticket as resolved."""
        self._conn.execute(
            "UPDATE tickets SET status = 'resolved', resolved_at = ?, diagnosis = ? WHERE id = ?",
            (datetime.now().isoformat(), summary, ticket_id),
        )
        self._conn.commit()

    def update_ticket_escalated(self, ticket_id: int, reason: str) -> None:
        """Mark ticket as escalated."""
        self._conn.execute(
            "UPDATE tickets SET status = 'diagnosed', diagnosis = ? WHERE id = ?",
            (f"ESCALATED: {reason}", ticket_id),
        )
        self._conn.commit()
```

### Example 2: Agent Loop with Graceful Shutdown (MODIFIED)

```python
# Location: packages/operator-core/src/operator_core/agent_lab/loop.py
# Pattern: Synchronous daemon with signal handling (adapted from MonitorLoop)

import signal
import threading
from pathlib import Path

def run_agent_loop(db_path: Path, audit_dir: Path | None = None) -> None:
    """Run agent polling loop. Blocks until Ctrl+C."""
    shutdown = threading.Event()
    current_session: tuple[AuditLogDB, str, int] | None = None  # (db, session_id, ticket_id)

    def handle_shutdown(signum, frame):
        """Handle SIGINT/SIGTERM by marking current session as escalated."""
        sig_name = signal.Signals(signum).name
        print(f"\nReceived {sig_name}, shutting down gracefully...")
        shutdown.set()

        # Mark current session as escalated (DEMO-07)
        if current_session is not None:
            audit_db, session_id, ticket_id = current_session
            try:
                audit_db.complete_session(session_id, "escalated", f"Interrupted by {sig_name}")
                with TicketOpsDB(db_path) as ticket_db:
                    ticket_db.update_ticket_escalated(ticket_id, f"Agent shutdown during processing ({sig_name})")
            except Exception as e:
                print(f"Error during shutdown cleanup: {e}")

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    client = anthropic.Anthropic()
    print(f"Agent loop starting. Database: {db_path}\nPress Ctrl+C to stop.\n")

    while not shutdown.is_set():
        try:
            with TicketOpsDB(db_path) as ticket_db:
                ticket = ticket_db.poll_for_open_ticket()

            if ticket and ticket.id is not None:
                print(f"\n{'='*60}")
                print(f"Processing ticket #{ticket.id}: {ticket.invariant_name}")
                print(f"{'='*60}\n")

                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(ticket.id)
                    current_session = (audit_db, session_id, ticket.id)

                    try:
                        status, summary = process_ticket(
                            client, ticket, audit_db, session_id
                        )
                        audit_db.complete_session(session_id, status, summary)

                        with TicketOpsDB(db_path) as ticket_db:
                            if status == "resolved":
                                ticket_db.update_ticket_resolved(ticket.id, summary)
                            else:
                                ticket_db.update_ticket_escalated(ticket.id, summary)

                        print(f"\n{'='*60}")
                        print(f"Ticket #{ticket.id} -> {status}")
                        print(f"{'='*60}\n")

                    except Exception as e:
                        print(f"\nERROR processing ticket #{ticket.id}: {e}\n")
                        audit_db.complete_session(session_id, "failed", str(e))
                        with TicketOpsDB(db_path) as ticket_db:
                            ticket_db.update_ticket_escalated(ticket.id, f"Error: {str(e)}")
                    finally:
                        current_session = None

            # Interruptible sleep (DEMO-07 - quick shutdown response)
            if shutdown.wait(timeout=1.0):
                break

        except Exception as e:
            print(f"\nERROR in main loop: {e}\n")
            if shutdown.wait(timeout=1.0):
                break

    print("\n\nAgent loop stopped.")
```

### Example 3: Unit Test for Schema Initialization (NEW)

```python
# Location: packages/operator-core/tests/test_agent_database.py
# Pattern: Tempfile database testing (from test_loop_audit.py)

import tempfile
from pathlib import Path
import pytest

from operator_core.agent_lab.ticket_ops import TicketOpsDB

def test_ticket_ops_initializes_schema_on_empty_database():
    """Verify TicketOpsDB creates schema on first connection (TEST-03)."""
    # Create temporary database file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Delete the file to ensure truly empty database
        db_path.unlink()

        # Open connection - should initialize schema automatically
        with TicketOpsDB(db_path) as db:
            # Query should succeed (not raise "no such table" error)
            ticket = db.poll_for_open_ticket()
            assert ticket is None  # Empty database, no tickets

        # Verify schema persists after closing connection
        with TicketOpsDB(db_path) as db:
            ticket = db.poll_for_open_ticket()
            assert ticket is None

    finally:
        db_path.unlink(missing_ok=True)

def test_ticket_ops_handles_existing_schema():
    """Verify TicketOpsDB is idempotent - safe to call on existing database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create schema twice - should not error
        with TicketOpsDB(db_path) as db:
            pass
        with TicketOpsDB(db_path) as db:
            pass

    finally:
        db_path.unlink(missing_ok=True)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw `sqlite3.connect()` in ticket_ops | Context manager with `_ensure_schema()` | Phase 33 (this phase) | Fixes "no such table" errors on clean database |
| No signal handling in agent loop | `signal.signal()` with graceful shutdown | Phase 33 (this phase) | Enables clean demo restarts (DEMO-07) |
| `time.sleep(1)` for polling interval | `event.wait(timeout=1.0)` | Phase 33 (this phase) | Faster shutdown response |
| Implicit session cleanup | Explicit escalation on SIGTERM | Phase 33 (this phase) | Sessions marked correctly in database |

**Deprecated/outdated:**
- Module-level functions in `ticket_ops.py` without schema init: Will be replaced with `TicketOpsDB` context manager
- Agent loop without signal handling: Will be enhanced with SIGTERM/SIGINT handlers

## Open Questions

1. **Should TicketOpsDB reuse AuditLogDB connection?**
   - What we know: Both operate on same db_path (tickets.db)
   - What's unclear: Whether SQLite locking allows nested context managers safely
   - Recommendation: Use separate connections (safer), ensure operations are serialized

2. **Should demo script verify schema before deleting tickets.db?**
   - What we know: Demo deletes tickets.db for clean state (run-demo.sh line 127-132)
   - What's unclear: Whether we should keep db and DELETE FROM instead
   - Recommendation: Keep current deletion approach - simpler, tests schema init

3. **How to test SIGTERM handling in unit tests?**
   - What we know: Test needs to verify session marked as escalated
   - What's unclear: How to send signal in pytest without killing test process
   - Recommendation: Test signal handler function directly, not full process lifecycle

## Sources

### Primary (HIGH confidence)
- `packages/operator-core/src/operator_core/db/audit_log.py` - Schema initialization pattern (lines 24-63)
- `packages/operator-core/src/operator_core/db/schema.py` - SCHEMA_SQL definitions
- `packages/operator-core/src/operator_core/monitor/loop.py` - Signal handling pattern (lines 84-123)
- `packages/operator-core/tests/test_loop_audit.py` - Testing pattern (lines 15-23)
- `packages/operator-core/src/operator_core/agent_lab/ticket_ops.py` - Current problematic implementation (lines 11-26)
- `packages/operator-core/src/operator_core/agent_lab/loop.py` - Current agent loop (lines 96-147)
- `scripts/run-demo.sh` - Demo database cleanup (lines 127-132)
- `demo/tui_integration.py` - Subprocess management (lines 128-157)

### Secondary (MEDIUM confidence)
- Python standard library documentation - signal module behavior
- SQLite documentation - CREATE IF NOT EXISTS semantics

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Direct codebase inspection, patterns clearly established
- Architecture: HIGH - Multiple working examples (AuditLogDB, MonitorLoop, TicketDB)
- Pitfalls: HIGH - Root cause identified from error messages and code inspection

**Research date:** 2026-01-28
**Valid until:** 2026-02-28 (30 days - stable internal codebase patterns)
