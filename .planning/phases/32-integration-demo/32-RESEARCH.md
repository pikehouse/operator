# Phase 32: Integration & Demo - Research

**Researched:** 2026-01-28
**Domain:** Docker Compose integration, CLI tooling, TUI streaming
**Confidence:** HIGH

## Summary

This phase integrates the existing agent (Phase 30/31) with the existing demo infrastructure (TUI, chaos injection) via Docker Compose. All core components exist - the research focuses on how to connect them. The codebase has well-established patterns for Docker Compose networking, TUI subprocess streaming, and CLI commands that should be followed.

The primary challenge is creating a new Docker Compose file for the agent container that joins the subject's network, and modifying the TUI demo to stream the agent_lab loop's output (instead of the old AgentRunner).

**Primary recommendation:** Follow existing patterns exactly - create `docker/agent/docker-compose.yml` that references external network, add `operator audit` CLI command group, and route agent_lab subprocess output through existing SubprocessManager/OutputBuffer infrastructure.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-on-whales | existing | Docker Compose operations | Already used in demo/tikv_chaos.py |
| typer | existing | CLI commands | All CLI in operator_core.cli uses it |
| Rich | existing | TUI panels and formatting | All TUI uses Rich layouts |
| sqlite3 | stdlib | Audit log queries | Used by AuditLogDB already |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| SubprocessManager | existing | Spawn and capture agent output | For streaming agent to TUI |
| OutputBuffer | existing | Ring buffer for subprocess output | For agent panel display |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-on-whales | docker CLI directly | python-on-whales already established in codebase |
| New TUI streaming | Print to stdout | Existing subprocess streaming infrastructure handles this |

**Installation:**
No new packages needed - all infrastructure exists.

## Architecture Patterns

### Recommended Project Structure
```
docker/
  agent/
    docker-compose.yml  # NEW - agent container compose
    Dockerfile          # EXISTS - from Phase 30
subjects/
  tikv/
    docker-compose.yaml # EXISTS - TiKV cluster
packages/
  operator-core/
    src/operator_core/
      cli/
        audit.py        # NEW - audit review CLI
        main.py         # UPDATE - add audit_app
      tui/
        subprocess.py   # EXISTS - SubprocessManager
demo/
  tui_integration.py    # UPDATE - switch to agent_lab process
```

### Pattern 1: External Network Reference (Docker Compose)
**What:** Agent compose file references the subject's network as external
**When to use:** When agent needs to communicate with services in another compose project
**Example:**
```yaml
# Source: docker/agent/docker-compose.yml (NEW)
# Based on pattern from subjects/tikv/docker-compose.yaml

networks:
  tikv_default:
    external: true

services:
  agent:
    build:
      context: ../..
      dockerfile: docker/agent/Dockerfile
    networks:
      - tikv_default
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # For docker commands
      - ~/.operator:/root/.operator  # For tickets.db
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PD_ENDPOINT=http://pd0:2379
      - PROMETHEUS_URL=http://prometheus:9090
```

### Pattern 2: CLI Command Group (Typer)
**What:** Add `audit` command group to existing CLI structure
**When to use:** New CLI functionality
**Example:**
```python
# Source: operator_core/cli/main.py pattern
# audit_app follows tickets_app, actions_app pattern

audit_app = typer.Typer(help="Review agent audit logs")

@audit_app.command("list")
def list_sessions(
    limit: int = typer.Option(10, "--limit", "-n"),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db"),
) -> None:
    """List recent agent sessions."""
    pass

@audit_app.command("show")
def show_session(
    session_id: str = typer.Argument(...),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db"),
) -> None:
    """Show full conversation for a session."""
    pass
```

### Pattern 3: TUI Subprocess Streaming
**What:** Stream agent_lab loop output to TUI agent panel
**When to use:** Demo needs to show agent activity
**Example:**
```python
# Source: demo/tui_integration.py lines 145-163
# Change from "agent start" to "agent_lab run"

agent_proc = await self._subprocess_mgr.spawn(
    "agent",
    [
        "-u",  # CRITICAL: Unbuffered for live display
        "-m",
        "operator_core.cli.main",
        "agent_lab",  # NEW command
        "run",
        "--subject",
        self.subject_name,
    ],
    buffer_size=50,
    env={
        "OPERATOR_SAFETY_MODE": "execute",
    },
)
```

