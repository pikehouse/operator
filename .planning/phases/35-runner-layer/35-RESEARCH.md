# Phase 35: Runner Layer - Research

**Researched:** 2026-01-29
**Domain:** Python async test harness with Protocol-based subject abstraction
**Confidence:** HIGH

## Summary

This research covers building an async evaluation harness for chaos engineering trials against distributed systems. The harness needs to orchestrate Docker containers, execute chaos injections, capture state snapshots, and persist raw timing data to SQLite for post-hoc analysis.

The standard approach uses Python's `typing.Protocol` for subject abstraction, `asyncio` for orchestration with `loop.run_in_executor()` to bridge synchronous Docker operations, and `aiosqlite` for async database persistence. The project already uses `python-on-whales` (synchronous) for Docker control and `typer` for CLI, so the research focuses on async wrapper patterns to integrate these existing tools into an async harness.

Key findings:
- `typing.Protocol` provides structural typing for subject abstraction without inheritance requirements
- `python-on-whales` is synchronous; wrap calls with `loop.run_in_executor()` for async compatibility
- `aiosqlite` provides async SQLite via connection pooling pattern; avoid write contention with sequential trial execution
- Chaos injection should capture exact timestamps (ISO8601) at each transition for accurate timing analysis

**Primary recommendation:** Use synchronous python-on-whales wrapped in `asyncio.to_thread()` (Python 3.9+) for Docker operations, define EvalSubject as a Protocol with async methods, and persist to separate eval.db using aiosqlite with explicit commits after each trial.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typing.Protocol | stdlib (3.8+) | Subject abstraction via structural typing | Built-in, no runtime overhead, type-checker verified |
| asyncio | stdlib | Async orchestration for trials | Standard Python async runtime |
| aiosqlite | 0.20.0+ | Async SQLite persistence | Already in project dependencies, async bridge to sqlite3 |
| python-on-whales | 0.70.0+ | Docker/Compose control | Already in project, comprehensive Docker CLI wrapper |
| typer | 0.21.0+ | CLI framework | Already in project for operator CLI |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.0.0+ | Data validation for Campaign/Trial models | Already in project; use for schema validation |
| rich | 14.0.0+ | CLI progress/formatting | Already in project; use for trial progress display |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Protocol | ABC (Abstract Base Class) | ABC requires explicit inheritance; Protocol allows structural compatibility for existing classes |
| aiosqlite | encode/databases | databases adds dependency layer; aiosqlite is thinner wrapper, already in deps |
| asyncio.to_thread | loop.run_in_executor | to_thread is simpler API (3.9+); executor gives more control but verbose |

**Installation:**
Already satisfied by existing operator-core dependencies. No new packages required.

## Architecture Patterns

### Recommended Project Structure
```
eval/
├── pyproject.toml           # Separate package
├── src/eval/
│   ├── __init__.py
│   ├── types.py             # EvalSubject Protocol, ChaosType enum, Campaign/Trial models
│   ├── runner/
│   │   ├── __init__.py
│   │   ├── harness.py       # Campaign runner (subject-agnostic)
│   │   └── db.py            # Raw data persistence (aiosqlite)
│   └── cli.py               # Top-level CLI (typer)
└── subjects/
    └── tikv/
        ├── __init__.py
        ├── subject.py       # TiKVEvalSubject (implements Protocol)
        └── chaos.py         # TiKV-specific chaos types
```

### Pattern 1: Protocol-Based Subject Abstraction

**What:** Define EvalSubject as a Protocol with async methods, allowing any class with matching signatures to satisfy the interface without explicit inheritance.

**When to use:** When you need polymorphism without tight coupling, especially for pluggable implementations (multiple subjects: TiKV, RateLimiter, future subjects).

