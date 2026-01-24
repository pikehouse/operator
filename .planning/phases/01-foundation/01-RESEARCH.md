# Phase 1: Foundation - Research

**Researched:** 2026-01-24
**Domain:** Python project structure, CLI design, Docker Compose programmatic control, interface patterns
**Confidence:** HIGH

## Summary

This phase establishes the core abstractions (Subject adapter interface, deployment abstraction) and local Docker Compose deployment infrastructure. The research focused on four key domains: Python project structure for monorepos, CLI frameworks for the `operator deploy` command, Docker Compose programmatic control, and Python interface patterns for the Subject adapter.

The Python ecosystem has mature, well-documented solutions for all requirements. For project structure, **uv workspaces** provide native monorepo support with shared lockfiles. For CLI, **Typer** offers type-hint-driven command creation with excellent subcommand support. For Docker Compose control, **python-on-whales** provides a comprehensive wrapper around the Docker CLI with full Compose v2 support. For interfaces, **Python Protocols** enable structural subtyping without requiring explicit inheritance, ideal for the Subject adapter pattern.

**Primary recommendation:** Use uv workspaces with Typer CLI, python-on-whales for Docker Compose, and Protocol-based interfaces for clean subject separation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| uv | latest | Package/project management | Rust-based, fast, native workspace support for monorepos |
| typer | 0.21.1 | CLI framework | Type-hint driven, built on Click, excellent subcommand support |
| python-on-whales | latest | Docker Compose control | Direct wrapper around Docker CLI, full Compose v2 API |
| httpx | latest | Async HTTP client | Modern async support, connection pooling, HTTP/2 |
| rich | 14.1.0 | Terminal output, spinners | Progress bars, status spinners, formatted output |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | v2 | Data validation/settings | Config file parsing, API response models |
| pytest | latest | Testing | Unit and integration tests |
| pytest-asyncio | latest | Async test support | Testing async code (httpx clients, etc.) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-on-whales | docker-py | docker-py is lower-level, lacks Compose support |
| python-on-whales | subprocess calls | Loses type safety, error handling complexity |
| Typer | Click | More verbose, no type hints |
| Typer | argparse | Much more boilerplate, no subcommand elegance |
| uv workspaces | Poetry | Poetry monorepo support is less mature |

**Installation:**
```bash
# In project root
uv init --package packages/operator-core
uv add typer rich python-on-whales httpx pydantic
```

## Architecture Patterns

### Recommended Project Structure
```
operator/
├── pyproject.toml           # Workspace root configuration
├── uv.lock                   # Shared lockfile
├── packages/
│   ├── operator-core/       # Core abstractions
│   │   ├── pyproject.toml
│   │   └── src/
│   │       └── operator_core/
│   │           ├── __init__.py
│   │           ├── subject.py       # Subject Protocol
│   │           ├── deploy.py        # Deployment Protocol
│   │           └── cli/
│   │               ├── __init__.py
│   │               └── deploy.py    # Deploy subcommands
│   └── operator-tikv/       # TiKV subject (Phase 2)
│       ├── pyproject.toml
│       └── src/
│           └── operator_tikv/
├── subjects/
│   └── tikv/
│       └── docker-compose.yaml  # TiKV cluster definition
└── deploy/
    └── local.yaml           # Local deployment config
```

### Pattern 1: Protocol-Based Subject Interface
**What:** Use `typing.Protocol` for structural subtyping — subjects implement the interface without explicit inheritance.
**When to use:** Always for the Subject adapter interface (CORE-01)
**Example:**
```python
# Source: https://typing.python.org/en/latest/spec/protocol.html
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class Store:
    id: str
    address: str
    state: str

@dataclass
class Region:
    id: int
    leader_store_id: str

@runtime_checkable
class Subject(Protocol):
    """Interface for subject systems (TiKV, Kafka, etc.)"""

    # Observations
    def get_stores(self) -> list[Store]: ...
    def get_hot_write_regions(self) -> list[Region]: ...
    def get_cluster_metrics(self) -> dict: ...

    # Actions (Phase 2+)
    def transfer_leader(self, region_id: int, to_store_id: str) -> None: ...
```

