# Phase 4: Monitor Loop - Research

**Researched:** 2026-01-24
**Domain:** Python asyncio daemon + SQLite ticket persistence + CLI commands
**Confidence:** HIGH

## Summary

This phase implements a continuous monitoring daemon that checks registered invariants at configurable intervals, creates tickets when violations occur, and manages ticket lifecycle through SQLite persistence. The monitor loop is a long-running asyncio daemon that must handle graceful shutdown, deduplication of violations, and flap detection.

The implementation uses Python's native asyncio for the daemon loop, aiosqlite for non-blocking SQLite operations, and extends the existing Typer CLI with new command groups. The existing `InvariantChecker` and `InvariantViolation` classes from operator-tikv provide the invariant checking foundation.

**Primary recommendation:** Use asyncio with signal handlers for the daemon loop, aiosqlite for async SQLite operations, and Rich tables for CLI output. Keep the ticket database in operator-core (shared infrastructure) while monitor commands integrate with the existing CLI.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | 0.20+ | Async SQLite operations | Official asyncio bridge to sqlite3; non-blocking queries on event loop |
| asyncio | stdlib | Event loop and daemon | Python standard library; well-documented signal handling |
| typer | 0.21+ | CLI commands | Already in use; subcommand groups via add_typer |
| rich | 14.0+ | Table output | Already in use; Table class for CLI output |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| functools | stdlib | Signal handler partial | Passing context to signal callbacks |
| signal | stdlib | SIGINT/SIGTERM | Graceful daemon shutdown |
| json | stdlib | JSON output mode | When --json flag passed to CLI |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiosqlite | SQLAlchemy async | Overkill for simple ticket table; adds ORM complexity |
| SQLite | PostgreSQL | Requires external service; SQLite is embedded and sufficient |
| Rich Table | tabulate | Rich already in deps; better styling options |

**Installation:**
```bash
pip install aiosqlite
# Other deps (typer, rich) already present
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/src/operator_core/
    db/
        __init__.py
        tickets.py          # TicketDB class: SQLite operations
        schema.py           # Schema creation SQL
    monitor/
        __init__.py
        loop.py             # MonitorLoop daemon class
        types.py            # Ticket dataclass, enums
    cli/
        tickets.py          # tickets subcommand group
        monitor.py          # monitor command (daemon)
```

### Pattern 1: Async Context Manager for Database
**What:** Wrap aiosqlite connection in an async context manager class
**When to use:** Any database operation in async code
**Example:**
```python
# Source: https://aiosqlite.omnilib.dev/en/stable/api.html
import aiosqlite
from pathlib import Path

class TicketDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "TicketDB":
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row  # Access by column name
        await self._ensure_schema()
        return self

    async def __aexit__(self, *args) -> None:
        if self._conn:
            await self._conn.close()

    async def _ensure_schema(self) -> None:
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
```

### Pattern 2: Daemon Loop with Signal Handling
**What:** Long-running async loop with graceful shutdown via signals
**When to use:** The `operator monitor` daemon command
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-eventloop.html
import asyncio
import signal
import functools

class MonitorLoop:
    def __init__(self, interval_seconds: float = 30.0):
        self.interval = interval_seconds
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig)
            )

        while not self._shutdown.is_set():
            await self._check_invariants()
            self._log_heartbeat()

            # Wait for interval or shutdown signal
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.interval
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop

    def _handle_signal(self, sig: signal.Signals) -> None:
        print(f"Received {sig.name}, shutting down...")
        self._shutdown.set()
```

### Pattern 3: Ticket Deduplication Key
**What:** Generate consistent key from violation for deduplication
**When to use:** Checking if violation already has an open ticket
**Example:**
```python
# Per CONTEXT.md: same violation = invariant type + store ID
def make_violation_key(violation: InvariantViolation) -> str:
    """Generate deduplication key for a violation."""
    if violation.store_id:
        return f"{violation.invariant_name}:{violation.store_id}"
    return violation.invariant_name
```

### Pattern 4: Typer Subcommand Group
**What:** Create nested CLI commands via add_typer
**When to use:** `operator tickets list`, `operator tickets resolve`
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/subcommands/add-typer/
# cli/tickets.py
import typer

tickets_app = typer.Typer(help="Manage operator tickets")

@tickets_app.command("list")
def list_tickets(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List all tickets."""
    ...

@tickets_app.command("resolve")
def resolve_ticket(ticket_id: int):
    """Manually resolve a ticket."""
    ...

# cli/main.py
from operator_core.cli.tickets import tickets_app
app.add_typer(tickets_app, name="tickets")
```

### Pattern 5: Rich Table with JSON Alternative
**What:** Output table by default, JSON when --json flag set
**When to use:** All ticket list commands
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/tables.html
import json
from rich.console import Console
from rich.table import Table