**Example:**
```python
# Source: https://docs.python.org/3/library/typing.html
from typing import Protocol, runtime_checkable

@runtime_checkable
class EvalSubject(Protocol):
    """Protocol for evaluation subjects.

    Subjects must implement async state lifecycle:
    - reset() to clean state
    - wait_healthy() to confirm ready
    - capture_state() for before/after snapshots
    - get_chaos_types() to enumerate available chaos
    """

    async def reset(self) -> None:
        """Reset subject to clean initial state."""
        ...

    async def wait_healthy(self, timeout_sec: float = 30.0) -> bool:
        """Wait for subject to reach healthy state.

        Returns:
            True if healthy within timeout, False otherwise.
        """
        ...

    async def capture_state(self) -> dict[str, Any]:
        """Capture current subject state for comparison.

        Returns:
            JSON-serializable state snapshot.
        """
        ...

    def get_chaos_types(self) -> list[str]:
        """Return list of chaos types this subject supports.

        Returns:
            List of chaos type identifiers (e.g., ['node_kill', 'network_partition']).
        """
        ...

    async def inject_chaos(self, chaos_type: str) -> dict[str, Any]:
        """Inject specified chaos type.

        Args:
            chaos_type: Chaos type identifier from get_chaos_types()

        Returns:
            Chaos metadata (e.g., {'target': 'tikv0', 'signal': 'SIGKILL'}).
        """
        ...
```

**Why @runtime_checkable:** Allows `isinstance(obj, EvalSubject)` checks for subject validation at CLI time, not just static type checking.

### Pattern 2: Async Wrapper for Synchronous Docker Operations

**What:** Use `asyncio.to_thread()` to run synchronous python-on-whales calls in thread pool without blocking event loop.

**When to use:** When integrating synchronous libraries (python-on-whales) into async code without refactoring the library.

**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-eventloop.html
import asyncio
from pathlib import Path
from python_on_whales import DockerClient

class TiKVEvalSubject:
    def __init__(self, compose_file: Path):
        self.compose_file = compose_file
        self.docker = DockerClient(compose_files=[compose_file])

    async def reset(self) -> None:
        """Reset TiKV cluster via docker-compose down/up."""
        # Run blocking docker operations in thread pool
        await asyncio.to_thread(self.docker.compose.down, volumes=True)
        await asyncio.to_thread(self.docker.compose.up, detach=True, wait=True)

    async def wait_healthy(self, timeout_sec: float = 30.0) -> bool:
        """Poll container health checks until healthy."""
        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            # Check health in thread pool
            containers = await asyncio.to_thread(self.docker.compose.ps)
            tikv_containers = [c for c in containers if 'tikv' in c.name.lower()]

            if all(c.state.health == 'healthy' for c in tikv_containers):
                return True

            await asyncio.sleep(1.0)

        return False
```

**Pitfall:** Don't use `loop.run_in_executor()` with `None` for Docker calls - creates unbounded thread pool. Use `asyncio.to_thread()` which uses bounded default executor.

### Pattern 3: Trial Timing Capture

**What:** Capture precise ISO8601 timestamps at each trial transition for post-hoc analysis of timing characteristics.

**When to use:** Chaos engineering harnesses where exact timing of events (chaos injection, detection, resolution) drives analysis.

**Example:**
```python
# Source: Existing operator-core/db/audit_log.py pattern
from datetime import datetime, timezone
from dataclasses import dataclass

@dataclass
class TrialRecord:
    trial_id: int
    campaign_id: int
    started_at: str          # ISO8601
    chaos_injected_at: str   # ISO8601
    ticket_created_at: str | None  # ISO8601, None for baseline trials
    resolved_at: str | None   # ISO8601, None if not resolved
    ended_at: str             # ISO8601
    initial_state: str        # JSON blob
    final_state: str          # JSON blob
    chaos_metadata: str       # JSON blob (target, type, etc.)

async def run_trial(subject: EvalSubject, chaos_type: str) -> TrialRecord:
    """Execute single trial with precise timing."""
    # All timestamps use timezone-aware UTC
    now = lambda: datetime.now(timezone.utc).isoformat()

    started_at = now()

    # Reset and wait for healthy
    await subject.reset()
    await subject.wait_healthy()

    # Capture pre-chaos state
    initial_state = await subject.capture_state()

    # Inject chaos
    chaos_injected_at = now()
    chaos_metadata = await subject.inject_chaos(chaos_type)

    # Wait for ticket creation (poll operator.db)
    ticket_created_at = await wait_for_ticket()

    # Wait for resolution (poll operator.db)
    resolved_at = await wait_for_resolution()

    # Capture post-chaos state
    final_state = await subject.capture_state()

    ended_at = now()

    return TrialRecord(
        started_at=started_at,
        chaos_injected_at=chaos_injected_at,
        ticket_created_at=ticket_created_at,
        resolved_at=resolved_at,
        ended_at=ended_at,
        initial_state=json.dumps(initial_state),
        final_state=json.dumps(final_state),
        chaos_metadata=json.dumps(chaos_metadata),
    )
