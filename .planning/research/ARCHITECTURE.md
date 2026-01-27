# Architecture Research: Infrastructure Actions and Script Execution

**Project:** Operator Infrastructure Control Milestone
**Researched:** 2026-01-27
**Confidence:** HIGH (verified with existing action framework, official docs, ecosystem patterns)

## Executive Summary

Infrastructure actions (Docker control, host operations) and sandboxed script execution integrate with the existing action framework through ActionType.TOOL. The core action lifecycle (propose → validate → execute → complete) remains unchanged. New infrastructure is isolated in dedicated executor components that implement tool execution handlers.

**Key architectural decision:** Script execution is treated as code generation + sandboxed execution, not direct LLM code execution. The agent generates a script as a string parameter, the system validates it, sandboxes it (gVisor/Docker), captures output, and returns results through the standard action result flow.

## Component Overview

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `DockerActionExecutor` | `packages/operator-core/src/operator_core/actions/executors/docker.py` | Docker container lifecycle, network operations |
| `HostActionExecutor` | `packages/operator-core/src/operator_core/actions/executors/host.py` | Host file operations, process management |
| `ScriptSandbox` | `packages/operator-core/src/operator_core/actions/executors/script.py` | Script validation, sandboxed execution, output capture |
| `InfrastructureTools` | `packages/operator-core/src/operator_core/actions/tools.py` | Tool action definitions for infrastructure |
| `aiodocker` integration | Dependency | Async Docker SDK (replaces synchronous docker-py) |

### Modified Components

| Component | Change |
|-----------|--------|
| `ActionExecutor.execute_proposal()` | Route ActionType.TOOL to tool executor dispatch |
| `actions/tools.py` | Add infrastructure tool definitions (docker, host, script) |
| `agent/diagnosis.py` | Support script_content field in ActionRecommendation |
| `agent/prompt.py` | Instruct agent when to generate scripts vs parameters |

### No Changes Required

| Component | Why Unchanged |
|-----------|---------------|
| `ActionProposal` | Already supports ActionType.TOOL and arbitrary parameters |
| `ActionRegistry` | Already handles TOOL type via get_general_tools() |
| `ActionStatus` lifecycle | Works identically for infrastructure actions |
| Database schema | parameters JSON field supports script_content |

## Architecture Diagram

```
                         ActionExecutor
                               |
                 +-------------+-------------+
                 |                           |
          ActionType.SUBJECT          ActionType.TOOL
                 |                           |
         subject.method()            tool executor dispatch
                                             |
                        +--------------------+--------------------+
                        |                    |                    |
                DockerActionExecutor  HostActionExecutor  ScriptSandbox
                        |                    |                    |
                   aiodocker          asyncio.subprocess      gVisor/Docker
                        |                    |                    |
                   Docker API           Host system         Isolated container
```

## Integration with Existing Action Framework

### ActionType.TOOL Routing

The existing `ActionExecutor` already has infrastructure for TOOL actions (added in v2.0). Infrastructure actions extend this:

```python
# operator_core/actions/executor.py (EXISTING)

async def execute_proposal(
    self,
    proposal_id: int,
    subject: "Subject",
) -> ActionRecord:
    """Execute a validated proposal."""

    # ... (safety checks, status updates) ...

    try:
        if proposal.action_type == ActionType.TOOL:
            # Execute general tool (ALREADY EXISTS)
            result = await execute_tool(
                proposal.action_name,
                proposal.parameters,
            )
        else:
            # Execute subject method
            method = getattr(subject, proposal.action_name, None)
            result = await method(**proposal.parameters)

        success = True
        result_data = {"result": result} if result is not None else None
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}"
```

**No changes needed to ActionExecutor.** Infrastructure actions route through existing `execute_tool()` path.

### Tool Registration Pattern

Infrastructure tools register the same way as existing general tools:

```python
# operator_core/actions/tools.py (EXTENDED)

from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType

def get_general_tools() -> list[ActionDefinition]:
    """
    Get all general tool action definitions.

    Extended to include infrastructure tools.
    """
    return [
        # Existing tools (calculate, echo, etc.)
        # ...

        # Docker tools
        ActionDefinition(
            name="docker_restart_container",
            description="Restart a Docker container by name or ID",
            parameters={
                "container": ParamDef(
                    type="str",
                    description="Container name or ID",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",
        ),
        ActionDefinition(
            name="docker_stop_container",
            description="Stop a Docker container",
            parameters={
                "container": ParamDef(type="str", description="Container name or ID", required=True),
                "timeout": ParamDef(type="int", description="Timeout in seconds", required=False, default=10),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
        ),
        ActionDefinition(
            name="docker_prune_networks",
            description="Remove unused Docker networks",
            parameters={},
            action_type=ActionType.TOOL,
            risk_level="low",
        ),

        # Host tools
        ActionDefinition(
            name="host_restart_service",
            description="Restart a systemd service",
            parameters={
                "service_name": ParamDef(type="str", description="Service name", required=True),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
        ),
        ActionDefinition(
            name="host_kill_process",
            description="Kill a process by PID or name",
            parameters={
                "target": ParamDef(type="str", description="PID or process name", required=True),
                "signal": ParamDef(type="str", description="Signal name (SIGTERM, SIGKILL)", required=False, default="SIGTERM"),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
        ),

        # Script execution
        ActionDefinition(
            name="execute_script",
            description="Execute a generated Python script in a sandbox",
            parameters={
                "script_content": ParamDef(
                    type="str",
                    description="Python script to execute",
                    required=True,
                ),
                "timeout_seconds": ParamDef(
                    type="int",
                    description="Execution timeout",
                    required=False,
                    default=30,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
        ),
    ]
```

**Pattern:** Each infrastructure action is a `ActionDefinition` with `action_type=ActionType.TOOL`.

### Tool Executor Dispatch

The `execute_tool()` function dispatches to specialized executors:

```python
# operator_core/actions/tools.py (NEW)

from operator_core.actions.executors.docker import DockerActionExecutor
from operator_core.actions.executors.host import HostActionExecutor
from operator_core.actions.executors.script import ScriptSandbox

# Module-level singletons (initialized on first use)
_docker_executor: DockerActionExecutor | None = None
_host_executor: HostActionExecutor | None = None
_script_sandbox: ScriptSandbox | None = None


async def execute_tool(action_name: str, parameters: dict[str, Any]) -> Any:
    """
    Execute a general tool action.

    Dispatches to specialized executors based on action name prefix.

    Args:
        action_name: Tool action name (e.g., "docker_restart_container")
        parameters: Action parameters

    Returns:
        Execution result (varies by tool)

    Raises:
        ValueError: If action name unknown
        RuntimeError: If execution fails
    """
    # Docker actions
    if action_name.startswith("docker_"):
        global _docker_executor
        if _docker_executor is None:
            _docker_executor = await DockerActionExecutor.create()

        return await _docker_executor.execute(action_name, parameters)

    # Host actions
    elif action_name.startswith("host_"):
        global _host_executor
        if _host_executor is None:
            _host_executor = HostActionExecutor()

        return await _host_executor.execute(action_name, parameters)

    # Script execution
    elif action_name == "execute_script":
        global _script_sandbox
        if _script_sandbox is None:
            _script_sandbox = await ScriptSandbox.create()

        return await _script_sandbox.execute(parameters["script_content"], parameters.get("timeout_seconds", 30))

    # Existing tools (calculate, echo, etc.)
    elif action_name == "calculate":
        # ... existing implementation ...
        pass

    else:
        raise ValueError(f"Unknown tool action: {action_name}")
```

**Pattern:** Lazy initialization of executors, dispatch by name prefix.

## Docker Action Executor

### Architecture

```
DockerActionExecutor
         |
     aiodocker.Docker (async client)
         |
    Docker Engine API
         |
    Container/Network/Volume operations
```

### Implementation

