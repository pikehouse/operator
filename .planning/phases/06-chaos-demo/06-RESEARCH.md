# Phase 6: Chaos Demo - Research

**Researched:** 2026-01-24
**Domain:** CLI Demo Scripting, Docker Fault Injection, Terminal UX
**Confidence:** HIGH

## Summary

This phase creates an end-to-end demo command (`operator demo chaos`) that showcases the AI diagnosis capability by injecting a fault into a TiKV cluster and observing the operator detect, diagnose, and explain the issue. The demo orchestrates existing components (LocalDeployment, MonitorLoop, AgentRunner) with Rich-based terminal output for a polished showcase experience.

The primary technologies are already in use in the codebase: Typer for CLI, Rich for terminal formatting, python-on-whales for Docker control. The demo is essentially glue code that sequences these existing capabilities with user-friendly output and interactive pacing via press-enter prompts.

**Primary recommendation:** Build the demo as a single async function that sequences: cluster health check, YCSB load start, random TiKV kill, live detection countdown, diagnosis display, and cleanup. Use Rich Console for all output with colored status messages and panels for diagnosis display.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rich | >=14.0.0 | Terminal formatting, colors, panels, status spinners | Already used in project for tables/progress |
| typer | >=0.21.0 | CLI command structure | Already the project's CLI framework |
| python-on-whales | >=0.70.0 | Docker container control (kill, stop, ps) | Already used in LocalDeployment |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio | stdlib | Async orchestration | Coordinate monitor/agent with Docker ops |
| random | stdlib | Random TiKV selection | Pick which store to kill |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Rich status | Plain print | Less polished; Rich already in deps |
| typer.prompt | input() | typer.prompt integrates better with Typer ecosystem |
| python-on-whales | subprocess docker | python-on-whales already in use, type-safe API |

**Installation:**
No new dependencies required. All libraries already in operator-core dependencies.

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/src/operator_core/
├── cli/
│   ├── demo.py          # NEW: demo subcommand group
│   └── main.py          # Add demo_app to main CLI
└── demo/
    └── chaos.py         # NEW: Chaos demo orchestration logic
```

### Pattern 1: Demo Orchestrator Class
**What:** A class that encapsulates the demo lifecycle with clear stages
**When to use:** Complex multi-step demos with cleanup requirements
**Example:**
```python
# Source: Project patterns + Rich docs
from dataclasses import dataclass
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

@dataclass
class ChaosDemo:
    """Orchestrates the chaos demo lifecycle."""

    console: Console
    subject: str = "tikv"
    detection_timeout: float = 30.0

    async def run(self) -> None:
        """Execute the full demo sequence."""
        try:
            await self._ensure_cluster_healthy()
            self._prompt("Press Enter to start YCSB load...")
            await self._start_ycsb_load()
            self._prompt("Press Enter to inject fault...")
            store_id = await self._inject_fault()
            await self._wait_for_detection(store_id)
            self._prompt("Press Enter to run AI diagnosis...")
            diagnosis = await self._run_diagnosis()
            self._display_diagnosis(diagnosis)
        finally:
            await self._cleanup()

    def _prompt(self, message: str) -> None:
        """Wait for user to press Enter."""
        self.console.input(f"\n[yellow]{message}[/yellow] ")
```

### Pattern 2: Live Detection Countdown
**What:** Use Rich's Live display to show real-time detection progress
**When to use:** Waiting for async event with user feedback
**Example:**
```python
# Source: Rich docs - Live display
from rich.live import Live
from rich.text import Text
import asyncio

async def wait_for_detection(
    self,
    timeout: float = 30.0,
    poll_interval: float = 2.0,
) -> bool:
    """Wait for violation detection with live countdown."""
    start = asyncio.get_event_loop().time()

    with Live(Text(""), console=self.console, refresh_per_second=1) as live:
        while True:
            elapsed = asyncio.get_event_loop().time() - start

            # Update display
            live.update(
                Text(f"Waiting for detection... {elapsed:.0f}s", style="cyan")
            )

            # Check for detection
            if await self._check_detection():
                live.update(Text("Detected!", style="bold green"))
                return True

            # Timeout check
            if elapsed >= timeout:
                live.update(Text(f"Timeout ({timeout}s)", style="yellow"))
                return False

            await asyncio.sleep(poll_interval)