### Anti-Patterns to Avoid
- **Duplicating Dockerfile:** Agent Dockerfile exists at docker/agent/Dockerfile (Phase 30). Don't create a new one.
- **Modifying subject compose:** Keep TiKV compose untouched - agent compose is separate.
- **Async in audit CLI:** Keep audit review CLI synchronous (sqlite3, not aiosqlite) - simpler and fine for CLI.
- **Custom output formatting:** Use Rich console formatting consistently with existing TUI.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docker network discovery | Manual docker inspect | python-on-whales network reference | Already handles external networks |
| Subprocess output capture | Custom readline loop | SubprocessManager from tui/subprocess.py | Handles buffering, shutdown, SIGTERM |
| CLI argument parsing | argparse | typer (existing pattern) | Consistent with all other CLI |
| Session list formatting | Manual string building | Rich Table | Consistent with tickets list |
| Conversation display | Plain print | Rich Panel/Console | Consistent with TUI styling |

**Key insight:** Every infrastructure component needed exists - the task is wiring them together correctly.

## Common Pitfalls

### Pitfall 1: Network Name Mismatch
**What goes wrong:** Agent can't reach TiKV services
**Why it happens:** Docker Compose generates network names with project prefix (e.g., `tikv_default` not just `default`)
**How to avoid:** Use `docker network ls` to verify actual network name, reference it exactly in agent compose
**Warning signs:** Connection refused errors when agent tries to reach pd0:2379

### Pitfall 2: Docker Socket Permissions
**What goes wrong:** Agent can't execute `docker restart` commands
**Why it happens:** Container user doesn't have access to /var/run/docker.sock
**How to avoid:** Either run as root or ensure docker group membership
**Warning signs:** "permission denied" in shell tool output

### Pitfall 3: Agent Output Not Streaming
**What goes wrong:** TUI agent panel stays empty or updates in batches
**Why it happens:** Missing `-u` flag (PYTHONUNBUFFERED) when spawning subprocess
**How to avoid:** Always use `-u` flag in subprocess spawn (already done in existing code)
**Warning signs:** Output appears all at once when session ends

### Pitfall 4: Database Path Mismatch
**What goes wrong:** Agent creates tickets but CLI can't find them
**Why it happens:** Different db_path between monitor, agent, and CLI
**How to avoid:** Mount same ~/.operator directory, use DEFAULT_DB_PATH constant
**Warning signs:** "Ticket not found" when ticket exists

### Pitfall 5: Agent Runs in Wrong Mode
**What goes wrong:** Agent observes but doesn't execute fixes
**Why it happens:** Missing OPERATOR_SAFETY_MODE=execute environment variable
**How to avoid:** Explicitly set in docker-compose.yml and TUI subprocess spawn
**Warning signs:** Agent diagnoses but prints "(observe-only mode - no actions)"

## Code Examples

Verified patterns from the existing codebase:

### Docker Compose External Network
```yaml
# Source: Derived from subjects/tikv/docker-compose.yaml network pattern
# Agent compose needs to join TiKV's network

version: '3.8'

networks:
  tikv_default:
    external: true  # Network created by tikv compose

services:
  agent:
    build:
      context: ../..
      dockerfile: docker/agent/Dockerfile
    container_name: operator-agent
    networks:
      - tikv_default
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - operator-data:/root/.operator
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PD_ENDPOINT=http://pd0:2379
      - PROMETHEUS_URL=http://prometheus:9090
      - OPERATOR_SAFETY_MODE=execute
    depends_on: []  # TiKV started separately
    command: >
      python -m operator_core.agent_lab.loop
      --db /root/.operator/tickets.db

volumes:
  operator-data:
```

### CLI Audit List Command
```python
# Source: Pattern from operator_core/cli/tickets.py

from rich.console import Console
from rich.table import Table

@audit_app.command("list")
def list_sessions(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of sessions to show"),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to database"),
) -> None:
    """List recent agent sessions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT session_id, ticket_id, status, started_at, ended_at, outcome_summary
        FROM agent_sessions
        ORDER BY started_at DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    console = Console()
    table = Table(title="Agent Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Ticket", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Started", style="dim")
    table.add_column("Summary")

    for row in rows:
        status_style = "green" if row["status"] == "completed" else "red"
        table.add_row(
            row["session_id"],
            str(row["ticket_id"]) if row["ticket_id"] else "-",
            f"[{status_style}]{row['status']}[/{status_style}]",
            row["started_at"][:19],  # Truncate to seconds
            (row["outcome_summary"] or "")[:50] + "..." if row["outcome_summary"] and len(row["outcome_summary"]) > 50 else row["outcome_summary"] or "",
        )

    console.print(table)
```

