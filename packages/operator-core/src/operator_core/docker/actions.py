"""Docker action executor for container lifecycle operations.

Provides async wrappers around python-on-whales for non-blocking Docker operations.
All methods use asyncio.run_in_executor to avoid blocking the event loop.
"""

import asyncio
from typing import Any

from python_on_whales import docker
from python_on_whales.exceptions import NoSuchContainer, NoSuchNetwork

from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType

# Maximum number of log lines to retrieve (prevent memory exhaustion)
MAX_TAIL = 10000


class DockerActionExecutor:
    """Executor for Docker container lifecycle operations.

    Implements async wrappers for start, stop, restart, and inspect operations.
    All operations are idempotent and use run_in_executor for non-blocking execution.
    """

    def __init__(self):
        """Initialize executor with python-on-whales docker client."""
        self._docker = docker

    async def start_container(self, container_id: str) -> dict[str, Any]:
        """Start a stopped container.

        Args:
            container_id: Container ID or name to start

        Returns:
            Dict with container_id, name, state, and running status

        Raises:
            NoSuchContainer: If container doesn't exist

        Note:
            Operation is idempotent - starting an already running container succeeds.
        """
        loop = asyncio.get_running_loop()

        def _blocking_start():
            # Check current state first for idempotent behavior
            container = self._docker.container.inspect(container_id)

            # Only start if not already running
            if not container.state.running:
                self._docker.container.start(container_id)
                # Re-inspect to get updated state
                container = self._docker.container.inspect(container_id)

            return {
                "container_id": container.id,
                "name": container.name,
                "state": container.state.status,
                "running": container.state.running,
            }

        return await loop.run_in_executor(None, _blocking_start)

    async def stop_container(
        self, container_id: str, timeout: int = 10
    ) -> dict[str, Any]:
        """Stop a running container with graceful shutdown.

        Args:
            container_id: Container ID or name to stop
            timeout: Seconds to wait for graceful shutdown before SIGKILL (default: 10)

        Returns:
            Dict with container_id, name, state, exit_code, graceful_shutdown, and killed status

        Raises:
            NoSuchContainer: If container doesn't exist

        Note:
            Operation is idempotent - stopping an already stopped container succeeds.
            Exit code 143 indicates graceful shutdown (SIGTERM).
            Exit code 137 indicates force killed (SIGKILL or OOM).
        """
        loop = asyncio.get_running_loop()

        def _blocking_stop():
            # Check current state first for idempotent behavior
            container = self._docker.container.inspect(container_id)

            # Only stop if currently running
            if container.state.running:
                self._docker.container.stop(container_id, time=timeout)
                # Re-inspect to get updated state
                container = self._docker.container.inspect(container_id)

            exit_code = container.state.exit_code or 0

            return {
                "container_id": container.id,
                "name": container.name,
                "state": container.state.status,
                "exit_code": exit_code,
                "graceful_shutdown": exit_code == 143,
                "killed": exit_code == 137,
            }

        return await loop.run_in_executor(None, _blocking_stop)

    async def restart_container(
        self, container_id: str, timeout: int = 10
    ) -> dict[str, Any]:
        """Restart a container (stop then start).

        Args:
            container_id: Container ID or name to restart
            timeout: Seconds to wait for graceful shutdown before SIGKILL (default: 10)

        Returns:
            Dict with container_id, name, state, and running status

        Raises:
            NoSuchContainer: If container doesn't exist
        """
        loop = asyncio.get_running_loop()

        def _blocking_restart():
            # Use native restart which handles stop + start atomically
            self._docker.container.restart(container_id, time=timeout)

            # Inspect to get updated state
            container = self._docker.container.inspect(container_id)

            return {
                "container_id": container.id,
                "name": container.name,
                "state": container.state.status,
                "running": container.state.running,
            }

        return await loop.run_in_executor(None, _blocking_restart)

    async def inspect_container(self, container_id: str) -> dict[str, Any]:
        """Inspect container status without modification.

        Args:
            container_id: Container ID or name to inspect

        Returns:
            Dict with id, name, image, state (status, running, paused, exit_code, started_at),
            and networks list

        Raises:
            NoSuchContainer: If container doesn't exist

        Note:
            Read-only operation - does not modify container state.
        """
        loop = asyncio.get_running_loop()

        def _blocking_inspect():
            container = self._docker.container.inspect(container_id)

            # Handle optional datetime fields
            started_at = None
            if container.state.started_at:
                started_at = container.state.started_at.isoformat()

            # Extract network names
            networks = list(container.network_settings.networks.keys())

            return {
                "id": container.id,
                "name": container.name,
                "image": container.config.image,
                "state": {
                    "status": container.state.status,
                    "running": container.state.running,
                    "paused": container.state.paused,
                    "exit_code": container.state.exit_code or 0,
                    "started_at": started_at,
                },
                "networks": networks,
            }

        return await loop.run_in_executor(None, _blocking_inspect)

    async def get_container_logs(
        self,
        container_id: str,
        tail: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve logs from a container.

        Args:
            container_id: Container ID or name to get logs from
            tail: Number of lines to retrieve (default: 100, max: 10000)
            since: Only return logs since this time (ISO format or relative)

        Returns:
            Dict with container_id, logs (string), line_count, tail_limit, and truncated (bool)

        Raises:
            NoSuchContainer: If container doesn't exist

        Note:
            Tail limit is silently capped at MAX_TAIL (10000) to prevent memory exhaustion.
            Never uses follow=True (would block indefinitely).
            Always includes timestamps for debugging.
        """
        loop = asyncio.get_running_loop()

        def _blocking_get_logs():
            # Default tail to 100, cap at MAX_TAIL
            effective_tail = tail if tail is not None else 100
            if effective_tail > MAX_TAIL:
                effective_tail = MAX_TAIL

            # Get logs with timestamps, never follow
            logs = self._docker.container.logs(
                container_id,
                tail=effective_tail,
                since=since,
                timestamps=True,
                follow=False,
            )

            # Count lines in logs
            line_count = len(logs.splitlines()) if logs else 0

            return {
                "container_id": container_id,
                "logs": logs,
                "line_count": line_count,
                "tail_limit": effective_tail,
                "truncated": tail is not None and tail > MAX_TAIL,
            }

        return await loop.run_in_executor(None, _blocking_get_logs)

    async def connect_container_to_network(
        self,
        container_id: str,
        network: str,
        alias: str | None = None,
    ) -> dict[str, Any]:
        """Connect a container to a Docker network.

        Args:
            container_id: Container ID or name to connect
            network: Network name or ID to connect to
            alias: Optional network alias for the container

        Returns:
            Dict with container_id, network, alias, and connected=True

        Raises:
            NoSuchContainer: If container doesn't exist
            ValueError: If network doesn't exist
        """
        loop = asyncio.get_running_loop()

        def _blocking_connect():
            # Validate container exists (provides better error message)
            self._docker.container.inspect(container_id)

            # Validate network exists
            if not self._docker.network.exists(network):
                raise ValueError(f"Network '{network}' not found")

            # Connect container to network
            self._docker.network.connect(
                network,
                container_id,
                alias=alias,
            )

            return {
                "container_id": container_id,
                "network": network,
                "alias": alias,
                "connected": True,
            }

        return await loop.run_in_executor(None, _blocking_connect)

    async def disconnect_container_from_network(
        self,
        container_id: str,
        network: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Disconnect a container from a Docker network.

        Args:
            container_id: Container ID or name to disconnect
            network: Network name or ID to disconnect from
            force: Force disconnection even if container is running

        Returns:
            Dict with container_id, network, and disconnected=True

        Raises:
            NoSuchContainer: If container doesn't exist
        """
        loop = asyncio.get_running_loop()

        def _blocking_disconnect():
            # Disconnect container from network
            self._docker.network.disconnect(
                network,
                container_id,
                force=force,
            )

            return {
                "container_id": container_id,
                "network": network,
                "disconnected": True,
            }

        return await loop.run_in_executor(None, _blocking_disconnect)

    async def execute_command(
        self,
        container_id: str,
        command: list[str],
        user: str | None = None,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        """Execute a command inside a running container.

        Args:
            container_id: Container ID or name to execute in
            command: Command to execute as list of strings
            user: User to run command as (default: container's default user)
            workdir: Working directory for command (default: container's workdir)

        Returns:
            Dict with container_id, command, success (bool), output (str), error (str or None)

        Raises:
            NoSuchContainer: If container doesn't exist

        Note:
            Runs with tty=False, interactive=False for programmatic access.
            Errors are captured in the error field, not raised as exceptions.
        """
        loop = asyncio.get_running_loop()

        def _blocking_execute():
            try:
                output = self._docker.container.execute(
                    container_id,
                    command,
                    user=user,
                    workdir=workdir,
                    tty=False,
                    interactive=False,
                )

                return {
                    "container_id": container_id,
                    "command": command,
                    "success": True,
                    "output": output,
                    "error": None,
                }
            except Exception as e:
                return {
                    "container_id": container_id,
                    "command": command,
                    "success": False,
                    "output": "",
                    "error": str(e),
                }

        return await loop.run_in_executor(None, _blocking_execute)


def get_docker_tools() -> list[ActionDefinition]:
    """
    Get Docker action tool definitions.

    Returns list of ActionDefinition for all Docker container operations.
    Per DOCK-10: All Docker actions register as ActionType.TOOL.
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
            requires_approval=True,
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
                    description="Seconds to wait for graceful shutdown before SIGKILL (default: 10)",
                    required=False,
                    default=10,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
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
                    description="Seconds to wait for graceful shutdown before SIGKILL (default: 10)",
                    required=False,
                    default=10,
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
                    description="Container ID or name to get logs from",
                    required=True,
                ),
                "tail": ParamDef(
                    type="int",
                    description="Number of lines to retrieve (default: 100, max: 10000)",
                    required=False,
                ),
                "since": ParamDef(
                    type="str",
                    description="Only return logs since this time (ISO format or relative)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="low",
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
            risk_level="low",
            requires_approval=False,
        ),
        ActionDefinition(
            name="docker_network_connect",
            description="Connect container to a Docker network",
            parameters={
                "container_id": ParamDef(
                    type="str",
                    description="Container ID or name to connect",
                    required=True,
                ),
                "network": ParamDef(
                    type="str",
                    description="Network name or ID to connect to",
                    required=True,
                ),
                "alias": ParamDef(
                    type="str",
                    description="Optional network alias for the container",
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
                    description="Container ID or name to disconnect",
                    required=True,
                ),
                "network": ParamDef(
                    type="str",
                    description="Network name or ID to disconnect from",
                    required=True,
                ),
                "force": ParamDef(
                    type="bool",
                    description="Force disconnection even if container is running",
                    required=False,
                    default=False,
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
                    description="Container ID or name to execute in",
                    required=True,
                ),
                "command": ParamDef(
                    type="list",
                    description="Command to execute as list of strings",
                    required=True,
                ),
                "user": ParamDef(
                    type="str",
                    description="User to run command as (default: container's default user)",
                    required=False,
                ),
                "workdir": ParamDef(
                    type="str",
                    description="Working directory for command (default: container's workdir)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",
            requires_approval=True,
        ),
    ]
