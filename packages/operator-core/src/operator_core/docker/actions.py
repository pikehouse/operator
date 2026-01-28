"""Docker action executor for container lifecycle operations.

Provides async wrappers around python-on-whales for non-blocking Docker operations.
All methods use asyncio.run_in_executor to avoid blocking the event loop.
"""

import asyncio
from typing import Any

from python_on_whales import docker
from python_on_whales.exceptions import NoSuchContainer


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
