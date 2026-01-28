"""Host action executor for systemd service and process management.

Provides async wrappers for systemctl commands (start/stop/restart) and
process signaling (SIGTERM/SIGKILL) with graceful escalation.

All methods use asyncio.create_subprocess_exec to prevent command injection.
Per HOST-07: Never use shell=True.
"""

import asyncio
import os
import signal
from typing import Any

from operator_core.host.validation import ServiceWhitelist, validate_pid


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

    async def kill_process(
        self,
        pid: int,
        signal_type: str = "SIGTERM",
        graceful_timeout: int = 5,
    ) -> dict[str, Any]:
        """Send signal to process with graceful escalation.

        Args:
            pid: Process ID to signal (must be > 1, not kernel thread)
            signal_type: 'SIGTERM' (graceful) or 'SIGKILL' (force). Default: SIGTERM
            graceful_timeout: Seconds to wait before SIGKILL escalation (default: 5)

        Returns:
            Dict with pid, signal, escalated, still_running, success

        Raises:
            ValueError: If PID invalid (<=1, kernel thread)
            ProcessLookupError: If process doesn't exist
            PermissionError: If insufficient privileges

        Note:
            Per HOST-04: kill_process sends SIGTERM or SIGKILL to processes.
            Per HOST-05: SIGTERM -> wait graceful_timeout -> SIGKILL if still running.
            Per HOST-06: Validates PID > 1 and not kernel thread.
        """
        # Validate PID (HOST-06)
        validate_pid(pid)

        # Map signal string to constant
        sig = signal.SIGTERM if signal_type == "SIGTERM" else signal.SIGKILL
        escalated = False

        # Send initial signal
        os.kill(pid, sig)

        # Graceful escalation pattern (HOST-05)
        if signal_type == "SIGTERM" and graceful_timeout > 0:
            # Wait for process to exit gracefully, checking every 100ms
            for _ in range(graceful_timeout * 10):
                await asyncio.sleep(0.1)

                try:
                    os.kill(pid, 0)  # Check if still exists
                except ProcessLookupError:
                    # Process exited gracefully
                    break
            else:
                # Timeout expired, process still running, escalate to SIGKILL
                try:
                    os.kill(pid, signal.SIGKILL)
                    escalated = True
                    await asyncio.sleep(0.5)  # Brief wait for SIGKILL to take effect
                except ProcessLookupError:
                    pass  # Exited just before escalation

        # Check final state
        try:
            os.kill(pid, 0)
            still_running = True
        except ProcessLookupError:
            still_running = False

        return {
            "pid": pid,
            "signal": signal_type,
            "escalated": escalated,
            "still_running": still_running,
            "success": not still_running,
        }


def get_host_tools() -> list["ActionDefinition"]:
    """
    Get host action tool definitions.

    Returns list of ActionDefinition for systemd and process operations.
    All host actions register as ActionType.TOOL for agent discovery.
    """
    from operator_core.actions.registry import ActionDefinition, ParamDef
    from operator_core.actions.types import ActionType

    return [
        ActionDefinition(
            name="host_service_start",
            description="Start a systemd service (requires whitelist authorization)",
            parameters={
                "service_name": ParamDef(
                    type="str",
                    description="Service name (e.g., 'nginx', 'redis-server'). Must be in whitelist.",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",  # State change but recoverable
            requires_approval=True,
        ),
        ActionDefinition(
            name="host_service_stop",
            description="Stop a systemd service gracefully",
            parameters={
                "service_name": ParamDef(
                    type="str",
                    description="Service name to stop. Must be in whitelist.",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",  # Availability impact
            requires_approval=True,
        ),
        ActionDefinition(
            name="host_service_restart",
            description="Restart a systemd service (stop then start)",
            parameters={
                "service_name": ParamDef(
                    type="str",
                    description="Service name to restart. Must be in whitelist.",
                    required=True,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="medium",  # Temporary disruption but recoverable
            requires_approval=True,
        ),
        ActionDefinition(
            name="host_kill_process",
            description="Send signal to process (SIGTERM for graceful, escalates to SIGKILL after 5s if needed)",
            parameters={
                "pid": ParamDef(
                    type="int",
                    description="Process ID to signal (must be >= 300, not kernel thread)",
                    required=True,
                ),
                "signal": ParamDef(
                    type="str",
                    description="Signal type: 'SIGTERM' (default, graceful) or 'SIGKILL' (force)",
                    required=False,
                ),
                "graceful_timeout": ParamDef(
                    type="int",
                    description="Seconds to wait before SIGKILL escalation (default: 5)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="high",  # Process termination impacts availability
            requires_approval=True,
        ),
    ]