```

### Pattern 3: Staged Output with Rules
**What:** Use console.rule() to clearly separate demo stages
**When to use:** Multi-stage demos that benefit from visual separation
**Example:**
```python
# Source: Rich docs - Console API
def _stage_banner(self, title: str, style: str = "bold blue") -> None:
    """Display a stage separator."""
    self.console.print()
    self.console.rule(f"[{style}]{title}[/{style}]")
    self.console.print()
```

### Pattern 4: Docker Container Kill
**What:** Use python-on-whales to hard-kill a container
**When to use:** Simulating sudden node failure
**Example:**
```python
# Source: python-on-whales docs
from python_on_whales import DockerClient

def kill_container(self, container_name: str) -> None:
    """Kill a container with SIGKILL (immediate, no cleanup)."""
    docker = DockerClient()
    docker.kill(container_name)  # SIGKILL by default
```

### Anti-Patterns to Avoid
- **Blocking the event loop:** Don't use time.sleep() in async code; use asyncio.sleep()
- **Hardcoded container names:** Select from actual running containers, don't assume tikv0/1/2
- **No cleanup on error:** Always use try/finally or context managers for cleanup
- **Mixing Rich and print:** Use console.print() consistently for output

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Terminal colors | ANSI escape codes | Rich markup `[green]text[/green]` | Rich handles terminal compatibility |
| Spinners/progress | Manual frame animation | `console.status()` | Built-in spinner library |
| Container control | subprocess + docker CLI | python-on-whales | Type-safe, already in use |
| Interactive prompts | input() | typer.prompt() or console.input() | Consistent with CLI framework |
| Markdown rendering | Manual formatting | `rich.markdown.Markdown` | Already used in tickets show |

**Key insight:** This demo is orchestration, not new functionality. Every component exists; the challenge is sequencing them elegantly.

## Common Pitfalls

### Pitfall 1: Container Name vs Service Name Confusion
**What goes wrong:** docker-compose service names (tikv0) differ from container names in some setups
**Why it happens:** Compose prefixes project name to container names
**How to avoid:** Use `docker.compose.ps()` to list actual container names, or use service-level commands
**Warning signs:** "No such container" errors when trying to kill

### Pitfall 2: Race Condition in Detection
**What goes wrong:** Demo continues before monitor has actually detected the fault
**Why it happens:** Monitor runs on interval; fault might occur just after a check
**How to avoid:** Poll for ticket creation AND invariant violation, not just elapsed time
**Warning signs:** Demo proceeds but no ticket exists

### Pitfall 3: YCSB Container Not Started
**What goes wrong:** YCSB is in "load" profile and doesn't auto-start
**Why it happens:** Docker Compose profiles require explicit activation
**How to avoid:** Start YCSB explicitly with `docker compose --profile load up ycsb -d`
**Warning signs:** No load stats to show, cluster appears idle

### Pitfall 4: Cleanup Failure Leaves Cluster Broken
**What goes wrong:** Demo errors out, killed container stays down
**Why it happens:** Exception before cleanup code runs
**How to avoid:** Use try/finally pattern; restart killed container in finally block
**Warning signs:** Subsequent runs fail because cluster is unhealthy

### Pitfall 5: Monitor/Agent Signal Handler Conflicts
**What goes wrong:** Starting monitor loop in demo interferes with demo's own signal handling
**Why it happens:** MonitorLoop/AgentRunner register SIGINT handlers
**How to avoid:** Run monitor as one-shot check, not continuous loop; or use subprocess
**Warning signs:** Ctrl+C doesn't cleanly exit demo

## Code Examples

Verified patterns from official sources:

### Rich Panel for Diagnosis Display
```python
# Source: Rich docs + existing tickets.py pattern
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