```

### Pattern 4: Async SQLite Persistence

**What:** Use aiosqlite context managers for async database operations with explicit commits after each trial.

**When to use:** When persisting evaluation results from async code without blocking event loop.

**Example:**
```python
# Source: https://aiosqlite.omnilib.dev/en/stable/
import aiosqlite
from pathlib import Path

class EvalDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def ensure_schema(self) -> None:
        """Create tables if not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_name TEXT NOT NULL,
                    chaos_type TEXT NOT NULL,
                    trial_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    chaos_injected_at TEXT NOT NULL,
                    ticket_created_at TEXT,
                    resolved_at TEXT,
                    ended_at TEXT NOT NULL,
                    initial_state TEXT NOT NULL,
                    final_state TEXT NOT NULL,
                    chaos_metadata TEXT NOT NULL,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
                )
            """)
            await db.commit()

    async def insert_trial(self, trial: TrialRecord) -> int:
        """Insert trial record, return trial_id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO trials (
                    campaign_id, started_at, chaos_injected_at,
                    ticket_created_at, resolved_at, ended_at,
                    initial_state, final_state, chaos_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trial.campaign_id, trial.started_at, trial.chaos_injected_at,
                trial.ticket_created_at, trial.resolved_at, trial.ended_at,
                trial.initial_state, trial.final_state, trial.chaos_metadata,
            ))
            await db.commit()
            return cursor.lastrowid
```

**Critical:** Always `await db.commit()` explicitly. aiosqlite does not auto-commit on context manager exit.

### Pattern 5: Typer CLI Integration

**What:** Define CLI commands using Typer decorators, call async runner functions via `asyncio.run()`.

**When to use:** When building CLI for async harness using existing Typer framework.

**Example:**
```python
# Source: Existing operator-core/cli/agent.py pattern
import typer
import asyncio
from pathlib import Path

eval_app = typer.Typer(help="Evaluation harness")

@eval_app.command("run")
def run_trial(
    subject: str = typer.Option(..., "--subject", help="Subject name (e.g., 'tikv')"),
    chaos: str = typer.Option(..., "--chaos", help="Chaos type (e.g., 'node_kill')"),
    baseline: bool = typer.Option(False, "--baseline", help="Run without agent"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Eval database path"),
) -> None:
    """Run single trial against subject."""
    asyncio.run(async_run_trial(subject, chaos, baseline, db_path))

async def async_run_trial(
    subject_name: str,
    chaos_type: str,
    baseline: bool,
    db_path: Path,
) -> None:
    """Async implementation of trial runner."""
    # Load subject
    subject = load_subject(subject_name)

    # Run trial
    trial = await run_trial(subject, chaos_type)

    # Persist to DB
    db = EvalDB(db_path)
    await db.ensure_schema()
    trial_id = await db.insert_trial(trial)

    typer.echo(f"Trial {trial_id} complete: {trial.ended_at}")
```

### Anti-Patterns to Avoid

- **Mixing async/sync SQLite:** Don't use `sqlite3` directly in async code - blocks event loop. Use `aiosqlite` wrapper.
- **Unbounded thread pools:** Don't use `loop.run_in_executor(None, blocking_fn)` repeatedly - creates unbounded threads. Use `asyncio.to_thread()` which uses default bounded executor.
- **Forgetting aiosqlite commits:** Unlike sqlite3 context managers, `aiosqlite` async context managers don't auto-commit. Must call `await db.commit()` explicitly.
- **Runtime Protocol checks in hot paths:** `isinstance(obj, Protocol)` with `@runtime_checkable` is slow. Use at initialization/validation time, not in tight loops.
- **Timezone-naive timestamps:** Always use `datetime.now(timezone.utc).isoformat()` for cross-platform consistency. Avoid `datetime.now()` without timezone.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite | Custom async queue + sqlite3 | aiosqlite | Handles connection pooling, thread safety, async context managers correctly |
| Thread pool management | manual ThreadPoolExecutor | asyncio.to_thread() | Manages default bounded executor, simpler API, automatic cleanup |
| Docker health checking | Custom curl loops | python-on-whales healthcheck API | Parses Docker healthcheck config, handles retries, normalizes across services |
| Timestamp formatting | strftime + manual timezone | datetime.isoformat() with timezone.utc | ISO8601 compliant, timezone-aware, sortable lexically |
| CLI argument parsing | argparse | typer | Type-safe, auto-generates help, already in project |

**Key insight:** Chaos engineering harnesses have subtle timing and state management complexities. Reusing battle-tested libraries (aiosqlite, asyncio stdlib) prevents data races, deadlocks, and timing inaccuracies that invalidate trial results.

## Common Pitfalls

### Pitfall 1: SQLite Write Contention in Parallel Trials

**What goes wrong:** Running multiple trials in parallel (`asyncio.gather()`) with concurrent writes to SQLite causes "database is locked" errors.

**Why it happens:** SQLite uses database-level write locks. Multiple async tasks with separate connections trying to write simultaneously collide, even with aiosqlite.

**How to avoid:** Execute trials sequentially, not in parallel. Use `for trial in trials:` loop, not `asyncio.gather()`. Sequential execution matches real chaos engineering workflows anyway (one failure at a time).

**Warning signs:**
- `sqlite3.OperationalError: database is locked`
- Intermittent write failures
- Trials succeed but data missing from DB

### Pitfall 2: python-on-whales Blocking Event Loop

**What goes wrong:** Calling `docker.compose.up()` directly in async function blocks event loop for 30+ seconds during container startup, freezing entire application.

**Why it happens:** python-on-whales uses `subprocess.run()` which blocks until Docker command completes. Long-running commands (compose up, pull) block event loop thread.

**How to avoid:** Wrap ALL python-on-whales calls with `await asyncio.to_thread(docker.method, args)`.

**Warning signs:**
- CLI freezes during "docker compose up"
- asyncio tasks don't progress during Docker operations
- Health checks timeout despite containers being healthy

**Example:**
```python
# WRONG - blocks event loop
async def reset(self):
    self.docker.compose.up(detach=True, wait=True)  # 30+ second block!

# CORRECT - runs in thread pool
async def reset(self):
    await asyncio.to_thread(self.docker.compose.up, detach=True, wait=True)
```

### Pitfall 3: Missing aiosqlite Commits

**What goes wrong:** Data inserted during trials doesn't appear in database after script completes. Queries return empty results.

**Why it happens:** aiosqlite async context managers exit cleanly but don't auto-commit. Changes are rolled back on connection close.

**How to avoid:** Explicitly `await db.commit()` before exiting async context manager. Make it the last line before the `async with` closes.

**Warning signs:**
- Inserts succeed (no errors) but data disappears
- Queries work during same connection but not after restart
- `SELECT` returns row count 0 for just-inserted records

**Example:**
```python
# WRONG - no commit, data lost
async with aiosqlite.connect(db_path) as db:
    await db.execute("INSERT INTO trials ...")
    # Context exits, changes rolled back

# CORRECT - explicit commit
async with aiosqlite.connect(db_path) as db:
    await db.execute("INSERT INTO trials ...")
    await db.commit()  # REQUIRED
```

### Pitfall 4: Protocol Without @runtime_checkable

**What goes wrong:** `isinstance(subject, EvalSubject)` raises `TypeError: Protocols cannot be used with isinstance() unless decorated with @runtime_checkable`.

**Why it happens:** Protocols are static-typing-only by default. Runtime checks require explicit opt-in via decorator.

**How to avoid:** Add `@runtime_checkable` decorator to Protocol definition if you need `isinstance()` checks (common for CLI validation).

**Warning signs:**
- TypeError mentioning "Protocols cannot be used with isinstance()"
- Type checker passes but runtime validation fails

**Example:**
```python
# WRONG - runtime check fails
class EvalSubject(Protocol):
    async def reset(self) -> None: ...

if isinstance(obj, EvalSubject):  # TypeError!
    ...

# CORRECT - decorator enables runtime checks
from typing import runtime_checkable

@runtime_checkable
class EvalSubject(Protocol):
    async def reset(self) -> None: ...

if isinstance(obj, EvalSubject):  # Works!
    ...
```

### Pitfall 5: Docker Compose Health Check Misinterpretation

**What goes wrong:** `wait_healthy()` returns True but containers immediately fail when chaos injected because cluster hasn't formed quorum yet.

**Why it happens:** Docker healthchecks only verify single-container health (e.g., "PD API responds"), not distributed system readiness (e.g., "3-node Raft quorum achieved").

**How to avoid:** After `docker.compose.up(wait=True)`, add subject-specific readiness check (e.g., query PD for store count, verify leader election). Don't trust healthcheck alone for distributed systems.

**Warning signs:**
- Trials fail immediately after "healthy" state
- Chaos injection finds no valid targets
- Inconsistent trial results (race condition during cluster formation)

## Code Examples

Verified patterns from official sources:

### Campaign Runner Structure
```python
# Source: Synthesized from asyncio.run pattern and aiosqlite docs
import asyncio
from pathlib import Path
from datetime import datetime, timezone

async def run_campaign(
    subject: EvalSubject,
    chaos_type: str,
    trial_count: int,
    db_path: Path,
) -> int:
    """Run campaign of N trials sequentially.

    Returns:
        campaign_id for later analysis
    """
    # Initialize DB
    db = EvalDB(db_path)
    await db.ensure_schema()

    # Create campaign record
    campaign_id = await db.insert_campaign(
        subject_name=subject.__class__.__name__,
        chaos_type=chaos_type,
        trial_count=trial_count,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # Run trials sequentially (avoid SQLite write contention)
    for trial_num in range(trial_count):
        print(f"Trial {trial_num + 1}/{trial_count}...")

        trial = await run_trial(subject, chaos_type, campaign_id)
        await db.insert_trial(trial)

        print(f"  Completed at {trial.ended_at}")

    return campaign_id
```

### TiKV Subject Implementation
```python
# Source: Adapted from demo/tikv_chaos.py with async wrappers
import asyncio
import json
from pathlib import Path
from typing import Any
from python_on_whales import DockerClient

class TiKVEvalSubject:
    """TiKV evaluation subject implementing EvalSubject protocol."""

    def __init__(self, compose_file: Path):
        self.compose_file = compose_file
        self.docker = DockerClient(compose_files=[compose_file])

    async def reset(self) -> None:
        """Reset cluster via compose down + up with volume wipe."""
        # Down with volume cleanup
        await asyncio.to_thread(
            self.docker.compose.down,
            volumes=True,
            remove_orphans=True,
        )

        # Up and wait for healthchecks
        await asyncio.to_thread(
            self.docker.compose.up,
            detach=True,
            wait=True,
        )

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for all TiKV + PD containers healthy."""
        start = asyncio.get_running_loop().time()

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            # Get container statuses (in thread pool)
            containers = await asyncio.to_thread(self.docker.compose.ps)

            # Filter to PD + TiKV containers
            cluster_containers = [
                c for c in containers
                if ('pd' in c.name.lower() or 'tikv' in c.name.lower())
            ]

            # Check if all healthy
            if all(c.state.health == 'healthy' for c in cluster_containers):
                # Additional check: query PD for store count
                # (verifies cluster formation, not just container health)
                if await self._verify_cluster_ready():
                    return True

            await asyncio.sleep(2.0)

        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture PD cluster state via API."""
        # Query PD API for stores, regions, leader
        # (run HTTP request in thread pool if using synchronous httpx)
        return {
            "store_count": 3,  # TODO: actual PD API query
            "region_count": 100,
            "leader": "pd0",
        }

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types."""
        return ["node_kill"]

    async def inject_chaos(self, chaos_type: str) -> dict[str, Any]:
        """Inject chaos, return metadata."""
        if chaos_type == "node_kill":
            return await self._kill_random_tikv()
        raise ValueError(f"Unknown chaos type: {chaos_type}")

    async def _kill_random_tikv(self) -> dict[str, Any]:
        """Kill random TiKV container with SIGKILL."""
        import random

        # Get running TiKV containers
        containers = await asyncio.to_thread(self.docker.compose.ps)
        tikv_containers = [
            c for c in containers
            if 'tikv' in c.name.lower() and c.state.running
        ]

        if not tikv_containers:
            raise RuntimeError("No running TiKV containers to kill")

        # Random selection
        target = random.choice(tikv_containers)

        # Kill with SIGKILL
        await asyncio.to_thread(self.docker.kill, target.name)

        return {
            "chaos_type": "node_kill",
            "target_container": target.name,
            "signal": "SIGKILL",
        }

    async def _verify_cluster_ready(self) -> bool:
        """Verify cluster has formed (not just containers healthy)."""
        # TODO: Query PD /pd/api/v1/stores endpoint
        # Verify store count == 3 and all stores "Up"
        return True
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ABC for interfaces | Protocol for structural typing | Python 3.8 (2019) | No longer need explicit inheritance for polymorphism |
| loop.run_in_executor() | asyncio.to_thread() | Python 3.9 (2020) | Simpler API, automatic bounded executor |
| Manual timezone handling | datetime.timezone.utc | Python 3.2+ (2011) | Timezone-aware timestamps by default |
| sqlite3 in async | aiosqlite wrapper | ~2018 | Non-blocking DB access in async code |

