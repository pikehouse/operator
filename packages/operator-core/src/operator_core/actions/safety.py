"""
Safety controls for action execution (SAF-01, SAF-02).

This module provides critical safety infrastructure:
- Kill switch (SAF-01, SAFE-08): Immediately halt all pending actions and Docker containers
- Observe-only mode (SAF-02): Prevent any action execution (v1 behavior)

The SafetyController is the gatekeeper for all action execution.
All execution paths MUST check can_execute before proceeding.

Per project patterns:
- Default to observe-only mode (safe by default)
- Log all mode changes and kill switch activations
- Integrate with ActionDB for cancellation
- Force-terminate Docker containers via subprocess (asyncio.Task.cancel can't interrupt blocking calls)
"""

from __future__ import annotations

import asyncio
import subprocess
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from operator_core.actions.audit import ActionAuditor


class SafetyMode(str, Enum):
    """
    Safety modes for action execution.

    OBSERVE: Observe-only mode - no action execution (v1 behavior, default)
    EXECUTE: Actions can be executed (v2 behavior, opt-in)
    """

    OBSERVE = "observe"
    """Observe-only mode, no action execution (default)."""

    EXECUTE = "execute"
    """Actions can be executed."""


class ObserveOnlyError(Exception):
    """
    Raised when action execution is attempted in observe-only mode.

    This exception provides a clear message about why execution
    was blocked and how to enable it.
    """

    def __init__(self, message: str | None = None) -> None:
        """
        Initialize the error.

        Args:
            message: Optional custom message
        """
        if message is None:
            message = (
                "Action execution blocked: observe-only mode is active. "
                "To enable action execution, set safety mode to EXECUTE."
            )
        super().__init__(message)


class SafetyController:
    """
    Safety controller for action execution.

    Controls whether actions can be executed through mode management
    and provides emergency kill switch to halt all pending actions.

    The SafetyController is the gatekeeper - all action execution paths
    MUST check can_execute before proceeding.

    Example:
        controller = SafetyController(db_path, auditor)

        # Check before executing
        controller.check_can_execute()  # Raises ObserveOnlyError if observe mode

        # Enable execution
        await controller.set_mode(SafetyMode.EXECUTE)

        # Emergency stop
        cancelled = await controller.kill_switch()
    """

    def __init__(
        self,
        db_path: Path,
        auditor: "ActionAuditor",
        mode: SafetyMode = SafetyMode.OBSERVE,
    ) -> None:
        """
        Initialize the safety controller.

        Args:
            db_path: Path to the SQLite database
            auditor: ActionAuditor for logging mode changes and kill switch
            mode: Initial safety mode (defaults to OBSERVE for safety)
        """
        self.db_path = db_path
        self._auditor = auditor
        self._mode = mode

    @property
    def mode(self) -> SafetyMode:
        """Current safety mode."""
        return self._mode

    @property
    def is_observe_only(self) -> bool:
        """True if in observe-only mode (actions blocked)."""
        return self._mode == SafetyMode.OBSERVE

    @property
    def can_execute(self) -> bool:
        """True if actions can be executed."""
        return self._mode == SafetyMode.EXECUTE

    def check_can_execute(self) -> None:
        """
        Check if action execution is allowed.

        Raises:
            ObserveOnlyError: If mode is OBSERVE
        """
        if self._mode == SafetyMode.OBSERVE:
            raise ObserveOnlyError()

    async def set_mode(self, mode: SafetyMode) -> None:
        """
        Set the safety mode.

        When switching to OBSERVE mode, all pending actions are cancelled
        (gentler than kill switch but same effect).

        Args:
            mode: The new safety mode
        """
        if mode == self._mode:
            return  # No change

        old_mode = self._mode
        self._mode = mode

        # Log mode change
        await self._auditor.log_mode_change(old_mode.value, mode.value)

        # If switching to OBSERVE, cancel all pending (like kill switch but quieter)
        if mode == SafetyMode.OBSERVE:
            # Lazy import to avoid circular dependency
            from operator_core.db.actions import ActionDB
            async with ActionDB(self.db_path) as db:
                await db.cancel_all_pending()

    async def _force_kill_docker_containers(self) -> int:
        """
        Force-terminate all running operator-managed Docker containers.

        Uses subprocess to run 'docker kill' commands since asyncio.Task.cancel()
        cannot interrupt blocking Docker SDK operations.

        Returns:
            Number of containers killed
        """
        try:
            # List all operator-managed containers (by label)
            result = subprocess.run(
                ["docker", "ps", "-q", "--filter", "label=operator.managed=true"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return 0

            container_ids = result.stdout.strip().split("\n")
            container_ids = [cid for cid in container_ids if cid]  # Filter empty

            if not container_ids:
                return 0

            # Kill all containers
            kill_result = subprocess.run(
                ["docker", "kill"] + container_ids,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if kill_result.returncode == 0:
                return len(container_ids)
            else:
                return 0

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            # Docker not available or timeout
            return 0

    async def _cancel_operator_tasks(self) -> int:
        """
        Cancel all asyncio tasks associated with operator actions.

        Returns:
            Number of tasks cancelled
        """
        # Get all running tasks except current
        current_task = asyncio.current_task()
        all_tasks = asyncio.all_tasks()

        operator_tasks = [
            task for task in all_tasks
            if task is not current_task and not task.done()
        ]

        # Cancel all operator tasks
        for task in operator_tasks:
            task.cancel()

        return len(operator_tasks)

    async def kill_switch(self) -> dict[str, int]:
        """
        Emergency stop - cancel all pending actions, Docker containers, and switch to observe mode (SAF-01, SAFE-08).

        This is the emergency stop button:
        1. Cancels ALL pending (proposed/validated) proposals
        2. Force-terminates Docker containers via subprocess
        3. Cancels asyncio tasks
        4. Switches mode to OBSERVE
        5. Logs kill_switch event with detailed counts

        Returns:
            Dict with counts: {
                "pending_proposals": int,
                "docker_containers": int,
                "asyncio_tasks": int
            }
        """
        # Cancel all pending proposals
        # Lazy import to avoid circular dependency
        from operator_core.db.actions import ActionDB
        async with ActionDB(self.db_path) as db:
            pending_proposals = await db.cancel_all_pending()

        # Force-terminate Docker containers
        docker_containers = await self._force_kill_docker_containers()

        # Cancel asyncio tasks
        asyncio_tasks = await self._cancel_operator_tasks()

        # Switch to observe mode
        self._mode = SafetyMode.OBSERVE

        # Log kill switch activation with detailed counts
        await self._auditor.log_kill_switch(
            pending_proposals,
            docker_killed=docker_containers,
            tasks_cancelled=asyncio_tasks
        )

        return {
            "pending_proposals": pending_proposals,
            "docker_containers": docker_containers,
            "asyncio_tasks": asyncio_tasks,
        }
