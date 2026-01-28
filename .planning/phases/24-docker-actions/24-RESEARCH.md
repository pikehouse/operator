# Phase 24: Docker Actions - Research

**Researched:** 2026-01-27
**Domain:** Docker container lifecycle management, python-on-whales, asyncio executor patterns
**Confidence:** HIGH

## Summary

This research covers implementing Docker container lifecycle actions (start/stop/restart/logs/inspect/exec/network) as ActionType.TOOL in the operator-core actions framework. The actions will enable agents to remediate containerized infrastructure failures.

The standard approach uses python-on-whales (already installed) as the Docker CLI wrapper, wrapped with asyncio.run_in_executor() to prevent blocking the event loop. Python-on-whales provides 1-to-1 mapping to Docker CLI commands with type-safe objects, thread-safe operation, and comprehensive exception handling. All blocking calls execute in ThreadPoolExecutor (default size: min(32, cpu_count + 4)) to maintain async responsiveness.

Key findings: Docker logs with tail limits prevent memory exhaustion (10,000 line max recommended), graceful shutdown requires 10-second default timeout with SIGTERM before SIGKILL, container exit codes 137 (SIGKILL/OOM) and 143 (SIGTERM) indicate different failure modes, and network operations require validation that containers and networks exist before connect/disconnect.

**Primary recommendation:** Use python-on-whales wrapped in asyncio.run_in_executor() for all Docker operations, implement 10,000 line tail limit for logs, validate container/network existence before operations, handle NoSuchContainer exceptions gracefully, and follow existing TOOL_EXECUTORS pattern from tools.py.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-on-whales | 0.70.0+ | Docker CLI wrapper | Already installed, 1-to-1 CLI mapping, thread-safe, comprehensive typed objects |
| asyncio | stdlib (3.11+) | Async executor pattern | run_in_executor() wraps blocking I/O, maintains event loop responsiveness |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| concurrent.futures | stdlib | ThreadPoolExecutor | Default executor for run_in_executor(), I/O-bound Docker operations |
| typing | stdlib | Type hints for Container objects | Type safety for Docker objects returned by python-on-whales |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-on-whales | docker-py (official SDK) | python-on-whales wraps CLI (stable API), docker-py wraps Engine API (more complex, version-dependent) |
| asyncio.run_in_executor() | aiodocker (async native) | aiodocker is async-first but less mature, python-on-whales has better typing and CLI parity |
| ThreadPoolExecutor | ProcessPoolExecutor | Docker CLI I/O-bound not CPU-bound, threads sufficient and faster for small operations |

**Installation:**
```bash
# Already installed in operator-core pyproject.toml
python-on-whales>=0.70.0
```

## Architecture Patterns

### Recommended Project Structure
```
operator-core/src/operator_core/
├── actions/
│   ├── tools.py           # Existing: wait, log_message (extend with Docker actions)
│   ├── executor.py        # Existing: ActionExecutor (already handles ActionType.TOOL)
│   └── registry.py        # Existing: ActionDefinition (for metadata)
└── docker/
    ├── __init__.py        # Public API exports
    ├── actions.py         # NEW: Docker action executors (start, stop, restart, etc.)
    └── client.py          # NEW: Shared DockerClient with executor wrapping
```

### Pattern 1: Async Executor Wrapping for Blocking Docker Operations
**What:** Wrap synchronous python-on-whales calls with asyncio.run_in_executor() to prevent event loop blocking
**When to use:** All Docker operations (python-on-whales is synchronous, blocks on subprocess calls)

**Example:**
```python
# Source: Python asyncio docs + python-on-whales thread safety research
import asyncio
from python_on_whales import docker, Container
from typing import Any

class DockerActionExecutor:
    """
    Async wrapper for Docker operations using python-on-whales.

    All methods use run_in_executor() to prevent blocking the event loop.
    Python-on-whales is thread-safe so we can share the client.
    """

    def __init__(self):
        # python-on-whales client is thread-safe (no intermediate state)
        self._docker = docker

    async def start_container(self, container_id: str) -> dict[str, Any]:
        """
        Start a stopped container.

        Args:
            container_id: Container ID or name

        Returns:
            Dict with container status

        Raises:
            NoSuchContainer: If container doesn't exist
        """
        def _start() -> Container:
            return self._docker.container.start(container_id)

        # Run blocking operation in thread pool
        loop = asyncio.get_running_loop()
        container = await loop.run_in_executor(None, _start)

        return {
            "container_id": container.id,
            "name": container.name,
            "state": container.state.status,
            "started_at": container.state.started_at.isoformat() if container.state.started_at else None,
        }

    async def stop_container(
        self,
        container_id: str,
        timeout: int = 10
    ) -> dict[str, Any]:
        """
        Stop a running container gracefully (SIGTERM then SIGKILL).

        Args:
            container_id: Container ID or name
            timeout: Seconds to wait before SIGKILL (default: 10)

        Returns:
            Dict with stop outcome
        """
        def _stop() -> Container:
            self._docker.container.stop(container_id, time=timeout)
            return self._docker.container.inspect(container_id)

        loop = asyncio.get_running_loop()
        container = await loop.run_in_executor(None, _stop)

        return {
            "container_id": container.id,
            "name": container.name,
            "state": container.state.status,
            "exit_code": container.state.exit_code,
            "stopped_at": container.state.finished_at.isoformat() if container.state.finished_at else None,
        }
```