### CLI Audit Show Command
```python
# Source: Pattern from AuditLogDB.get_session_entries()

@audit_app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="Session ID to display"),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to database"),
) -> None:
    """Show full conversation for a session."""
    with AuditLogDB(db_path) as audit_db:
        entries = audit_db.get_session_entries(session_id)

    if not entries:
        print(f"Session {session_id} not found")
        raise typer.Exit(1)

    console = Console()

    for entry in entries:
        timestamp = entry["timestamp"][:19]
        entry_type = entry["entry_type"]
        content = entry["content"]

        if entry_type == "reasoning":
            console.print(f"[dim]{timestamp}[/dim] [bold cyan]Claude:[/bold cyan]")
            console.print(f"  {content}\n")
        elif entry_type == "tool_call":
            tool_name = entry["tool_name"]
            console.print(f"[dim]{timestamp}[/dim] [bold yellow]Tool Call:[/bold yellow] {tool_name}")
            console.print(f"  {content}\n")
        elif entry_type == "tool_result":
            exit_code = entry["exit_code"]
            style = "green" if exit_code == 0 else "red"
            console.print(f"[dim]{timestamp}[/dim] [bold {style}]Result (exit {exit_code}):[/bold {style}]")
            console.print(f"  {content}\n")
```

### TUI Demo with Agent Lab
```python
# Source: demo/tui_integration.py lines 128-163, modified for agent_lab

# In TUIDemoController.run(), change agent subprocess spawn:
agent_proc = await self._subprocess_mgr.spawn(
    "agent",
    [
        "-u",  # Unbuffered output (critical for live display)
        "-m",
        "operator_core.agent_lab.loop",  # Direct module, not CLI
    ],
    buffer_size=100,  # Larger buffer for agent reasoning
    env={
        "OPERATOR_SAFETY_MODE": "execute",
        "OPERATOR_DB_PATH": str(Path.home() / ".operator" / "tickets.db"),
    },
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| AgentRunner (Phase 5) | agent_lab loop (Phase 31) | Phase 31 | Use tool_runner pattern, Haiku summaries |
| Observe-only diagnosis | Execute mode with safety | Phase 23 | Agent can actually fix issues now |
| Single compose file | Separate agent compose | This phase | Cleaner separation of concerns |

**Deprecated/outdated:**
- `operator agent start`: The old AgentRunner from Phase 5 that used structured output for diagnosis. Replaced by agent_lab loop with tool_runner.
- In-process agent: Demo previously ran agent in subprocess via CLI. Same pattern continues but with new agent_lab module.

## Open Questions

Things that couldn't be fully resolved:

1. **Exact network name for TiKV compose**
   - What we know: Docker Compose prefixes network with project name
   - What's unclear: Whether it's `tikv_default` or uses directory name
   - Recommendation: Run `docker network ls` after starting TiKV, use actual name

2. **Agent container restart policy**
   - What we know: Demo expects agent to run continuously
   - What's unclear: What happens if agent crashes during demo
   - Recommendation: Use `restart: on-failure` for demo robustness

3. **Volume for shared database**
   - What we know: Monitor and agent need same tickets.db
   - What's unclear: Best volume strategy for demo (named volume vs host mount)
   - Recommendation: Use named volume `operator-data` for isolation, or bind mount `~/.operator` for debugging

## Sources

### Primary (HIGH confidence)
- `/Users/jrtipton/x/operator/docker/agent/Dockerfile` - Agent container definition
- `/Users/jrtipton/x/operator/subjects/tikv/docker-compose.yaml` - TiKV cluster compose
- `/Users/jrtipton/x/operator/demo/tui_integration.py` - TUI demo controller
- `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/agent_lab/loop.py` - Agent loop implementation
- `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/db/audit_log.py` - Audit log database
- `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/subprocess.py` - SubprocessManager

### Secondary (MEDIUM confidence)
- `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/cli/main.py` - CLI structure pattern
- `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/cli/tickets.py` - CLI command pattern
- `/Users/jrtipton/x/operator/demo/tikv_chaos.py` - python-on-whales usage

### Tertiary (LOW confidence)
- Docker Compose external network documentation (verified against existing patterns)

## Metadata

**Confidence breakdown:**
- Docker Compose setup: HIGH - patterns exist in codebase, just need to apply
- CLI audit tooling: HIGH - follows established typer/Rich patterns
- TUI streaming: HIGH - exact infrastructure exists (SubprocessManager)
- Agent integration: HIGH - agent_lab loop exists and works

**Research date:** 2026-01-28
**Valid until:** Indefinite - this is integration of stable existing components