def print_tickets(tickets: list[Ticket], json_output: bool) -> None:
    if json_output:
        data = [t.to_dict() for t in tickets]
        print(json.dumps(data, indent=2, default=str))
        return

    console = Console()
    table = Table(title="Tickets")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Invariant")
    table.add_column("Store ID")
    table.add_column("Created")

    for t in tickets:
        table.add_row(
            str(t.id),
            t.status,
            t.invariant_name,
            t.store_id or "-",
            t.created_at.isoformat(),
        )

    console.print(table)
```

### Anti-Patterns to Avoid
- **Blocking SQLite calls:** Never use sqlite3 directly in async code; always use aiosqlite
- **Missing signal handlers:** Daemon without SIGTERM handling won't stop gracefully in Docker
- **Polling shutdown flag:** Use asyncio.Event with wait_for timeout, not busy polling
- **Raw asyncio.sleep:** Can't be interrupted; use Event.wait() with timeout instead

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite | Thread pool wrapper | aiosqlite | Handles connection threading, cursor iteration correctly |
| CLI table formatting | Manual string formatting | Rich Table | Column width, alignment, styling handled |
| Signal handling | Manual signal.signal() | loop.add_signal_handler() | Safe interaction with event loop |
| JSON serialization of dataclasses | Manual dict conversion | dataclasses.asdict() | Handles nested dataclasses automatically |
| Status transitions | String manipulation | Enum with validation | Type safety, prevents invalid states |

**Key insight:** The daemon pattern with asyncio requires careful coordination between the event loop, signal handlers, and sleep/wait operations. Using asyncio.Event for shutdown coordination is critical for responsive termination.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with SQLite
**What goes wrong:** Using sqlite3 directly blocks the entire event loop during queries
**Why it happens:** SQLite is synchronous by design; forgetting to use aiosqlite
**How to avoid:** Always use aiosqlite for all database operations; lint for sqlite3 imports
**Warning signs:** Monitor loop heartbeats become irregular; high latency in check cycles

### Pitfall 2: Signal Handler Not Registered in Main Thread
**What goes wrong:** `add_signal_handler` silently fails or raises RuntimeError
**Why it happens:** asyncio signal handlers must be set in main thread
**How to avoid:** Register handlers inside async main(), not in separate threads
**Warning signs:** Ctrl+C doesn't stop daemon; SIGTERM ignored

### Pitfall 3: Zombie Tickets from Unclean Shutdown
**What goes wrong:** Tickets left in inconsistent state when daemon crashes
**Why it happens:** No transaction management; commit not called before shutdown
**How to avoid:** Use SQLite transactions; commit after each ticket operation
**Warning signs:** Tickets stuck in wrong status after restart

### Pitfall 4: Race Condition in Violation Batching
**What goes wrong:** Same violation creates multiple tickets
**Why it happens:** Check for existing ticket and create new ticket not atomic
**How to avoid:** Use SQLite UNIQUE constraint on violation_key + open status; INSERT OR IGNORE
**Warning signs:** Duplicate tickets for same store/invariant

### Pitfall 5: Flap Detection State Loss
**What goes wrong:** Flapping not detected across daemon restarts
**Why it happens:** Flap detection state kept in memory only
**How to avoid:** Store occurrence history in database; query recent occurrences on startup
**Warning signs:** Flapping violations keep creating tickets after restart

### Pitfall 6: Auto-Resolve While Held
**What goes wrong:** Ticket resolves even though operator set hold
**Why it happens:** Auto-resolve logic doesn't check hold flag
**How to avoid:** Always check `held` column before auto-resolving
**Warning signs:** User complaints that held tickets keep closing

## Code Examples

Verified patterns from official sources:

### SQLite Schema for Tickets
```sql
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
```

### Ticket Dataclass with Status Enum
```python
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any

class TicketStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DIAGNOSED = "diagnosed"
    RESOLVED = "resolved"

@dataclass
class Ticket:
    id: int | None
    violation_key: str
    invariant_name: str
    message: str
    severity: str
    first_seen_at: datetime
    last_seen_at: datetime
    status: TicketStatus = TicketStatus.OPEN
    store_id: str | None = None
    held: bool = False
    batch_key: str | None = None
    occurrence_count: int = 1
    resolved_at: datetime | None = None
    diagnosis: str | None = None
    metric_snapshot: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["status"] = self.status.value
        return d