### Pattern 2: Logs with Tail Limit and Streaming
**What:** Retrieve container logs with configurable tail limit (max 10,000 lines) to prevent memory exhaustion
**When to use:** Agent needs to inspect recent container output for debugging

**Example:**
```python
# Source: Docker logs best practices + python-on-whales logs() API
async def get_container_logs(
    self,
    container_id: str,
    tail: int | None = None,
    follow: bool = False,
    since: str | None = None,
) -> dict[str, Any]:
    """
    Retrieve container logs with tail limit.

    Args:
        container_id: Container ID or name
        tail: Number of lines from end (max 10000, default: 100)
        follow: Stream logs continuously (not recommended for actions)
        since: Only logs after this timestamp/duration

    Returns:
        Dict with logs and metadata
    """
    # Enforce maximum tail limit to prevent memory issues
    MAX_TAIL = 10000
    DEFAULT_TAIL = 100

    if tail is None:
        tail = DEFAULT_TAIL
    elif tail > MAX_TAIL:
        tail = MAX_TAIL

    def _get_logs() -> str:
        # python-on-whales logs() returns str by default
        return self._docker.container.logs(
            container_id,
            tail=tail,
            follow=False,  # Never follow in action context (blocks indefinitely)
            since=since,
            timestamps=True,  # Include timestamps for debugging
        )

    loop = asyncio.get_running_loop()
    logs = await loop.run_in_executor(None, _get_logs)

    # Count actual lines returned
    lines = logs.strip().split('\n') if logs else []

    return {
        "container_id": container_id,
        "lines": lines,
        "line_count": len(lines),
        "tail_limit": tail,
        "truncated": len(lines) == tail,  # May have more logs available
    }
```

### Pattern 3: Container Inspection (Read-Only Status Check)
**What:** Get container state without modifying it (safe diagnostic operation)
**When to use:** Agent needs to check container status before proposing actions

**Example:**
```python
# Source: python-on-whales Container object attributes research
async def inspect_container(self, container_id: str) -> dict[str, Any]:
    """
    Inspect container status and configuration (read-only).

    Args:
        container_id: Container ID or name

    Returns:
        Dict with container state, config, and network info

    Raises:
        NoSuchContainer: If container doesn't exist
    """
    def _inspect() -> Container:
        return self._docker.container.inspect(container_id)

    loop = asyncio.get_running_loop()
    container = await loop.run_in_executor(None, _inspect)

    # Extract key attributes from Container object
    return {
        "id": container.id,
        "name": container.name,
        "state": {
            "status": container.state.status,
            "running": container.state.running,
            "paused": container.state.paused,
            "restarting": container.state.restarting,
            "oom_killed": container.state.oom_killed,
            "dead": container.state.dead,
            "pid": container.state.pid,
            "exit_code": container.state.exit_code,
            "error": container.state.error,
            "started_at": container.state.started_at.isoformat() if container.state.started_at else None,
            "finished_at": container.state.finished_at.isoformat() if container.state.finished_at else None,
        },
        "config": {
            "image": container.config.image,
            "hostname": container.config.hostname,
            "user": container.config.user,
            "working_dir": str(container.config.working_dir),
            "env": container.config.env,
            "labels": container.config.labels,
        },
        "network_settings": {
            "networks": {
                name: {
                    "ip_address": net.ip_address,
                    "gateway": net.gateway,
                    "mac_address": net.mac_address,
                }
                for name, net in (container.network_settings.networks or {}).items()
            }
        }
    }
```

### Pattern 4: Network Connect/Disconnect with Validation
**What:** Attach/detach containers from Docker networks with existence validation
**When to use:** Agent needs to isolate misbehaving containers or restore network connectivity