**Deprecated/outdated:**
- `@asyncio.coroutine` decorator: Use `async def` instead (Python 3.5+)
- `asyncio.get_event_loop()`: Use `asyncio.get_running_loop()` or `asyncio.run()` (Python 3.7+)
- `loop.create_task()`: Use `asyncio.create_task()` (Python 3.7+)

## Open Questions

Things that couldn't be fully resolved:

1. **Agent command extraction timing**
   - What we know: RUN-04 requires extracting commands from agent session for analysis
   - What's unclear: Should extraction happen during trial (polling operator.db live) or post-hoc (query agent_log_entries after trial)? Live polling is more accurate but complex; post-hoc is simpler but might miss timing if agent modifies tickets asynchronously.
   - Recommendation: Start with post-hoc extraction (simpler). Query operator.db agent_log_entries table after trial completes, filter to session_id, extract tool_call entries where tool_name='shell'. Add live polling in later phase if timing analysis requires it.

2. **Baseline trial mechanics**
   - What we know: RUN-05 requires baseline trials without agent for self-healing comparison
   - What's unclear: Should baseline trials still create tickets in operator.db (to verify monitor works) or bypass monitoring entirely? If tickets are created, how to prevent agent from picking them up?
   - Recommendation: Create tickets normally but don't start agent loop during baseline trials. This verifies monitor + ticket creation but ensures no agent intervention. Store baseline flag in trials table to distinguish in analysis.