### Pattern 2: Typer Subcommand Groups
**What:** Organize CLI with nested command groups: `operator deploy local up`
**When to use:** For the deployment CLI (DEPLOY-01, DEPLOY-02)
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/subcommands/
import typer

# Main app
app = typer.Typer(help="Operator for distributed systems")

# Deploy command group
deploy_app = typer.Typer(help="Deployment commands")
app.add_typer(deploy_app, name="deploy")

# Local subcommand group under deploy
local_app = typer.Typer(help="Local Docker Compose deployment")
deploy_app.add_typer(local_app, name="local")

@local_app.command()
def up(
    config: str = typer.Option("subjects/tikv/docker-compose.yaml", help="Compose file path"),
    detach: bool = typer.Option(True, help="Run in background"),
):
    """Start local cluster"""
    ...

@local_app.command()
def down():
    """Stop local cluster"""
    ...

@local_app.command()
def status():
    """Show cluster status"""
    ...
```

### Pattern 3: Deployment Abstraction
**What:** Protocol defining deployment operations, with concrete implementations per target
**When to use:** DEPLOY-01 abstraction
**Example:**
```python
from typing import Protocol
from pathlib import Path

class DeploymentTarget(Protocol):
    """Interface for deployment targets (local, AWS, etc.)"""

    def up(self, config_path: Path) -> None:
        """Start the deployment"""
        ...

    def down(self) -> None:
        """Stop the deployment"""
        ...

    def status(self) -> dict:
        """Get deployment status"""
        ...

    def logs(self, service: str | None = None, follow: bool = False) -> None:
        """Show logs"""
        ...

class LocalDeployment:
    """Docker Compose-based local deployment"""

    def __init__(self, compose_file: Path):
        from python_on_whales import DockerClient
        self.docker = DockerClient(compose_files=[compose_file])

    def up(self, config_path: Path) -> None:
        self.docker.compose.up(detach=True, wait=True)

    def down(self) -> None:
        self.docker.compose.down()
```

### Pattern 4: Constructor Injection for Clients
**What:** Pass HTTP/Prometheus clients to subject constructors rather than subjects creating their own
**When to use:** Subject implementations receiving injected dependencies
**Example:**
```python
# Source: Manual DI pattern (Pythonic approach without frameworks)
import httpx

class TiKVSubject:
    """TiKV subject implementation with injected clients"""

    def __init__(self, pd_client: httpx.AsyncClient, prom_client: httpx.AsyncClient):
        self.pd = pd_client
        self.prom = prom_client

    async def get_stores(self) -> list[Store]:
        response = await self.pd.get("/pd/api/v1/stores")
        # ... parse response

# Composition root (main.py or factory)
async def create_tikv_subject(pd_url: str, prom_url: str) -> TiKVSubject:
    pd_client = httpx.AsyncClient(base_url=pd_url)
    prom_client = httpx.AsyncClient(base_url=prom_url)
    return TiKVSubject(pd_client, prom_client)