**Example:**
```python
# Source: python-on-whales network.connect/disconnect API + validation patterns
async def connect_container_to_network(
    self,
    container_id: str,
    network_name: str,
    alias: str | None = None,
) -> dict[str, Any]:
    """
    Connect container to a network.

    Args:
        container_id: Container ID or name
        network_name: Network name or ID
        alias: Optional network-scoped alias

    Returns:
        Dict with connection result

    Raises:
        NoSuchContainer: If container doesn't exist
        NoSuchNetwork: If network doesn't exist
    """
    def _connect() -> None:
        # Validate container exists first (better error message)
        self._docker.container.inspect(container_id)

        # Validate network exists
        if not self._docker.network.exists(network_name):
            from python_on_whales.exceptions import NoSuchNetwork
            raise NoSuchNetwork(f"Network '{network_name}' not found")

        # Connect container to network
        self._docker.network.connect(
            network_name,
            container_id,
            alias=alias,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _connect)

    # Re-inspect to get updated network settings
    container = await self.inspect_container(container_id)

    return {
        "container_id": container_id,
        "network": network_name,
        "alias": alias,
        "networks": list(container["network_settings"]["networks"].keys()),
    }

async def disconnect_container_from_network(
    self,
    container_id: str,
    network_name: str,
    force: bool = False,
) -> dict[str, Any]:
    """
    Disconnect container from a network.

    Args:
        container_id: Container ID or name
        network_name: Network name or ID
        force: Force disconnection even if container is running

    Returns:
        Dict with disconnection result
    """
    def _disconnect() -> None:
        self._docker.network.disconnect(
            network_name,
            container_id,
            force=force,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _disconnect)

    return {
        "container_id": container_id,
        "network": network_name,
        "disconnected": True,
    }
```

### Pattern 5: Execute Command in Container with Output Capture
**What:** Run commands inside containers with stdout/stderr capture (like docker exec)
**When to use:** Agent needs to run diagnostics or repairs inside containers

**Example:**
```python
# Source: python-on-whales execute() API + security best practices
async def execute_command(
    self,
    container_id: str,
    command: list[str],
    user: str | None = None,
    workdir: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Execute command inside a running container.

    Args:
        container_id: Container ID or name
        command: Command and arguments as list (e.g., ['ls', '-la'])
        user: Run as specific user (default: container's default user)
        workdir: Working directory inside container
        env: Additional environment variables

    Returns:
        Dict with command output and exit code

    Raises:
        NoSuchContainer: If container doesn't exist
    """
    def _execute() -> str:
        # python-on-whales execute() returns output as string
        # Raises DockerException if command fails
        return self._docker.container.execute(
            container_id,
            command,
            user=user,
            workdir=workdir,
            envs=env or {},
            tty=False,  # No TTY for programmatic access
            interactive=False,  # No stdin
        )

    loop = asyncio.get_running_loop()

    try:
        output = await loop.run_in_executor(None, _execute)
        success = True
        error = None
    except Exception as e:
        output = ""
        success = False
        error = str(e)

    return {
        "container_id": container_id,
        "command": command,
        "success": success,
        "output": output,
        "error": error,
    }
```

### Pattern 6: Registration as ActionType.TOOL
**What:** Register Docker actions in get_general_tools() for agent discovery
**When to use:** Always - enables agent to propose Docker actions

