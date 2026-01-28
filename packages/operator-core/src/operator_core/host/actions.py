"""Host action executor for systemd service management.

Provides async wrappers for systemctl commands (start/stop/restart).
All methods use asyncio.create_subprocess_exec to prevent command injection.
Per HOST-07: Never use shell=True.
"""

import asyncio
from typing import Any

from operator_core.host.validation import ServiceWhitelist


class HostActionExecutor:
    """Executor for host-level systemd service operations.

    Implements async wrappers for start, stop, restart operations.
    All operations use asyncio.create_subprocess_exec with array arguments
    to prevent command injection.

    Note:
        These methods require systemd and will work on Linux systems.
        On macOS (development), commands will fail gracefully with appropriate errors.
        Tests mock subprocess calls for cross-platform compatibility.
    """

    def __init__(self, service_whitelist: set[str] | None = None):
        """Initialize executor with service whitelist.

        Args:
            service_whitelist: Allowed service names, or None for default whitelist
        """
        self._whitelist = ServiceWhitelist(service_whitelist)

    async def start_service(self, service_name: str) -> dict[str, Any]:
        """Start a systemd service.

        Args:
            service_name: Service name (e.g., 'nginx', 'redis-server')

        Returns:
            Dict with service_name, command, returncode, active, success, stdout, stderr

        Raises:
            ValueError: If service not in whitelist or invalid service name

        Note:
            Per HOST-01: Start a systemd service via asyncio.create_subprocess_exec.
            Per HOST-06: Validates service name against whitelist before execution.
            Per HOST-07: Uses create_subprocess_exec with array args (never shell=True).
        """
        # Validate service name for security (path traversal prevention)
        self._whitelist.validate_service_name(service_name)

        # Validate against whitelist (HOST-06)
        if not self._whitelist.is_allowed(service_name):
            raise ValueError(f"Service '{service_name}' not in whitelist")

        # Execute systemctl start (HOST-07: array args, no shell)
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "start",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()
        returncode = proc.returncode

        # Verify service actually started (systemctl start has minimal output)
        is_active = await self._check_service_active(service_name)

        return {
            "service_name": service_name,
            "command": "start",
            "returncode": returncode,
            "active": is_active,
            "success": returncode == 0 and is_active,
            "stdout": stdout.decode("utf-8").strip(),
            "stderr": stderr.decode("utf-8").strip(),
        }

    async def stop_service(self, service_name: str) -> dict[str, Any]:
        """Stop a systemd service.

        Args:
            service_name: Service name to stop

        Returns:
            Dict with service_name, command, returncode, active, success, stdout, stderr

        Raises:
            ValueError: If service not in whitelist or invalid service name

        Note:
            Per HOST-02: Stop a systemd service with validation.
            Per HOST-06: Validates service name against whitelist before execution.
            Per HOST-07: Uses create_subprocess_exec with array args (never shell=True).
        """
        # Validate service name for security (path traversal prevention)
        self._whitelist.validate_service_name(service_name)

        # Validate against whitelist
        if not self._whitelist.is_allowed(service_name):
            raise ValueError(f"Service '{service_name}' not in whitelist")

        # Execute systemctl stop
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "stop",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()
        returncode = proc.returncode

        # Verify service actually stopped
        is_active = await self._check_service_active(service_name)

        return {
            "service_name": service_name,
            "command": "stop",
            "returncode": returncode,
            "active": is_active,
            "success": returncode == 0 and not is_active,
            "stdout": stdout.decode("utf-8").strip(),
            "stderr": stderr.decode("utf-8").strip(),
        }

    async def restart_service(self, service_name: str) -> dict[str, Any]:
        """Restart a systemd service (stop then start).

        Args:
            service_name: Service name to restart

        Returns:
            Dict with service_name, command, returncode, active, success, stdout, stderr

        Raises:
            ValueError: If service not in whitelist or invalid service name

        Note:
            Per HOST-03: Restart a systemd service.
            Per HOST-06: Validates service name against whitelist before execution.
            Per HOST-07: Uses create_subprocess_exec with array args (never shell=True).
        """
        # Validate service name for security (path traversal prevention)
        self._whitelist.validate_service_name(service_name)

        # Validate against whitelist
        if not self._whitelist.is_allowed(service_name):
            raise ValueError(f"Service '{service_name}' not in whitelist")

        # Execute systemctl restart
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "restart",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()
        returncode = proc.returncode

        # Verify service is active after restart
        is_active = await self._check_service_active(service_name)

        return {
            "service_name": service_name,
            "command": "restart",
            "returncode": returncode,
            "active": is_active,
            "success": returncode == 0 and is_active,
            "stdout": stdout.decode("utf-8").strip(),
            "stderr": stderr.decode("utf-8").strip(),
        }

    async def _check_service_active(self, service_name: str) -> bool:
        """Check if service is active using systemctl is-active.

        Args:
            service_name: Service name to check

        Returns:
            True if service is active, False otherwise
        """
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await proc.communicate()
        # is-active returns "active" on stdout if service is running
        return stdout.decode("utf-8").strip() == "active"