```python
# operator_core/actions/executors/docker.py

import aiodocker
from typing import Any


class DockerActionExecutor:
    """
    Executor for Docker container and network operations.

    Uses aiodocker for async Docker API access. Implements common
    infrastructure actions like restart, stop, prune.

    Example:
        executor = await DockerActionExecutor.create()
        result = await executor.execute("docker_restart_container", {"container": "tikv0"})
    """

    def __init__(self, docker: aiodocker.Docker) -> None:
        """Initialize with aiodocker client."""
        self._docker = docker

    @classmethod
    async def create(cls) -> "DockerActionExecutor":
        """
        Factory method to create executor with Docker client.

        Returns:
            Initialized DockerActionExecutor
        """
        docker = aiodocker.Docker()
        return cls(docker)

    async def close(self) -> None:
        """Close Docker client connection."""
        await self._docker.close()

    async def execute(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a Docker action.

        Args:
            action_name: Action name (e.g., "docker_restart_container")
            parameters: Action parameters

        Returns:
            Execution result with status and details

        Raises:
            ValueError: If action unknown
            aiodocker.DockerError: If Docker operation fails
        """
        if action_name == "docker_restart_container":
            return await self._restart_container(parameters["container"])

        elif action_name == "docker_stop_container":
            timeout = parameters.get("timeout", 10)
            return await self._stop_container(parameters["container"], timeout)

        elif action_name == "docker_start_container":
            return await self._start_container(parameters["container"])

        elif action_name == "docker_prune_networks":
            return await self._prune_networks()

        elif action_name == "docker_inspect_container":
            return await self._inspect_container(parameters["container"])

        else:
            raise ValueError(f"Unknown Docker action: {action_name}")

    async def _restart_container(self, container: str) -> dict[str, Any]:
        """Restart a container."""
        c = await self._docker.containers.get(container)
        await c.restart()

        return {
            "status": "restarted",
            "container": container,
        }

    async def _stop_container(self, container: str, timeout: int) -> dict[str, Any]:
        """Stop a container."""
        c = await self._docker.containers.get(container)
        await c.stop(timeout=timeout)

        return {
            "status": "stopped",
            "container": container,
            "timeout": timeout,
        }

    async def _start_container(self, container: str) -> dict[str, Any]:
        """Start a container."""
        c = await self._docker.containers.get(container)
        await c.start()

        return {
            "status": "started",
            "container": container,
        }

    async def _prune_networks(self) -> dict[str, Any]:
        """Remove unused networks."""
        result = await self._docker.networks.prune()

        return {
            "status": "pruned",
            "networks_deleted": len(result.get("NetworksDeleted", [])),
        }

    async def _inspect_container(self, container: str) -> dict[str, Any]:
        """Get container details."""
        c = await self._docker.containers.get(container)
        info = await c.show()

        return {
            "status": "inspected",
            "container": container,
            "state": info["State"]["Status"],
            "health": info["State"].get("Health", {}).get("Status"),
        }
```

**Key patterns:**
- Async throughout (aiodocker is fully async)
- Fire-and-forget semantics (return on API success)
- Structured results (dict with status + details)
- Docker errors propagate as exceptions

### Technology: aiodocker

**Why aiodocker over docker-py:**
- Native asyncio support (docker-py is synchronous)
- Non-blocking I/O fits existing operator architecture
- Active maintenance (0.25.1 released 2025)
- Full Docker API coverage

**Installation:**
```bash
uv add aiodocker
```