3. **State capture granularity**
   - What we know: SUBJ-03 captures initial_state and final_state as JSON blobs
   - What's unclear: What level of detail is useful? Full PD API dump (100+ regions) or summary (store count, leader, health)? Too much data bloats database; too little limits analysis.
   - Recommendation: Start with summary level (store count, region count, leader, health status). Add detailed capture as optional flag (--verbose-state) if analysis requires it. Detailed state can always be queried post-hoc from PD API via timestamps.

## Sources

### Primary (HIGH confidence)
- [Python typing.Protocol documentation](https://docs.python.org/3/library/typing.html) - Protocol class definition, @runtime_checkable, structural typing patterns
- [aiosqlite official documentation](https://aiosqlite.omnilib.dev/en/stable/) - Async context managers, commit patterns, connection management
- [Python asyncio event loop documentation](https://docs.python.org/3/library/asyncio-eventloop.html) - run_in_executor, to_thread, subprocess patterns
- [Python asyncio subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html) - create_subprocess_exec vs create_subprocess_shell, process communication
- [python-on-whales documentation](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) - Docker client thread-safety, compose operations

### Secondary (MEDIUM confidence)
- [Docker container kill documentation](https://docs.docker.com/reference/cli/docker/container/kill/) - SIGKILL vs SIGTERM semantics
- [PEP 544 - Protocols: Structural subtyping](https://peps.python.org/pep-0544/) - Design rationale for Protocol
- [mypy protocols documentation](https://mypy.readthedocs.io/en/stable/protocols.html) - Type checker perspective on protocols

### Tertiary (LOW confidence)
- WebSearch: "chaos engineering test harness patterns Python 2026" - General patterns, not specific to this architecture
- WebSearch: "Python testing patterns state capture before after snapshot 2026" - Snapshot testing libraries (not directly applicable but informative)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified from official docs, already in project dependencies except none needed
- Architecture: HIGH - Patterns verified from official Python docs and existing codebase (audit_log.py, agent.py)
- Pitfalls: MEDIUM - Based on common asyncio/SQLite issues documented in community resources; should validate during implementation

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - stable Python stdlib, mature libraries)
