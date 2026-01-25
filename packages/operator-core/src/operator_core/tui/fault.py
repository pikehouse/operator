"""
Fault injection and recovery workflow for TUI demo.

Provides countdown display, node kill, and recovery functionality
integrated with TUIController.

Per RESEARCH.md Pattern 4: Fault Injection Integration
- Adapted from chaos.py patterns
- Uses python-on-whales for Docker operations
- Stores killed container name for recovery
"""

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from python_on_whales import DockerClient


@dataclass
class FaultWorkflow:
    """
    Manages fault injection and recovery lifecycle.

    Provides methods for:
    - Countdown display before fault
    - Node kill (random TiKV container)
    - Node recovery (restart killed container)

    Attributes:
        compose_file: Path to docker-compose.yaml
        on_narration_update: Callback to update narration panel
        on_workload_update: Callback to inject workload values
        shutdown_event: Event for graceful shutdown
    """

    compose_file: Path
    on_narration_update: Callable[[str], None]
    on_workload_update: Callable[[float], None]
    shutdown_event: asyncio.Event

    _docker: DockerClient = field(init=False)
    _killed_container: str | None = field(init=False, default=None)
    _baseline_ops: float = field(init=False, default=10000.0)

    def __post_init__(self) -> None:
        """Initialize Docker client."""
        self._docker = DockerClient(compose_files=[self.compose_file])

    async def run_countdown(self, seconds: int = 3) -> bool:
        """
        Display countdown before fault injection.

        Per RESEARCH.md Pattern 2: Countdown Display with Rich Update.
        Uses asyncio.sleep with shutdown check between ticks.

        Args:
            seconds: Countdown duration (default 3)

        Returns:
            True if countdown completed, False if interrupted
        """
        for i in range(seconds, 0, -1):
            text = f"[bold yellow]Injecting fault in {i}...[/bold yellow]"
            self.on_narration_update(text)
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=1.0)
                return False  # Interrupted
            except asyncio.TimeoutError:
                continue  # Normal tick

        self.on_narration_update("[bold red]FAULT INJECTED![/bold red]")
        await asyncio.sleep(0.5)
        return True

    async def inject_fault(self) -> str | None:
        """
        Kill a random TiKV container.

        Per chaos.py pattern: Uses SIGKILL for immediate termination.

        Returns:
            Name of killed container, or None if no targets
        """
        containers = self._docker.compose.ps()
        tikv_containers = [
            c
            for c in containers
            if "tikv" in c.name.lower() and c.state.running
        ]

        if not tikv_containers:
            self.on_narration_update("[red]No running TiKV containers found![/red]")
            return None

        target = random.choice(tikv_containers)
        container_name = target.name

        self._docker.kill(container_name)
        self._killed_container = container_name

        return container_name

    async def simulate_degradation(self) -> None:
        """
        Simulate workload degradation after fault.

        Injects decreasing ops/sec values to show degradation in workload panel.
        """
        # Simulate degradation: ops drop from baseline to ~20%
        for i in range(5):
            if self.shutdown_event.is_set():
                return
            degraded_ops = self._baseline_ops * (0.8 - i * 0.15)
            self.on_workload_update(max(100.0, degraded_ops))
            await asyncio.sleep(1.0)

    async def recover(self) -> bool:
        """
        Restart the killed container.

        Returns:
            True if recovery successful, False if nothing to recover
        """
        if not self._killed_container:
            return False

        # Extract service name from container name
        # Container names may have project prefix: "operator-tikv-tikv0-1" -> "tikv0"
        service_name = self._killed_container
        for part in self._killed_container.split("-"):
            if part.startswith("tikv") and len(part) > 4:
                service_name = part
                break

        self._docker.compose.start(services=[service_name])
        self._killed_container = None

        return True

    async def simulate_recovery(self) -> None:
        """
        Simulate workload recovery after node restart.

        Injects increasing ops/sec values to show recovery in workload panel.
        """
        # Simulate recovery: ops climb back to baseline
        for i in range(5):
            if self.shutdown_event.is_set():
                return
            recovering_ops = self._baseline_ops * (0.3 + i * 0.15)
            self.on_workload_update(min(self._baseline_ops, recovering_ops))
            await asyncio.sleep(1.0)

    def establish_baseline(self, ops: float) -> None:
        """Set baseline ops/sec for degradation simulation."""
        self._baseline_ops = ops