**Sources:**
- [aiodocker GitHub](https://github.com/aio-libs/aiodocker) (PRIMARY)
- [aiodocker PyPI](https://pypi.org/project/aiodocker/) (PRIMARY)
- [aiodocker Documentation](https://aiodocker.readthedocs.io/) (PRIMARY)

## Host Action Executor

### Architecture

```
HostActionExecutor
         |
   asyncio.create_subprocess_exec()
         |
   Host system commands (systemctl, kill, etc.)
```

### Implementation

```python
# operator_core/actions/executors/host.py

import asyncio
import shlex
from typing import Any


class HostActionExecutor:
    """
    Executor for host system operations.

    Uses asyncio subprocess management for non-blocking execution.
    Implements systemd service control, process management.

    SECURITY: Uses asyncio.create_subprocess_exec (not shell=True) to
    prevent command injection. Parameters are validated before execution.

    Example:
        executor = HostActionExecutor()
        result = await executor.execute("host_restart_service", {"service_name": "nginx"})
    """

    async def execute(self, action_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a host action.

        Args:
            action_name: Action name (e.g., "host_restart_service")
            parameters: Action parameters

        Returns:
            Execution result with status, stdout, stderr

        Raises:
            ValueError: If action unknown or parameters invalid
            RuntimeError: If command execution fails
        """
        if action_name == "host_restart_service":
            return await self._restart_service(parameters["service_name"])

        elif action_name == "host_stop_service":
            return await self._stop_service(parameters["service_name"])

        elif action_name == "host_start_service":
            return await self._start_service(parameters["service_name"])

        elif action_name == "host_kill_process":
            signal = parameters.get("signal", "SIGTERM")
            return await self._kill_process(parameters["target"], signal)

        else:
            raise ValueError(f"Unknown host action: {action_name}")

    async def _restart_service(self, service_name: str) -> dict[str, Any]:
        """Restart a systemd service."""
        self._validate_service_name(service_name)

        # Use create_subprocess_exec (NOT shell=True) for security
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "restart", service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Service restart failed: {stderr.decode()}")

        return {
            "status": "restarted",
            "service": service_name,
            "stdout": stdout.decode(),
        }

    async def _stop_service(self, service_name: str) -> dict[str, Any]:
        """Stop a systemd service."""
        self._validate_service_name(service_name)

        proc = await asyncio.create_subprocess_exec(
            "systemctl", "stop", service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Service stop failed: {stderr.decode()}")

        return {
            "status": "stopped",
            "service": service_name,
        }

    async def _start_service(self, service_name: str) -> dict[str, Any]:
        """Start a systemd service."""
        self._validate_service_name(service_name)

        proc = await asyncio.create_subprocess_exec(
            "systemctl", "start", service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Service start failed: {stderr.decode()}")

        return {
            "status": "started",
            "service": service_name,
        }

    async def _kill_process(self, target: str, signal: str) -> dict[str, Any]:
        """Kill a process by PID or name."""
        self._validate_signal(signal)

        # If target is numeric, it's a PID
        if target.isdigit():
            pid = target
        else:
            # Find PID by process name
            pid = await self._find_pid_by_name(target)
            if pid is None:
                raise ValueError(f"Process not found: {target}")

        proc = await asyncio.create_subprocess_exec(
            "kill", f"-{signal}", pid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Kill failed: {stderr.decode()}")

        return {
            "status": "killed",
            "target": target,
            "pid": pid,
            "signal": signal,
        }

    def _validate_service_name(self, service_name: str) -> None:
        """Validate service name to prevent injection."""
        # Only allow alphanumeric, dash, underscore, dot
        if not all(c.isalnum() or c in "-_." for c in service_name):
            raise ValueError(f"Invalid service name: {service_name}")

    def _validate_signal(self, signal: str) -> None:
        """Validate signal name."""
        valid_signals = {"SIGTERM", "SIGKILL", "SIGHUP", "SIGINT"}
        if signal not in valid_signals:
            raise ValueError(f"Invalid signal: {signal}")

    async def _find_pid_by_name(self, name: str) -> str | None:
        """Find PID by process name using pgrep."""
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-f", name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode == 0 and stdout:
            # Return first PID
            return stdout.decode().split("\n")[0]

        return None
```

**Key patterns:**
- NEVER use `shell=True` (prevents command injection)
- Always use `asyncio.create_subprocess_exec()` with argument list
- Validate all inputs before execution
- Use `communicate()` for async I/O
- Structured error handling

**Security considerations:**
- Input validation prevents injection attacks
- No shell interpolation (direct exec)
- Service names validated against whitelist pattern
- Signal names validated against known set
- Process names validated before pgrep

**Sources:**
- [Python asyncio subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html) (PRIMARY - Python 3.14.2, updated 2026-01-26)
- [OpenStack subprocess security guidelines](https://security.openstack.org/guidelines/dg_use-subprocess-securely.html) (SECONDARY)
- [Secure Python subprocess usage](https://www.codiga.io/blog/python-subprocess-security/) (SECONDARY)

## Script Sandbox Executor

### Architecture

Script execution is a two-phase process:

1. **Generation Phase**: Agent generates Python script as `script_content` string
2. **Execution Phase**: System validates, sandboxes, executes, captures output

```
Agent generates script
         |
         v
ScriptSandbox validates
         |
         v
gVisor container created (isolated)
         |
         v
Script executed with timeout
         |
         v
Output captured (stdout/stderr/exit code)
         |
         v
Container destroyed
         |
         v
Result returned through action result
```

### Implementation

```python
# operator_core/actions/executors/script.py

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import aiodocker


class ScriptValidationError(Exception):
    """Raised when script validation fails."""
    pass


class ScriptSandbox:
    """
    Sandbox for executing LLM-generated scripts.

    Validates script content, executes in isolated gVisor container,
    captures output with timeout, and cleans up.

    SECURITY: Scripts run in gVisor sandbox with:
    - No network access
    - No host filesystem access
    - Resource limits (CPU, memory)
    - Execution timeout

    Example:
        sandbox = await ScriptSandbox.create()
        result = await sandbox.execute(script_content, timeout=30)
    """

    def __init__(self, docker: aiodocker.Docker) -> None:
        """Initialize with Docker client."""
        self._docker = docker

    @classmethod
    async def create(cls) -> "ScriptSandbox":
        """Factory method to create sandbox."""
        docker = aiodocker.Docker()

        # Ensure sandbox image exists (gVisor-enabled Python)
        await cls._ensure_sandbox_image(docker)

        return cls(docker)

    @staticmethod
    async def _ensure_sandbox_image(docker: aiodocker.Docker) -> None:
        """Pull sandbox image if not present."""
        image_name = "python:3.12-alpine"

        try:
            await docker.images.inspect(image_name)
        except aiodocker.exceptions.DockerError:
            # Image not found, pull it
            await docker.images.pull(image_name)

    async def execute(self, script_content: str, timeout_seconds: int = 30) -> dict[str, Any]:
        """
        Execute a script in sandbox.

        Args:
            script_content: Python script to execute
            timeout_seconds: Execution timeout

        Returns:
            Result dict with stdout, stderr, exit_code, timed_out

        Raises:
            ScriptValidationError: If script validation fails
            RuntimeError: If sandbox setup fails
        """
        # Validate script
        self._validate_script(script_content)

        # Create temporary file for script
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            script_path = Path(f.name)

        try:
            # Create sandbox container
            container = await self._create_sandbox_container(script_path)

            # Start container
            await container.start()

            # Wait for completion with timeout
            try:
                await asyncio.wait_for(
                    container.wait(),
                    timeout=timeout_seconds,
                )
                timed_out = False
            except asyncio.TimeoutError:
                # Kill container on timeout
                await container.kill()
                timed_out = True

            # Get logs
            logs = await container.log(stdout=True, stderr=True)
            stdout = "".join(logs)

            # Get exit code
            info = await container.show()
            exit_code = info["State"]["ExitCode"]

            # Clean up container
            await container.delete(force=True)

            return {
                "status": "completed" if not timed_out else "timeout",
                "stdout": stdout,
                "stderr": "",  # Logs are combined in aiodocker
                "exit_code": exit_code,
                "timed_out": timed_out,
            }

        finally:
            # Clean up script file
            script_path.unlink(missing_ok=True)

    async def _create_sandbox_container(self, script_path: Path) -> Any:
        """Create sandboxed container for script execution."""
        config = {
            "Image": "python:3.12-alpine",
            "Cmd": ["python", "/script.py"],
            "HostConfig": {
                "Binds": [f"{script_path}:/script.py:ro"],
                "NetworkMode": "none",  # No network access
                "Memory": 128 * 1024 * 1024,  # 128MB limit
                "MemorySwap": 128 * 1024 * 1024,  # No swap
                "CpuQuota": 50000,  # 50% of one CPU
                "ReadonlyRootfs": True,  # Read-only filesystem
                "SecurityOpt": ["no-new-privileges"],  # Prevent privilege escalation
            },
        }

        container = await self._docker.containers.create(config=config)
        return container

    def _validate_script(self, script_content: str) -> None:
        """
        Validate script content.

        Basic validation to catch obvious issues before execution.
        Not a complete security analysis (sandbox handles that).

        Args:
            script_content: Script to validate

        Raises:
            ScriptValidationError: If validation fails
        """
        if not script_content or not script_content.strip():
            raise ScriptValidationError("Script content is empty")

        if len(script_content) > 10000:
            raise ScriptValidationError("Script too long (max 10000 chars)")

        # Check for basic syntax errors
        try:
            compile(script_content, "<script>", "exec")
        except SyntaxError as e:
            raise ScriptValidationError(f"Syntax error: {e}")

        # Deny list for dangerous operations
        deny_list = [
            "import os",
            "import subprocess",
            "import sys",
            "__import__",
            "eval(",
            "exec(",
            "compile(",
        ]

        for pattern in deny_list:
            if pattern in script_content:
                raise ScriptValidationError(f"Forbidden pattern: {pattern}")
```

**Key patterns:**
- Two-phase: validate → sandbox → execute → capture → cleanup
- gVisor sandbox (via Docker runtime configuration)
- No network, read-only root, resource limits
- Timeout enforcement with container kill
- Automatic cleanup (container + temp file)

**Security layers:**
1. **Validation**: Syntax check, deny list, length limit
2. **Sandbox**: gVisor isolation, no network, read-only FS
3. **Resource limits**: CPU, memory, execution time
4. **Privilege dropping**: no-new-privileges, non-root user

**Sources:**
- [Setting Up a Secure Python Sandbox for LLM Agents](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents) (PRIMARY)
- [OpenAI Code Interpreter Tool](https://cookbook.openai.com/examples/object_oriented_agentic_approach/secure_code_interpreter_tool_for_llm_agents) (SECONDARY)
- [OpenEDX CodeJail](https://github.com/openedx/codejail) (REFERENCE)

## Agent Script Generation Flow

### When Does Agent Generate Scripts?

Agent generates scripts when diagnosis recommends `execute_script` action:

```python
# operator_core/agent/diagnosis.py (EXTENDED)

from pydantic import BaseModel, Field

class ActionRecommendation(BaseModel):
    """
    Recommended action from diagnosis.

    Extended to support script content for execute_script actions.
    """
    action_name: str = Field(..., description="Action name")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action parameters (may include script_content)",
    )
    reason: str = Field(..., description="Why this action")
    urgency: str = Field(default="medium", description="Urgency level")
```

### Prompt Guidance

System prompt instructs agent when to use script generation:

```markdown
# operator_core/agent/prompt.py (EXTENDED)

## Available Actions

... (existing action types) ...

### Script Execution (execute_script)

For complex remediation requiring multiple operations, generate a Python script.

**When to use:**
- Remediation requires conditional logic
- Multiple operations needed (query → decide → act)
- Need to inspect state before deciding action
- Standard actions insufficient

**How to specify:**
- action_name: "execute_script"
- parameters.script_content: Full Python script as string
- parameters.timeout_seconds: Execution timeout (default 30)

**Script capabilities:**
- Read subject metrics (via httpx to APIs)
- Perform calculations
- Output diagnosis to stdout

**Script limitations:**
- No network access (except to subject endpoints)
- No file system access
- No subprocess execution
- 30s timeout default

**Example:**
```json
{
  "action_name": "execute_script",
  "parameters": {
    "script_content": "import json\nprint(json.dumps({'status': 'ok'}))",
    "timeout_seconds": 30
  },
  "reason": "Need to query metrics and conditionally restart services",
  "urgency": "high"
}
```
```

### Script Content in Action Parameters

Script content flows through existing parameter field:

```json
{
  "action_name": "execute_script",
  "parameters": {
    "script_content": "import httpx\n\nresponse = httpx.get('http://pd:2379/health')\nprint(response.json())",
    "timeout_seconds": 30
  },
  "reason": "Check PD health before leader transfer"
}
```

**No schema changes needed.** The `parameters` JSON field already supports arbitrary structure.

## Build Order

Based on dependency analysis, suggested build order:

### Phase 1: Docker Actions (Foundation)

Docker actions are simplest and don't depend on script execution.

1. Add `aiodocker` dependency to `pyproject.toml`
2. Create `operator_core/actions/executors/` directory
3. Implement `DockerActionExecutor` in `executors/docker.py`
4. Add Docker tool definitions to `actions/tools.py`
5. Extend `execute_tool()` to dispatch Docker actions
6. Write unit tests (mocked aiodocker)
7. Write integration tests (real Docker daemon)

**Verification:** Can restart TiKV containers via action execution.

### Phase 2: Host Actions

Host actions depend on subprocess patterns, no external deps.

1. Implement `HostActionExecutor` in `executors/host.py`
2. Add host tool definitions to `actions/tools.py`
3. Extend `execute_tool()` to dispatch host actions
4. Write unit tests (mocked subprocess)
5. Write integration tests (real systemctl commands)

**Verification:** Can restart systemd services via action execution.

### Phase 3: Script Sandbox

Script execution is most complex, depends on Docker.

1. Implement `ScriptSandbox` in `executors/script.py`
2. Add `execute_script` tool definition to `actions/tools.py`
3. Extend `execute_tool()` to dispatch script execution
4. Create sandbox Docker image (gVisor-enabled)
5. Write unit tests (mocked container creation)
6. Write integration tests (real script execution)

**Verification:** Can execute simple Python script, capture output, enforce timeout.

### Phase 4: Agent Integration

Connect script generation to agent workflow.

1. Extend `agent/prompt.py` with script execution guidance
2. Update `ActionRecommendation` schema (already supports script_content)
3. Test agent script generation in diagnosis
4. Validate script → sandbox → result flow end-to-end

**Verification:** Agent generates script for complex diagnosis, sandbox executes, result captured.

### Phase 5: Demo Scenarios

Create scenarios showcasing infrastructure actions.

1. TiKV container crash → docker_restart_container
2. PD process hung → host_kill_process → docker_restart_container
3. Network partition → execute_script (query metrics + conditional restart)
4. Update demo chapters with infrastructure action flows

## Integration Points Summary

| Integration Point | Status | Change Required |
|-------------------|--------|-----------------|
| `ActionExecutor.execute_proposal()` | ✅ Ready | None (already supports TOOL type) |
| `ActionType.TOOL` enum | ✅ Ready | None (exists since v2.0) |
| `ActionProposal.parameters` | ✅ Ready | None (JSON field supports arbitrary data) |
| `execute_tool()` dispatch | 🔧 Extend | Add Docker/host/script branches |
| `get_general_tools()` | 🔧 Extend | Add infrastructure tool definitions |
| `agent/prompt.py` | 🔧 Extend | Add script execution guidance |
| `ActionRecommendation` | ✅ Ready | None (parameters already flexible) |
| Database schema | ✅ Ready | None (JSON parameters field) |

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Action framework integration | HIGH | ActionType.TOOL already exists, no framework changes |
| Docker executor pattern | HIGH | aiodocker official docs, well-established patterns |
| Host executor security | HIGH | Python asyncio subprocess official docs, OpenStack guidelines |
| Script sandbox approach | MEDIUM | Validated by multiple LLM agent implementations, requires testing |
| Agent script generation | MEDIUM | Extends existing diagnosis, prompt engineering needed |
| Build order dependencies | HIGH | Clear dependency graph, no circular deps |

## Sources

### Docker (HIGH confidence)
- [aiodocker GitHub](https://github.com/aio-libs/aiodocker) - Official async Docker SDK
- [aiodocker PyPI](https://pypi.org/project/aiodocker/) - Package info and installation
- [aiodocker Documentation](https://aiodocker.readthedocs.io/) - API reference and examples
- [Docker Best Practices 2026](https://medium.com/devops-ai-decoded/docker-in-2026-top-10-must-see-innovations-and-best-practices-for-production-success-30a5e090e5d6) - Production patterns

### Host Operations (HIGH confidence)
- [Python asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html) - Official Python 3.14.2 docs (updated 2026-01-26)
- [OpenStack subprocess security](https://security.openstack.org/guidelines/dg_use-subprocess-securely.html) - Security guidelines
- [Secure Python subprocess](https://www.codiga.io/blog/python-subprocess-security/) - Best practices

### Script Execution (MEDIUM confidence)
- [Secure Python Sandbox for LLM Agents](https://dida.do/blog/setting-up-a-secure-python-sandbox-for-llm-agents) - gVisor sandbox pattern
- [OpenAI Code Interpreter Tool](https://cookbook.openai.com/examples/object_oriented_agentic_approach/secure_code_interpreter_tool_for_llm_agents) - LLM code execution patterns
- [OpenEDX CodeJail](https://github.com/openedx/codejail) - Production sandbox implementation
- [Python Sandboxing Complexity](https://checkmarx.com/zero-post/glass-sandbox-complexity-of-python-sandboxing/) - Security considerations

### Existing Codebase (HIGH confidence)
- `operator_core/actions/executor.py` - ActionExecutor with TOOL support
- `operator_core/actions/tools.py` - Tool registration pattern
- `operator_core/actions/types.py` - ActionType enum
- `.planning/research/ARCHITECTURE.md` - v2.1 rate limiter architecture