```

### Database Operations with Deduplication
```python
# Source: aiosqlite patterns from https://aiosqlite.omnilib.dev/en/stable/
async def create_or_update_ticket(
    self,
    violation: InvariantViolation,
    metric_snapshot: dict | None = None,
    batch_key: str | None = None,
) -> Ticket:
    """Create new ticket or update existing open ticket for same violation."""
    violation_key = make_violation_key(violation)
    now = datetime.now()

    # Check for existing open ticket
    async with self._conn.execute(
        """
        SELECT * FROM tickets
        WHERE violation_key = ? AND status != 'resolved'
        """,
        (violation_key,)
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        # Update existing ticket
        await self._conn.execute(
            """
            UPDATE tickets SET
                last_seen_at = ?,
                occurrence_count = occurrence_count + 1,
                message = ?
            WHERE id = ?
            """,
            (now.isoformat(), violation.message, row["id"])
        )
        await self._conn.commit()
        return await self.get_ticket(row["id"])

    # Create new ticket
    snapshot_json = json.dumps(metric_snapshot) if metric_snapshot else None
    await self._conn.execute(
        """
        INSERT INTO tickets (
            violation_key, invariant_name, store_id, message, severity,
            first_seen_at, last_seen_at, batch_key, metric_snapshot
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            violation_key, violation.invariant_name, violation.store_id,
            violation.message, violation.severity,
            violation.first_seen.isoformat(), now.isoformat(),
            batch_key, snapshot_json
        )
    )
    await self._conn.commit()
    return await self.get_ticket(self._conn.lastrowid)
```

### Monitor Loop with Heartbeat
```python
async def _check_invariants(self) -> None:
    """Run one check cycle across all registered invariants."""
    stores = await self.subject.get_stores()
    violations: list[InvariantViolation] = []

    # Check store health
    violations.extend(self.checker.check_stores_up(stores))

    # Check metrics for each store
    for store in stores:
        if store.state == "Up":
            metrics = await self.subject.get_store_metrics(store.id)
            if v := self.checker.check_latency(metrics):
                violations.append(v)
            if v := self.checker.check_disk_space(metrics):
                violations.append(v)

    # Create/update tickets for violations
    if violations:
        batch_key = f"batch-{datetime.now().isoformat()}"
        for v in violations:
            await self.db.create_or_update_ticket(v, batch_key=batch_key)

    # Auto-resolve cleared violations
    await self._auto_resolve_cleared(violations)

def _log_heartbeat(self) -> None:
    """Output periodic status message."""
    print(f"Check complete: {self._invariant_count} invariants, "
          f"{self._violation_count} violations")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| sqlite3 in threads | aiosqlite | 2020+ | Non-blocking SQLite in asyncio |
| asyncio.gather() | TaskGroup | Python 3.11 | Safer task management, but gather still fine for simple cases |
| Manual signal handlers | loop.add_signal_handler() | Python 3.6+ | Safe event loop interaction |
| asyncio.get_event_loop() | asyncio.get_running_loop() | Python 3.10 deprecation | Correct loop access in async context |

**Deprecated/outdated:**
- `loop.run_until_complete()`: Use `asyncio.run()` for application entry points
- `asyncio.get_event_loop()` in async code: Use `asyncio.get_running_loop()`

## Open Questions

Things that couldn't be fully resolved:

1. **Exact flap detection thresholds**
   - What we know: CONTEXT.md says "3+ times in N minutes"
   - What's unclear: What should N be? 5 minutes? 10 minutes?
   - Recommendation: Default to 5 minutes (10 check cycles at 30s), make configurable

2. **Metric snapshot storage format**
   - What we know: Should capture metrics at violation time
   - What's unclear: All metrics or just relevant ones?
   - Recommendation: Store full StoreMetrics as JSON; filter can happen at display time

3. **Ticket ID format**
   - What we know: SQLite auto-increment gives integers
   - What's unclear: Should IDs be prefixed (TKT-123) for CLI friendliness?
   - Recommendation: Use integers internally, format with prefix in display layer only

4. **Database file location**
   - What we know: Need persistent storage
   - What's unclear: Where should the .db file live?
   - Recommendation: `~/.operator/tickets.db` for user installs, configurable path for production

## Sources

### Primary (HIGH confidence)
- [Python asyncio Event Loop documentation](https://docs.python.org/3/library/asyncio-eventloop.html) - Signal handling patterns
- [aiosqlite API Reference](https://aiosqlite.omnilib.dev/en/stable/api.html) - Async SQLite patterns
- [Typer Subcommands](https://typer.tiangolo.com/tutorial/subcommands/add-typer/) - CLI structure
- [Rich Table documentation](https://rich.readthedocs.io/en/stable/tables.html) - Table output

### Secondary (MEDIUM confidence)
- [Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/) - Shutdown patterns
- [Trac Database Schema](https://trac.edgewall.org/wiki/TracDev/DatabaseSchema/TicketSystem) - Ticket schema inspiration

### Tertiary (LOW confidence)
- Web search results on flap detection patterns - Need validation in implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries well-documented, aiosqlite is the standard choice
- Architecture: HIGH - Patterns verified against official docs
- Pitfalls: MEDIUM - Based on experience patterns and documentation warnings
- Schema design: MEDIUM - Adapted from Trac patterns, may need refinement

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable technologies)