**Example:**
```python
# Source: Existing tools.py pattern + ActionDefinition structure
from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType

def get_docker_tools() -> list[ActionDefinition]:
    """
    Get Docker action tool definitions.

    Returns:
        List of ActionDefinition for Docker operations
    """
    return [
        ActionDefinition(
            name="docker_start_container",
            description="Start a stopped Docker container",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name to start",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",
            requires_approval=True,  # Infrastructure changes need approval
        ),
        ActionDefinition(
            name="docker_stop_container",
            description="Stop a running Docker container gracefully (SIGTERM then SIGKILL after timeout)",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name to stop",
                    required=True,
                ),
                "timeout": ParamDef(
                    type="int",
                    description="Seconds to wait before force kill (default: 10)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",  # Stopping containers impacts availability
            requires_approval=True,
        ),
        ActionDefinition(
            name="docker_restart_container",
            description="Restart a Docker container (stop then start)",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name to restart",
                    required=True,
                ),
                "timeout": ParamDef(
                    type="int",
                    description="Seconds to wait for stop before force kill (default: 10)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
            requires_approval=True,
        ),
        ActionDefinition(
            name="docker_logs",
            description="Retrieve container logs with tail limit (max 10000 lines)",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name",
                    required=True,
                ),
                "tail": ParamDef(
                    type="int",
                    description="Number of lines from end (max 10000, default: 100)",
                    required=False,
                ),
                "since": ParamDef(
                    type="str",
                    description="Only logs after this timestamp (e.g., '2024-01-27T10:00:00')",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="low",  # Read-only operation
            requires_approval=False,
        ),
        ActionDefinition(
            name="docker_inspect_container",
            description="Get container status and configuration (read-only)",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name to inspect",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="low",  # Read-only operation
            requires_approval=False,
        ),
        ActionDefinition(
            name="docker_network_connect",
            description="Connect container to a Docker network",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name",
                    required=True,
                ),
                "network": ParamDef(
                    type="str",
                    description="Network name or ID",
                    required=True,
                ),
                "alias": ParamDef(
                    type="str",
                    description="Optional network-scoped alias for the container",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",
            requires_approval=True,
        ),
        ActionDefinition(
            name="docker_network_disconnect",
            description="Disconnect container from a Docker network",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name",
                    required=True,
                ),
                "network": ParamDef(
                    type="str",
                    description="Network name or ID",
                    required=True,
                ),
                "force": ParamDef(
                    type="bool",
                    description="Force disconnect even if container is running (default: false)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",
            requires_approval=True,
        ),
        ActionDefinition(
            name="docker_exec",
            description="Execute command inside a running container with output capture",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name",
                    required=True,
                ),
                "command": ParamDef(
                    type="list",
                    description="Command and arguments as list (e.g., ['ls', '-la'])",
                    required=True,
                ),
                "user": ParamDef(
                    type="str",
                    description="Run as specific user (default: container's default user)",
                    required=False,
                ),
                "workdir": ParamDef(
                    type="str",
                    description="Working directory inside container",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",  # Arbitrary command execution
            requires_approval=True,
        ),
    ]

# In tools.py, extend get_general_tools():
def get_general_tools() -> list[ActionDefinition]:
    """Get all general-purpose tool definitions."""
    from operator_core.docker.actions import get_docker_tools

    base_tools = [
        # ... existing wait, log_message ...
    ]

    docker_tools = get_docker_tools()

    return base_tools + docker_tools

# Extend TOOL_EXECUTORS map:
from operator_core.docker.actions import DockerActionExecutor

_docker_executor = DockerActionExecutor()

TOOL_EXECUTORS = {
    "wait": execute_wait,
    "log_message": execute_log_message,
    "docker_start_container": _docker_executor.start_container,
    "docker_stop_container": _docker_executor.stop_container,
    "docker_restart_container": _docker_executor.restart_container,
    "docker_logs": _docker_executor.get_container_logs,
    "docker_inspect_container": _docker_executor.inspect_container,
    "docker_network_connect": _docker_executor.connect_container_to_network,
    "docker_network_disconnect": _docker_executor.disconnect_container_from_network,
    "docker_exec": _docker_executor.execute_command,
}
```

### Anti-Patterns to Avoid
- **Calling python-on-whales directly in async functions without executor:** Blocks event loop on subprocess calls, freezes entire application
- **Using follow=True on logs() in actions:** Streams indefinitely, never returns, blocks executor thread
- **No tail limit on logs:** Large log files (GB+) cause memory exhaustion when loaded into strings
- **Not validating container/network existence before operations:** Poor error messages, unclear failures
- **Using ProcessPoolExecutor instead of ThreadPoolExecutor:** Docker operations are I/O-bound, process overhead adds latency
- **Ignoring NoSuchContainer exceptions:** Crashes instead of graceful failure reporting

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docker API interactions | Custom subprocess calls to `docker` CLI | python-on-whales | Type-safe objects, comprehensive error handling, 1-to-1 CLI mapping, actively maintained |
| Async wrapping of blocking I/O | Custom thread pool management | asyncio.run_in_executor(None, ...) | Uses default ThreadPoolExecutor, automatic thread lifecycle, proper cleanup |
| Container log streaming | Manual tail -f subprocess | python-on-whales logs(tail=N) | Handles compressed logs, respects Docker logging drivers, proper stream cleanup |
| Container state inspection | Parsing `docker ps` output | python-on-whales Container objects | Typed attributes, real-time updates, handles all state transitions |
| Network existence checks | Try-catch on connect | docker.network.exists() | Explicit check, better error messages, avoids exception overhead |

**Key insight:** Docker CLI has 200+ commands with subtle flags and edge cases. Python-on-whales provides battle-tested wrappers that handle parsing, error codes, and object lifecycle. Rolling custom wrappers duplicates years of community bug fixes.

## Common Pitfalls