```

### Anti-Patterns to Avoid
- **Global client instances:** Don't create module-level httpx clients; inject them for testability
- **Subject creates own clients:** Violates CONTEXT.md decision; core injects clients
- **Hardcoded service URLs:** Use configuration, not hardcoded hostnames
- **Blocking Docker operations:** Use python-on-whales async or run in thread pool
- **Mixing sync/async:** Pick one model per component; don't mix without clear boundaries

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docker Compose control | subprocess calls to `docker compose` | python-on-whales | Type safety, error handling, streaming logs |
| CLI argument parsing | Manual argparse setup | Typer | Auto-generates help, validates types, shell completion |
| Progress indicators | Print statements with spinners | Rich progress/status | Handles terminal width, colors, threading |
| Config file parsing | Manual YAML loading | Pydantic Settings | Validation, type coercion, env var support |
| Health check polling | While loops with sleep | python-on-whales `wait=True` | Handles timeouts, proper exit codes |

**Key insight:** The Docker Compose and CLI ecosystems have mature libraries that handle edge cases (signal handling, terminal resizing, container events) that would take significant effort to implement correctly.

## Common Pitfalls

### Pitfall 1: Blocking on Docker Operations
**What goes wrong:** Main thread blocks during container startup; UI becomes unresponsive
**Why it happens:** Docker operations can take 30+ seconds; synchronous calls freeze the CLI
**How to avoid:** Use Rich's status/spinner while waiting; python-on-whales supports callbacks for events
**Warning signs:** CLI hangs with no output during `deploy up`

### Pitfall 2: Forgetting to Close HTTP Clients
**What goes wrong:** Connection leaks, eventually hitting file descriptor limits
**Why it happens:** httpx.AsyncClient instances not closed properly
**How to avoid:** Always use context managers: `async with httpx.AsyncClient() as client:`
**Warning signs:** "Too many open files" errors in long-running processes

### Pitfall 3: Protocol vs ABC Confusion
**What goes wrong:** Using `@abstractmethod` on Protocol methods, expecting runtime enforcement
**Why it happens:** Protocols are for static type checking; they don't enforce at runtime by default
**How to avoid:** Use `@runtime_checkable` decorator if you need `isinstance()` checks; otherwise trust type checkers
**Warning signs:** Tests pass but production creates objects missing methods

### Pitfall 4: uv Workspace Member Dependencies
**What goes wrong:** Import errors when one package can't find another in the workspace
**Why it happens:** Missing `workspace = true` in `tool.uv.sources` configuration
**How to avoid:** Explicitly declare workspace dependencies:
```toml
[tool.uv.sources]
operator-core = { workspace = true }
```
**Warning signs:** `ModuleNotFoundError` for workspace packages

### Pitfall 5: Docker Compose Health Check Timing
**What goes wrong:** CLI returns before services are actually ready
**Why it happens:** Containers are "running" but applications inside aren't ready
**How to avoid:** Define healthchecks in docker-compose.yaml; use `wait=True` with python-on-whales
**Warning signs:** Immediate failures when trying to connect to just-started services

## Code Examples

Verified patterns from official sources:

### Docker Compose Up with Progress
```python
# Source: https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/compose/
# Source: https://rich.readthedocs.io/en/latest/progress.html
from python_on_whales import DockerClient
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

def deploy_up(compose_file: str):
    docker = DockerClient(compose_files=[compose_file])

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Starting containers...", total=None)

        # up() with wait=True blocks until healthy
        docker.compose.up(detach=True, wait=True)

        progress.update(task, description="[green]Cluster ready!")

    # Print endpoints
    console.print("\n[bold]Services:[/bold]")
    console.print("  Grafana:    http://localhost:3000")
    console.print("  Prometheus: http://localhost:9090")
    console.print("  PD API:     http://localhost:2379")
```

### Typer CLI with Subcommands
```python
# Source: https://typer.tiangolo.com/tutorial/subcommands/
import typer
from pathlib import Path

app = typer.Typer(
    name="operator",
    help="AI-powered operator for distributed systems"
)

deploy_app = typer.Typer(help="Deployment commands")
app.add_typer(deploy_app, name="deploy")

local_app = typer.Typer(help="Local Docker Compose deployment")
deploy_app.add_typer(local_app, name="local")

@local_app.command()
def up(
    subject: str = typer.Argument("tikv", help="Subject to deploy"),
    wait: bool = typer.Option(True, help="Wait for health checks"),
):
    """Start local cluster for a subject."""
    compose_file = Path(f"subjects/{subject}/docker-compose.yaml")
    if not compose_file.exists():
        typer.echo(f"Error: {compose_file} not found", err=True)
        raise typer.Exit(1)

    # Deploy logic here
    typer.echo(f"Starting {subject} cluster...")

@local_app.command()
def down(subject: str = typer.Argument("tikv")):
    """Stop local cluster."""
    typer.echo(f"Stopping {subject} cluster...")

@local_app.command()
def status(subject: str = typer.Argument("tikv")):
    """Show cluster status."""
    ...

@local_app.command()
def logs(
    subject: str = typer.Argument("tikv"),
    service: str = typer.Option(None, help="Specific service"),
    follow: bool = typer.Option(False, "-f", help="Follow logs"),
):
    """View container logs."""
    ...

if __name__ == "__main__":
    app()