def display_diagnosis(console: Console, diagnosis_md: str) -> None:
    """Display AI diagnosis in a styled panel."""
    console.print()
    console.print(Panel(
        Markdown(diagnosis_md),
        title="[bold green]AI Diagnosis[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))
```

### Random TiKV Store Selection
```python
# Source: Project patterns
import random
from python_on_whales import DockerClient

def select_random_tikv(compose_file: Path) -> str:
    """Select a random running TiKV container."""
    docker = DockerClient(compose_files=[compose_file])
    containers = docker.compose.ps()

    tikv_containers = [
        c for c in containers
        if c.name.startswith("tikv") and c.state.running
    ]

    if not tikv_containers:
        raise RuntimeError("No running TiKV containers found")

    return random.choice(tikv_containers).name
```

### YCSB Stats Parsing
```python
# Source: go-ycsb output format
import re

def parse_ycsb_stats(output: str) -> dict[str, str]:
    """Parse YCSB output into key stats.

    Example output line:
    Run finished, takes 11.7s
    INSERT - Takes(s): 11.7, Count: 10000, OPS: 855.2, Avg(us): 18690
    """
    stats = {}

    # Extract OPS
    ops_match = re.search(r'OPS:\s*([\d.]+)', output)
    if ops_match:
        stats['ops'] = f"{float(ops_match.group(1)):.0f} ops/sec"

    # Extract latency
    avg_match = re.search(r'Avg\(us\):\s*(\d+)', output)
    if avg_match:
        avg_us = int(avg_match.group(1))
        stats['avg_latency'] = f"{avg_us / 1000:.1f}ms"

    return stats
```

### Detection Verification
```python
# Source: Project patterns - combining invariant check + ticket check
async def check_detection(
    self,
    subject: TiKVSubject,
    db: TicketDB,
    target_store_id: str,
) -> bool:
    """Check if fault has been detected.

    Returns True when BOTH:
    1. Invariant shows store is down
    2. Ticket exists for the violation
    """
    # Check invariant
    stores = await subject.get_stores()
    target_down = any(
        s.id == target_store_id and s.state != "Up"
        for s in stores
    )

    if not target_down:
        return False

    # Check for ticket
    tickets = await db.list_tickets(status=TicketStatus.OPEN)
    has_ticket = any(
        t.store_id == target_store_id and t.invariant_name == "store_down"
        for t in tickets
    )

    return has_ticket
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bash demo scripts | Python CLI with Rich | Project inception | Better error handling, consistent styling |
| docker CLI subprocess | python-on-whales | Phase 3 | Type safety, cleaner API |
| Plain print statements | Rich console markup | Phase 3 | Professional terminal output |

**Deprecated/outdated:**
- Shell script demos: verify-phase5.sh works but lacks error handling sophistication
- Manual ANSI codes: Rich handles all terminal formatting

## Open Questions

Things that couldn't be fully resolved:

1. **YCSB Container Output Capture**
   - What we know: YCSB runs in container, outputs stats to stdout
   - What's unclear: Best way to capture output while container runs (docker logs vs attach)
   - Recommendation: Use `docker.compose.logs(services=["ycsb"], tail=20)` after short run

2. **Store ID to Container Name Mapping**
   - What we know: PD reports store IDs (e.g., "1"), containers are named tikv0/1/2
   - What's unclear: Exact mapping mechanism (may need to query PD for store address)
   - Recommendation: Map via store address which contains container hostname

3. **Monitor Loop Integration**
   - What we know: MonitorLoop is designed as long-running daemon
   - What's unclear: Whether to run as subprocess or adapt for single-shot use
   - Recommendation: Run monitor check directly (call _check_cycle) without full loop

## Sources

### Primary (HIGH confidence)
- Rich documentation (rich.readthedocs.io) - Console, Panel, Live, Status APIs
- python-on-whales documentation - Container kill/stop, compose operations
- Typer documentation - Prompt and confirm functions
- Existing codebase (packages/operator-core) - Patterns from deploy.py, tickets.py

### Secondary (MEDIUM confidence)
- go-ycsb GitHub - Output format and statistics
- TiKV performance docs - Expected benchmark values

### Tertiary (LOW confidence)
- WebSearch results for chaos engineering best practices - General patterns, not verified

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in use in project
- Architecture: HIGH - Follows existing project patterns closely
- Pitfalls: MEDIUM - Some based on general Docker/async experience, not verified in this specific context

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable domain, mature libraries)