### Pitfall 1: Blocking Event Loop with Synchronous Docker Calls
**What goes wrong:** Direct python-on-whales calls block event loop for 100ms-5s per operation, freezing entire application
**Why it happens:** python-on-whales uses subprocess.run() internally, which blocks until Docker CLI returns
**How to avoid:** Always wrap in `await loop.run_in_executor(None, _blocking_func)`
**Warning signs:** Application becomes unresponsive during Docker operations, TUI freezes, timeouts on other async tasks

### Pitfall 2: Unbounded Log Retrieval Exhausts Memory
**What goes wrong:** Calling logs() without tail parameter on container with GB of logs loads entire file into memory, OOM crash
**Why it happens:** Default behavior retrieves all logs, Docker doesn't enforce limits
**How to avoid:** Always specify tail parameter, enforce max 10,000 lines in action layer
**Warning signs:** Memory usage spikes during log operations, application crashes with OOM on large containers

### Pitfall 3: Confusing Exit Codes 137 vs 143
**What goes wrong:** Agent reports "container killed" without distinguishing graceful shutdown (143) from OOM/force-kill (137)
**Why it happens:** Both are non-zero exit codes, easy to treat identically
**How to avoid:** Check container.state.exit_code specifically: 137 = SIGKILL/OOM, 143 = SIGTERM success
**Warning signs:** Diagnoses miss OOM conditions, agent can't distinguish clean stops from crashes

### Pitfall 4: Not Handling Container Already Stopped/Started
**What goes wrong:** start_container() fails with exception when container already running, unclear error to user
**Why it happens:** Docker CLI returns error for start on running container
**How to avoid:** Check container.state.running before start/stop, return idempotent success if already in desired state
**Warning signs:** Actions fail with "already running" errors, agent retries unnecessarily

### Pitfall 5: Default 10-Second Stop Timeout Too Short for Graceful Shutdown
**What goes wrong:** Container killed with SIGKILL (exit 137) before graceful shutdown completes
**Why it happens:** Some apps need >10s to flush data, close connections, cleanup
**How to avoid:** Make timeout configurable parameter, default 10s but allow override to 30s for databases
**Warning signs:** Containers always exit with 137, never 143, data corruption on restarts

### Pitfall 6: Network Connect Without Existence Validation
**What goes wrong:** Generic "network not found" error deep in stack, unclear to agent which network is missing
**Why it happens:** python-on-whales network.connect() validates lazily during operation
**How to avoid:** Explicitly check docker.network.exists(network_name) first, raise clear error
**Warning signs:** Agent logs show "unknown error" during network operations, retry storms

### Pitfall 7: Execute Command Without User Specification Runs as Root
**What goes wrong:** Security violation - command runs as root inside container when non-root expected
**Why it happens:** docker exec defaults to container's default user (often root in images)
**How to avoid:** Always specify user parameter explicitly, never rely on container default
**Warning signs:** Security audit flags root command execution, privilege escalation possible

### Pitfall 8: Streaming Logs with follow=True Blocks Executor Thread Forever
**What goes wrong:** Thread pool executor thread blocked indefinitely on logs(follow=True), thread pool exhaustion
**Why it happens:** follow=True streams logs until container stops, never returns
**How to avoid:** Never use follow=True in action context, only tail=N for snapshot
**Warning signs:** Available executor threads decrease over time, new actions timeout waiting for threads

### Pitfall 9: Container Name vs ID Confusion
**What goes wrong:** Action succeeds with container name but fails with ID or vice versa
**Why it happens:** Inconsistent handling of ValidContainer types
**How to avoid:** python-on-whales accepts both, treat uniformly, always return both in results
**Warning signs:** Actions fail intermittently based on how agent specified container

### Pitfall 10: ThreadPoolExecutor Size Not Configured for Docker Operations
**What goes wrong:** Default executor size (cpu_count + 4) may be insufficient for many concurrent Docker operations
**Why it happens:** Default sizing designed for CPU-bound work, Docker operations are I/O-bound
**How to avoid:** Accept default, Docker CLI operations typically fast (<100ms), queue naturally
**Warning signs:** Actions queue waiting for executor threads, but CPU usage low

## Code Examples

Verified patterns from official sources:

### Complete DockerActionExecutor Skeleton
```python
# Source: Combining asyncio.run_in_executor + python-on-whales patterns
import asyncio
from typing import Any
from python_on_whales import docker, Container
from python_on_whales.exceptions import NoSuchContainer, NoSuchNetwork

class DockerActionExecutor:
    """
    Async executor for Docker container lifecycle operations.

    All methods wrap blocking python-on-whales calls with run_in_executor()
    to prevent blocking the asyncio event loop.

    Pattern: DOCK-09 requirement - all Docker actions use async executor wrapping.
    """

    def __init__(self):
        # Shared Docker client (thread-safe per python-on-whales docs)
        self._docker = docker

    async def start_container(self, container_id: str) -> dict[str, Any]:
        """DOCK-01: Start a stopped container."""
        loop = asyncio.get_running_loop()

        def _start() -> Container:
            # Check current state for idempotency
            container = self._docker.container.inspect(container_id)
            if container.state.running:
                return container  # Already running, idempotent

            self._docker.container.start(container_id)
            return self._docker.container.inspect(container_id)

        container = await loop.run_in_executor(None, _start)

        return {
            "container_id": container.id,
            "name": container.name,
            "state": container.state.status,
            "running": container.state.running,
        }

    async def stop_container(
        self,
        container_id: str,
        timeout: int = 10
    ) -> dict[str, Any]:
        """DOCK-02: Stop a running container (graceful SIGTERM then SIGKILL)."""
        loop = asyncio.get_running_loop()

        def _stop() -> Container:
            container = self._docker.container.inspect(container_id)
            if not container.state.running:
                return container  # Already stopped, idempotent

            self._docker.container.stop(container_id, time=timeout)
            return self._docker.container.inspect(container_id)

        container = await loop.run_in_executor(None, _stop)

        return {
            "container_id": container.id,
            "name": container.name,
            "state": container.state.status,
            "exit_code": container.state.exit_code,
            "graceful_shutdown": container.state.exit_code == 143,  # SIGTERM
            "killed": container.state.exit_code == 137,  # SIGKILL or OOM
        }

    async def restart_container(
        self,
        container_id: str,
        timeout: int = 10
    ) -> dict[str, Any]:
        """DOCK-03: Restart a container (stop then start)."""
        loop = asyncio.get_running_loop()

        def _restart() -> Container:
            self._docker.container.restart(container_id, time=timeout)
            return self._docker.container.inspect(container_id)

        container = await loop.run_in_executor(None, _restart)

        return {
            "container_id": container.id,
            "name": container.name,
            "state": container.state.status,
            "running": container.state.running,
        }

    async def get_container_logs(
        self,
        container_id: str,
        tail: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """DOCK-04: Retrieve container logs with tail limit (max 10000 lines)."""
        MAX_TAIL = 10000
        DEFAULT_TAIL = 100

        if tail is None:
            tail = DEFAULT_TAIL
        elif tail > MAX_TAIL:
            tail = MAX_TAIL

        loop = asyncio.get_running_loop()

        def _get_logs() -> str:
            return self._docker.container.logs(
                container_id,
                tail=tail,
                since=since,
                timestamps=True,
                follow=False,  # NEVER follow in actions
            )

        logs = await loop.run_in_executor(None, _get_logs)
        lines = logs.strip().split('\n') if logs else []

        return {
            "container_id": container_id,
            "logs": logs,
            "line_count": len(lines),
            "tail_limit": tail,
            "truncated": len(lines) == tail,
        }

    async def inspect_container(self, container_id: str) -> dict[str, Any]:
        """DOCK-05: Return container status and config (read-only)."""
        loop = asyncio.get_running_loop()

        def _inspect() -> Container:
            return self._docker.container.inspect(container_id)

        container = await loop.run_in_executor(None, _inspect)

        return {
            "id": container.id,
            "name": container.name,
            "image": container.config.image,
            "state": {
                "status": container.state.status,
                "running": container.state.running,
                "paused": container.state.paused,
                "exit_code": container.state.exit_code,
                "started_at": container.state.started_at.isoformat() if container.state.started_at else None,
            },
            "networks": list((container.network_settings.networks or {}).keys()),
        }

    async def connect_container_to_network(
        self,
        container_id: str,
        network: str,
        alias: str | None = None,
    ) -> dict[str, Any]:
        """DOCK-06: Connect container to network with validation."""
        loop = asyncio.get_running_loop()

        def _connect() -> None:
            # Validate container exists
            self._docker.container.inspect(container_id)

            # Validate network exists
            if not self._docker.network.exists(network):
                raise NoSuchNetwork(f"Network '{network}' not found")

            # Connect
            self._docker.network.connect(network, container_id, alias=alias)

        await loop.run_in_executor(None, _connect)

        return {
            "container_id": container_id,
            "network": network,
            "alias": alias,
            "connected": True,
        }

    async def disconnect_container_from_network(
        self,
        container_id: str,
        network: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """DOCK-07: Disconnect container from network."""
        loop = asyncio.get_running_loop()

        def _disconnect() -> None:
            self._docker.network.disconnect(network, container_id, force=force)

        await loop.run_in_executor(None, _disconnect)

        return {
            "container_id": container_id,
            "network": network,
            "disconnected": True,
        }

    async def execute_command(
        self,
        container_id: str,
        command: list[str],
        user: str | None = None,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        """DOCK-08: Execute command in container with output capture."""
        loop = asyncio.get_running_loop()

        def _execute() -> str:
            return self._docker.container.execute(
                container_id,
                command,
                user=user,
                workdir=workdir,
                tty=False,
                interactive=False,
            )

        try:
            output = await loop.run_in_executor(None, _execute)
            success = True
            error = None
        except Exception as e:
            output = ""
            success = False
            error = str(e)

        return {
            "container_id": container_id,
            "command": command,
            "success": success,
            "output": output,
            "error": error,
        }
```