```

### Protocol-Based Subject Interface
```python
# Source: https://typing.python.org/en/latest/spec/protocol.html
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class Store:
    id: str
    address: str
    state: str  # "Up", "Down", "Tombstone"

@dataclass
class Region:
    id: int
    leader_store_id: str
    peer_store_ids: list[str]

@dataclass
class ClusterMetrics:
    store_count: int
    region_count: int
    leader_count: dict[str, int]  # store_id -> leader count

@runtime_checkable
class Subject(Protocol):
    """
    Interface for subject systems.

    Implementations provide observations and actions for a specific
    distributed system (TiKV, Kafka, etc.).
    """

    # Observations
    async def get_stores(self) -> list[Store]:
        """Get all stores in the cluster."""
        ...

    async def get_hot_write_regions(self) -> list[Region]:
        """Get regions with high write traffic."""
        ...

    async def get_cluster_metrics(self) -> ClusterMetrics:
        """Get cluster-wide metrics."""
        ...

    # Actions (for Phase 2+, observe-only for now)
    async def transfer_leader(self, region_id: int, to_store_id: str) -> None:
        """Transfer region leader to another store."""
        ...
```

### uv Workspace Configuration
```toml
# pyproject.toml (workspace root)
[project]
name = "operator"
version = "0.1.0"
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv.workspace]
members = ["packages/*"]

# packages/operator-core/pyproject.toml
[project]
name = "operator-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.21.0",
    "rich>=14.0.0",
    "python-on-whales>=0.70.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/operator_core"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Poetry for monorepos | uv workspaces | 2024-2025 | Native workspace support, much faster |
| docker-py for Compose | python-on-whales | 2022+ | Full Compose v2 support |
| Click for CLIs | Typer (built on Click) | 2020+ | Type hints, less boilerplate |
| ABC for interfaces | Protocol | Python 3.8+ | Structural subtyping, no inheritance required |
| requests for HTTP | httpx | 2020+ | Async support, HTTP/2 |

**Deprecated/outdated:**
- **docker-compose v1**: Compose v2 is now standard; python-on-whales only supports v2
- **typer-cli package**: Merged into typer; install `typer` not `typer-cli`
- **Manual argparse**: Typer eliminates 90% of boilerplate

## Open Questions

Things that couldn't be fully resolved:

1. **Async vs sync for CLI operations**
   - What we know: Typer is sync by default; python-on-whales can be used sync
   - What's unclear: Whether async provides benefits for CLI tool (not long-running)
   - Recommendation: Start sync for simplicity; refactor to async if needed for concurrent operations

2. **Container log streaming implementation**
   - What we know: python-on-whales supports `logs(stream=True)` returning an iterator
   - What's unclear: Best way to integrate with Rich output
   - Recommendation: Start with simple `logs(follow=True)`, enhance later

## Sources

### Primary (HIGH confidence)
- [Typer Official Docs](https://typer.tiangolo.com/) - Subcommands, CLI patterns
- [Python Protocols Spec](https://typing.python.org/en/latest/spec/protocol.html) - Protocol definition, runtime_checkable
- [uv Workspaces Docs](https://docs.astral.sh/uv/concepts/projects/workspaces/) - Workspace configuration
- [python-on-whales Docs](https://gabrieldemarmiesse.github.io/python-on-whales/) - Compose API
- [Rich Progress Docs](https://rich.readthedocs.io/en/latest/progress.html) - Spinners, progress bars
- [httpx Async Docs](https://www.python-httpx.org/async/) - AsyncClient patterns

### Secondary (MEDIUM confidence)
- [pingcap/tidb-docker-compose](https://github.com/pingcap/tidb-docker-compose) - TiDB/TiKV cluster structure
- [Docker Compose healthcheck docs](https://docs.docker.com/reference/compose-file/services/) - Health check configuration

### Tertiary (LOW confidence)
- Community articles on Python monorepo patterns (multiple sources agree)
- DI pattern recommendations (multiple sources agree on constructor injection)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries have official documentation, versions verified
- Architecture: HIGH - Patterns from official docs, CONTEXT.md decisions respected
- Pitfalls: MEDIUM - Based on general Python/Docker knowledge, some from community sources

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable ecosystem)
