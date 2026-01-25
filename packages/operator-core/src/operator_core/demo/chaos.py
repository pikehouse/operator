"""
Chaos demo orchestration for AI diagnosis showcase.

This module provides the ChaosDemo class that sequences the end-to-end
chaos demonstration:
1. Ensure cluster is healthy
2. Start YCSB load
3. Inject fault (random TiKV kill)
4. Wait for detection with live countdown
5. Run AI diagnosis
6. Display diagnosis in Rich panel
7. Cleanup (restart killed container)

Per RESEARCH.md patterns:
- Use Rich Console for all output
- Use Rich Live for detection countdown
- Use try/finally for cleanup
- Use SIGKILL via docker.kill() for realistic failure simulation
"""

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from python_on_whales import DockerClient
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import TicketStatus


@dataclass
class ChaosDemo:
    """
    Orchestrates the chaos demo lifecycle.

    Sequences all demo stages with interactive prompts and Rich
    terminal output. Ensures cleanup even on errors via try/finally.

    Attributes:
        console: Rich Console for all output
        compose_file: Path to docker-compose.yaml
        subject: Subject name (default "tikv")
        detection_timeout: Seconds to wait for detection (default 30)
        db_path: Path to ticket database

    Example:
        demo = ChaosDemo(
            console=Console(),
            compose_file=Path("subjects/tikv/docker-compose.yaml"),
        )
        await demo.run()
    """

    console: Console
    compose_file: Path
    subject: str = "tikv"
    detection_timeout: float = 30.0
    db_path: Path = field(
        default_factory=lambda: Path.home() / ".operator" / "tickets.db"
    )

    # Internal state
    _docker: DockerClient = field(init=False)
    _killed_container: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Initialize Docker client with compose file."""
        self._docker = DockerClient(compose_files=[self.compose_file])

    async def run(self) -> None:
        """
        Execute the full demo sequence.

        Stages:
        1. Ensure cluster healthy
        2. Start YCSB load
        3. Inject fault
        4. Wait for detection
        5. Run AI diagnosis
        6. Display diagnosis
        7. Cleanup (always runs via finally)
        """
        try:
            self._stage_banner("Stage 1: Cluster Health Check")
            await self._ensure_cluster_healthy()

            self._prompt("Press Enter to start YCSB load...")
            self._stage_banner("Stage 2: Start Load Generator")
            await self._start_ycsb_load()

            self._prompt("Press Enter to inject fault...")
            self._stage_banner("Stage 3: Fault Injection")
            container = await self._inject_fault()

            self._stage_banner("Stage 4: Detection Wait")
            detected = await self._wait_for_detection(container)

            if detected:
                self._prompt("Press Enter to run AI diagnosis...")
                self._stage_banner("Stage 5: AI Diagnosis")
                diagnosis = await self._run_diagnosis()
                if diagnosis:
                    self._display_diagnosis(diagnosis)
                else:
                    self.console.print(
                        "[yellow]No diagnosis generated (no open tickets found)[/yellow]"
                    )
            else:
                self.console.print(
                    f"[yellow]Detection timeout ({self.detection_timeout}s) - "
                    "proceeding to cleanup[/yellow]"
                )

        finally:
            self._stage_banner("Stage 6: Cleanup")
            await self._cleanup()

    async def _ensure_cluster_healthy(self) -> None:
        """
        Check cluster is up, start if not, wait for healthy.

        Uses docker compose to check container status. Starts the cluster
        if containers are not running, then waits for healthy state.
        """
        self.console.print("Checking cluster status...")

        containers = self._docker.compose.ps()
        running_count = sum(1 for c in containers if c.state.running)

        if running_count == 0:
            self.console.print("[yellow]Cluster not running, starting...[/yellow]")
            self._docker.compose.up(detach=True, wait=True)
            self.console.print("[green]Cluster started and healthy[/green]")
        else:
            # Check if all expected containers are healthy
            total = len(containers)
            if running_count == total:
                self.console.print(
                    f"[green]Cluster healthy ({running_count}/{total} containers running)[/green]"
                )
            else:
                self.console.print(
                    f"[yellow]Cluster partially running ({running_count}/{total}), waiting...[/yellow]"
                )
                self._docker.compose.up(detach=True, wait=True)
                self.console.print("[green]Cluster now healthy[/green]")

    def _prompt(self, message: str) -> None:
        """
        Wait for user to press Enter.

        Uses console.input() for consistent Rich styling.

        Args:
            message: Prompt message to display
        """
        self.console.input(f"\n[yellow]{message}[/yellow] ")

    async def _start_ycsb_load(self) -> None:
        """
        Start YCSB with load profile.

        Uses docker compose profile to start YCSB container.
        Shows brief status message about load generation.
        """
        self.console.print("Starting YCSB load generator...")

        # Start YCSB with the load profile
        self._docker.compose.up(
            services=["ycsb"],
            detach=True,
        )

        self.console.print(
            "[green]YCSB load generator started[/green]\n"
            "  Operations: write-heavy workload\n"
            "  Target: TiKV cluster"
        )

        # Give YCSB a moment to start generating load
        await asyncio.sleep(2.0)

    async def _inject_fault(self) -> str:
        """
        Select random TiKV container and kill it.

        Uses SIGKILL for immediate termination (simulates sudden crash).

        Returns:
            Name of the killed container

        Raises:
            RuntimeError: If no running TiKV containers found
        """
        # Get running TiKV containers
        containers = self._docker.compose.ps()
        tikv_containers = [
            c
            for c in containers
            if "tikv" in c.name.lower() and c.state.running
        ]

        if not tikv_containers:
            raise RuntimeError("No running TiKV containers found")

        # Random selection
        target = random.choice(tikv_containers)
        container_name = target.name

        self.console.print(f"Selected target: [bold red]{container_name}[/bold red]")
        self.console.print("Killing container with SIGKILL...")

        # Kill with SIGKILL (immediate, no cleanup)
        self._docker.kill(container_name)
        self._killed_container = container_name

        self.console.print(f"[red]Container {container_name} killed[/red]")

        return container_name

    async def _get_store_id_for_container(self, container_name: str) -> str | None:
        """
        Map container name to PD store ID by matching hostname in address.

        The container name (e.g., "tikv0") matches the hostname portion
        of the store address (e.g., "tikv0:20160").

        Args:
            container_name: Docker container name

        Returns:
            Store ID string if found, None otherwise
        """
        # Import here to avoid circular imports
        from operator_tikv.pd_client import PDClient

        # Extract service name from container name (e.g., "operator-tikv-tikv0-1" -> "tikv0")
        # Container names may have project prefix and replica suffix
        service_name = container_name
        for part in container_name.split("-"):
            if part.startswith("tikv") and part[-1].isdigit():
                service_name = part
                break

        async with httpx.AsyncClient(base_url="http://localhost:2379") as http:
            pd = PDClient(http=http)
            stores = await pd.get_stores()
            for store in stores:
                # Store address format: "tikv0:20160"
                if store.address.startswith(f"{service_name}:"):
                    return store.id
        return None

    async def _wait_for_detection(self, killed_container: str) -> bool:
        """
        Wait for violation detection with live countdown.

        Polls for ticket creation at 2-second intervals, showing
        elapsed time via Rich Live display.

        Args:
            killed_container: Name of the killed container

        Returns:
            True if detection occurred, False on timeout
        """
        # Get store ID for the killed container
        store_id = await self._get_store_id_for_container(killed_container)
        if store_id is None:
            self.console.print(
                f"[red]Could not map {killed_container} to store ID[/red]"
            )
            return False

        self.console.print(f"Mapped container to store ID: {store_id}")
        self.console.print(
            f"Waiting for detection (timeout: {self.detection_timeout}s)..."
        )

        start = asyncio.get_event_loop().time()

        with Live(Text(""), console=self.console, refresh_per_second=1) as live:
            while True:
                elapsed = asyncio.get_event_loop().time() - start
                live.update(
                    Text(f"Waiting for detection... {elapsed:.0f}s", style="cyan")
                )

                # Check for ticket creation
                async with TicketDB(self.db_path) as db:
                    tickets = await db.list_tickets(status=TicketStatus.OPEN)
                    has_ticket = any(
                        t.store_id == store_id and t.invariant_name == "store_down"
                        for t in tickets
                    )

                if has_ticket:
                    live.update(Text("Detected!", style="bold green"))
                    await asyncio.sleep(0.5)  # Brief pause to show "Detected!"
                    return True

                if elapsed >= self.detection_timeout:
                    live.update(
                        Text(f"Timeout ({self.detection_timeout}s)", style="yellow")
                    )
                    await asyncio.sleep(0.5)
                    return False

                await asyncio.sleep(2.0)

    async def _run_diagnosis(self) -> str | None:
        """
        Run one-shot AI diagnosis on the detected ticket.

        Per RESEARCH.md Pitfall 5: Don't run full AgentRunner loop -
        do one-shot diagnosis for demo purposes.

        Returns:
            Diagnosis markdown string, or None if no tickets
        """
        # Import agent components
        from operator_core.agent.context import ContextGatherer
        from operator_core.agent.diagnosis import DiagnosisOutput, format_diagnosis_markdown
        from operator_core.agent.prompt import SYSTEM_PROMPT, build_diagnosis_prompt
        from operator_tikv.pd_client import PDClient
        from operator_tikv.prom_client import PrometheusClient
        from operator_tikv.subject import TiKVSubject

        async with TicketDB(self.db_path) as db:
            tickets = await db.list_tickets(status=TicketStatus.OPEN)
            if not tickets:
                return None

            ticket = tickets[0]  # Get first open ticket
            self.console.print(
                f"Diagnosing ticket #{ticket.id}: [bold]{ticket.invariant_name}[/bold]"
            )

            # Create subject with httpx clients
            async with httpx.AsyncClient(base_url="http://localhost:2379") as pd_http:
                async with httpx.AsyncClient(
                    base_url="http://localhost:9090"
                ) as prom_http:
                    subject = TiKVSubject(
                        pd=PDClient(http=pd_http),
                        prom=PrometheusClient(http=prom_http),
                    )

                    # Gather context and build prompt
                    gatherer = ContextGatherer(subject, db)
                    context = await gatherer.gather(ticket)
                    prompt = build_diagnosis_prompt(context)

                    self.console.print("Invoking Claude for diagnosis...")

                    # Invoke Claude with structured output
                    client = AsyncAnthropic()
                    response = await client.beta.messages.parse(
                        model="claude-sonnet-4-5",
                        max_tokens=4096,
                        betas=["structured-outputs-2025-11-13"],
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                        output_schema=DiagnosisOutput,
                    )

                    diagnosis_md = format_diagnosis_markdown(response.output_parsed)

                    # Update ticket with diagnosis
                    await db.update_diagnosis(ticket.id, diagnosis_md)

                    return diagnosis_md

    def _display_diagnosis(self, diagnosis_md: str) -> None:
        """
        Display AI diagnosis in a styled Rich panel.

        Uses green border and "AI Diagnosis" title per RESEARCH.md.

        Args:
            diagnosis_md: Markdown-formatted diagnosis text
        """
        self.console.print()
        self.console.print(
            Panel(
                Markdown(diagnosis_md),
                title="[bold green]AI Diagnosis[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )

    async def _cleanup(self) -> None:
        """
        Restart killed container and restore cluster health.

        Uses try/finally pattern in run() to ensure this always executes.
        """
        if self._killed_container:
            self.console.print(
                f"Restarting killed container: {self._killed_container}"
            )
            # Restart the container
            self._docker.compose.start(services=[self._killed_container])
            self.console.print(
                f"[green]Container {self._killed_container} restarted[/green]"
            )
            self._killed_container = None
        else:
            self.console.print("[dim]No cleanup needed[/dim]")

        self.console.print("\n[bold green]Demo complete![/bold green]")

    def _stage_banner(self, title: str, style: str = "bold blue") -> None:
        """
        Display a stage separator.

        Uses console.rule() for clear visual separation between stages.

        Args:
            title: Stage title text
            style: Rich style for the title (default "bold blue")
        """
        self.console.print()
        self.console.rule(f"[{style}]{title}[/{style}]")
        self.console.print()