### Exception Handling Pattern
```python
# Source: python-on-whales exception handling research
from python_on_whales.exceptions import NoSuchContainer, NoSuchNetwork, DockerException

async def safe_docker_operation(container_id: str) -> dict[str, Any]:
    """
    Example of proper exception handling for Docker operations.

    All python-on-whales exceptions inherit from DockerException and
    have attributes: docker_command, return_code, stdout, stderr.
    """
    try:
        result = await docker_executor.start_container(container_id)
        return {"success": True, "result": result}

    except NoSuchContainer as e:
        # Specific exception for missing containers
        return {
            "success": False,
            "error": "container_not_found",
            "message": f"Container '{container_id}' does not exist",
            "docker_command": e.docker_command,
            "return_code": e.return_code,
        }

    except DockerException as e:
        # Generic Docker CLI errors
        return {
            "success": False,
            "error": "docker_error",
            "message": str(e),
            "docker_command": e.docker_command,
            "return_code": e.return_code,
            "stderr": e.stderr,
        }

    except Exception as e:
        # Unexpected errors (network issues, etc.)
        return {
            "success": False,
            "error": "unexpected_error",
            "message": str(e),
        }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| docker-py (official SDK) | python-on-whales | 2020-2023 | CLI wrapper more stable than Engine API, better typing, 1-to-1 command mapping |
| Unbounded log retrieval | Tail limits (50-10000) | 2025-2026 | Prevents memory exhaustion on large log files |
| ProcessPoolExecutor for I/O | ThreadPoolExecutor | Always | Threads faster for I/O-bound work, less overhead than processes |
| Manual graceful shutdown | Docker stop with timeout | Docker 1.13+ (2017) | SIGTERM then SIGKILL after configurable delay |
| Default bridge network | User-defined bridge networks | 2015-2020 | Better isolation, automatic DNS, security boundaries |
| docker exec as root | Explicit user parameter | 2018-2020 | Security best practice, least-privilege principle |
| Synchronous blocking calls | asyncio.run_in_executor() | Python 3.7+ (2018) | Maintains async responsiveness, prevents event loop blocking |

**Deprecated/outdated:**
- **docker-py for new projects:** python-on-whales preferred for CLI stability and typing
- **logs(follow=True) in automation:** Only for interactive terminals, blocks indefinitely in code
- **Assuming 10s timeout sufficient:** Databases and stateful services often need 30-60s
- **Ignoring exit codes:** 137 (SIGKILL) vs 143 (SIGTERM) critical for diagnosing failures

## Open Questions

Things that couldn't be fully resolved:

1. **Should Docker actions be rate-limited separately from TiKV actions?**
   - What we know: Docker operations typically fast (<100ms), but container lifecycle changes are infrastructure-impacting
   - What's unclear: Whether to enforce per-action-type rate limits or global rate limit
   - Recommendation: Start with global rate limit (existing system), add per-type limits later if needed

2. **How to handle container dependencies (e.g., can't stop PD if TiKV depends on it)?**
   - What we know: Docker has depends_on for compose, but no runtime dependency enforcement
   - What's unclear: Should actions validate dependencies or trust agent reasoning
   - Recommendation: Phase 24 doesn't validate dependencies, agent must reason about impact. Phase 25+ could add dependency checking.

3. **Should docker_exec be restricted to specific commands (e.g., only diagnostic commands)?**
   - What we know: Arbitrary command execution is high risk (exit code 137, data corruption)
   - What's unclear: Whether to allowlist commands or trust safety controls (approval + audit)
   - Recommendation: Start with approval requirement + audit logging, add command allowlist in Phase 25+ if security review requires it

4. **How to handle multi-container operations (e.g., restart all TiKV nodes)?**
   - What we know: Individual container operations work, but agents may need batch operations
   - What's unclear: Whether to add batch actions or let agent propose multiple single-container actions
   - Recommendation: Phase 24 single-container only, workflows (Phase 15) handle multi-container via multiple actions

5. **Should logs be streamed to agent or returned as batch?**
   - What we know: follow=True blocks forever, tail=N returns snapshot
   - What's unclear: Whether agent needs real-time streaming or batch is sufficient
   - Recommendation: Phase 24 batch only (tail=N), streaming could be added later with different action (docker_logs_stream with iterator)

## Sources

### Primary (HIGH confidence)
- [python-on-whales GitHub](https://github.com/gabrieldemarmiesse/python-on-whales) - Library repository, issues, examples
- [python-on-whales Container Docs](https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/container/) - Container lifecycle API reference
- [python-on-whales Objects/Containers](https://gabrieldemarmiesse.github.io/python-on-whales/objects/containers/) - Container object attributes
- [python-on-whales Network Docs](https://gabrieldemarmiesse.github.io/python-on-whales/sub-commands/network/) - Network connect/disconnect API
- [python-on-whales Docker Client](https://gabrieldemarmiesse.github.io/python-on-whales/docker_client/) - Thread safety, usage patterns
- [python-on-whales Exceptions](https://gabrieldemarmiesse.github.io/python-on-whales/user_guide/exceptions/) - Exception handling, NoSuchContainer
- [Python asyncio Docs: concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html) - ThreadPoolExecutor default sizing
- [Python asyncio Docs: run_in_executor](https://docs.python.org/3/library/asyncio-eventloop.html) - Executor wrapping pattern
- [Docker CLI Reference: logs](https://docs.docker.com/reference/cli/docker/container/logs/) - Tail parameter, timestamps, follow flag
- [Docker CLI Reference: stop](https://docs.docker.com/reference/cli/docker/container/stop/) - Graceful shutdown timeout
- [Docker CLI Reference: exec](https://docs.docker.com/reference/cli/docker/container/exec/) - Command execution, user parameter

### Secondary (MEDIUM confidence)
- [Docker Logs Tail Guide - Uptrace](https://uptrace.dev/blog/docker-logs-tail) - Tail limit best practices (50-100 typical, 10000 max recommended)
- [Docker Logs Memory - GitHub Issue](https://github.com/moby/moby/issues/41678) - Compressed logs memory consumption issue
- [Docker Exit Codes Guide - Komodor](https://komodor.com/learn/exit-codes-in-containers-and-kubernetes-the-complete-guide/) - Exit code 137 (SIGKILL) vs 143 (SIGTERM) meanings
- [Docker Exit Code 137 Fix - DevToDevOps](https://devtodevops.com/blog/docker-container-exit-code-137/) - OOM vs manual kill
- [Docker Exit Code 143 - groundcover](https://www.groundcover.com/kubernetes-troubleshooting/exit-code-143) - Graceful termination verification
- [Docker Graceful Shutdown - CompileNRun](https://www.compilenrun.com/docs/devops/docker/docker-management/docker-stop/) - SIGTERM timeout best practices
- [Docker Network Bridge Best Practices - Docker Docs](https://docs.docker.com/engine/network/drivers/bridge/) - User-defined networks vs default bridge
- [Docker Network Isolation - CyberPanel](https://cyberpanel.net/blog/docker-bridge-network) - Network isolation patterns 2026
- [Docker Exec Security - Better Stack](https://betterstack.com/community/guides/scaling-docker/docker-exec/) - User parameter security
- [Docker Security Best Practices - OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html) - Exec security, least privilege
- [asyncio Blocking I/O - BBC CloudFit](https://bbc.github.io/cloudfit-public-docs/asyncio/asyncio-part-5.html) - run_in_executor best practices
- [asyncio Blocking Tasks - Super Fast Python](https://superfastpython.com/asyncio-blocking-tasks/) - ThreadPoolExecutor usage with asyncio

### Tertiary (LOW confidence)
- WebSearch results on python-on-whales 2026 updates - Library remains actively maintained
- WebSearch results on Docker container dependencies - General patterns, not definitive guidance
- WebSearch results on ThreadPoolExecutor sizing - Community recommendations vary

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - python-on-whales already installed, well-documented, stable API
- Architecture: HIGH - asyncio.run_in_executor pattern well-established, matches existing keyboard.py usage
- Pitfalls: HIGH - Based on official docs warnings, GitHub issues, and Docker community experience

**Research date:** 2026-01-27
**Valid until:** 2026-04-27 (90 days - python-on-whales stable, Docker CLI evolves slowly)
