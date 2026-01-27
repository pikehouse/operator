"""
TUI-integrated demo controller for full-featured demos.

This module provides TUIDemoController which combines:
- Existing Rich TUI 5-panel layout (from operator_core.tui.layout)
- Subject-agnostic demo infrastructure (chapters, health pollers, chaos)
- Real subprocess management (monitor and agent daemons)

The controller works with any subject (TiKV or rate limiter) by:
- Using generic HealthPollerProtocol for health data
- Detecting subject type from health dict keys
- Formatting health panel appropriately per subject

Usage:
    from demo.tikv import TIKV_CHAPTERS
    from demo.tikv_health import TiKVHealthPoller

    controller = TUIDemoController(
        subject_name="tikv",
        chapters=TIKV_CHAPTERS,
        health_poller=TiKVHealthPoller(),
        compose_file=Path("subjects/tikv/docker-compose.yaml"),
    )
    await controller.run()
"""

import asyncio
import functools
import signal
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live

from demo.status import demo_status
from demo.types import Chapter, DemoState, HealthPollerProtocol
from operator_core.tui.keyboard import KeyboardTask
from operator_core.tui.layout import (
    create_layout,
    make_cluster_panel,
    make_panel,
)
from operator_core.tui.subprocess import SubprocessManager


# Unicode symbols for health indicators
UP_SYMBOL = "\u25cf"  # ● (filled circle)
DOWN_SYMBOL = "\u2717"  # ✗ (cross mark)


class TUIDemoController:
    """
    Full-featured TUI demo controller with 5-panel layout.

    Combines the existing TUI infrastructure with subject-agnostic demo
    abstractions to create production-quality demos for any subject.

    The controller:
    - Spawns monitor and agent daemon subprocesses
    - Polls health via HealthPollerProtocol
    - Displays 5-panel layout with Rich Live
    - Handles keyboard input for chapter progression
    - Executes chapter callbacks (chaos injection, etc.)

    Attributes:
        subject_name: Subject identifier for CLI flags ("tikv" or "ratelimiter")
        chapters: List of demo chapters to progress through
        health_poller: Subject-specific health poller
        compose_file: Path to docker-compose.yaml (for context)
        console: Rich Console for rendering
    """

    def __init__(
        self,
        subject_name: str,
        chapters: list[Chapter],
        health_poller: HealthPollerProtocol,
        compose_file: Path | None = None,
        console: Console | None = None,
    ) -> None:
        """
        Initialize TUI demo controller.

        Args:
            subject_name: Subject identifier ("tikv" or "ratelimiter")
            chapters: List of demo chapters
            health_poller: Subject-specific health poller implementing protocol
            compose_file: Path to docker-compose.yaml (optional)
            console: Rich Console (creates default if None)
        """
        self.subject_name = subject_name
        self.console = console if console is not None else Console()
        self.compose_file = compose_file

        # Core components
        self._shutdown = asyncio.Event()
        self._layout = create_layout()
        self._subprocess_mgr: SubprocessManager | None = None
        self._health_poller = health_poller
        self._keyboard: KeyboardTask | None = None

        # Demo state
        self._demo_state = DemoState(chapters=chapters)
        self._current_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """
        Run the TUI demo until shutdown signal.

        CRITICAL ORDER (per TUIController patterns):
        1. Register signal handlers BEFORE Live context
        2. Spawn subprocesses AFTER signal handlers, BEFORE Live context
        3. Initialize panels with placeholder content
        4. Enter Live context for rendering
        5. Run TaskGroup with reader tasks and update loop
        6. Exit cleanly, terminate subprocesses, let Live context restore terminal
        """
        loop = asyncio.get_running_loop()

        # 1. Register signal handlers BEFORE Live context
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        # 2. Spawn subprocesses AFTER signal handlers, BEFORE Live context
        self._subprocess_mgr = SubprocessManager()
        monitor_proc = await self._subprocess_mgr.spawn(
            "monitor",
            [
                "-u",  # Unbuffered output (critical for live display)
                "-m",
                "operator_core.cli.main",
                "monitor",
                "run",
                "--subject",
                self.subject_name,
                "-i",
                "5",
            ],
            buffer_size=50,
        )
        agent_proc = await self._subprocess_mgr.spawn(
            "agent",
            [
                "-u",  # Unbuffered output (critical for live display)
                "-m",
                "operator_core.cli.main",
                "agent",
                "start",
                "--subject",
                self.subject_name,
                "-i",
                "5",
            ],
            buffer_size=50,
        )

        # Initialize keyboard handler
        self._keyboard = KeyboardTask(on_key=self._handle_key)

        # 3. Initialize panels with placeholder content
        self._init_panels()

        # 4. Enter Live context for flicker-free rendering
        # Use screen=False so print() statements from callbacks are visible
        with Live(
            self._layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,
        ) as live:
            # 5. Run TaskGroup with reader tasks and update loop
            try:
                async with asyncio.TaskGroup() as tg:
                    # Subprocess output readers
                    tg.create_task(self._subprocess_mgr.read_output(monitor_proc))
                    tg.create_task(self._subprocess_mgr.read_output(agent_proc))
                    # Health poller
                    tg.create_task(self._health_poller.run())
                    # Keyboard handler
                    tg.create_task(self._keyboard.run())
                    # Update loop
                    tg.create_task(self._update_loop(live))
            except* Exception:
                pass  # TaskGroup handles cancellation

        # 6. Clean shutdown - terminate subprocesses and load generators
        if self._subprocess_mgr:
            await self._subprocess_mgr.terminate_all()
        await self._cleanup_load_generators()
        self.console.print("[green]Demo shutdown complete[/green]")

    def _handle_signal(self, sig: signal.Signals) -> None:
        """
        Handle shutdown signal by setting shutdown events.

        Signals all components to stop: subprocesses, health poller, keyboard.

        Args:
            sig: Signal received (SIGINT or SIGTERM)
        """
        self._shutdown.set()
        if self._subprocess_mgr is not None:
            self._subprocess_mgr.shutdown.set()
        if self._health_poller is not None:
            self._health_poller.stop()
        if self._keyboard is not None:
            self._keyboard.stop()

    def _init_panels(self) -> None:
        """Initialize all panels with placeholder content."""
        self._layout["cluster"].update(
            make_panel("Loading...", "Cluster Status", "cyan")
        )
        # Show first chapter in narration panel
        self._update_narration()
        self._layout["main"]["monitor"].update(
            make_panel("Waiting for monitor...", "Monitor", "blue")
        )
        self._layout["main"]["agent"].update(
            make_panel("Waiting for agent...", "Agent", "green")
        )
        self._layout["main"]["workload"].update(
            make_panel("Waiting for data...", "Workload", "yellow")
        )

    def _handle_key(self, key: str) -> None:
        """
        Handle keypress for demo flow control.

        SPACE/ENTER/RIGHT: Advance to next chapter
        Q: Quit demo

        Executes on_enter callbacks when entering new chapters.

        Args:
            key: Key pressed (raw character or escape sequence)
        """
        if self._demo_state is None:
            return

        # Check for advance keys
        if key in (" ", "\r", "\n", "\x1b[C"):
            current = self._demo_state.get_current()

            # Don't advance if current chapter blocks it
            if current.blocks_advance and self._current_task is not None:
                return  # Action in progress

            # Clear status when advancing
            demo_status.clear()

            # Advance to next chapter
            if self._demo_state.advance():
                self._update_narration()

                # Check if new chapter has on_enter callback
                new_chapter = self._demo_state.get_current()
                if new_chapter.on_enter is not None:
                    # Schedule the callback as a task
                    self._current_task = asyncio.create_task(
                        self._execute_chapter_callback(new_chapter)
                    )
        # Check for quit keys
        elif key in ("q", "Q"):
            self._shutdown.set()
            if self._subprocess_mgr is not None:
                self._subprocess_mgr.shutdown.set()
            if self._health_poller is not None:
                self._health_poller.stop()
            if self._keyboard is not None:
                self._keyboard.stop()

    def _update_narration(self) -> None:
        """
        Update narration panel with current chapter content.

        Shows chapter title, narration text, status (if any), key hints, and progress.
        """
        if self._demo_state is None:
            return

        chapter = self._demo_state.get_current()
        progress = self._demo_state.get_progress()

        # Get current status (from chaos callbacks) - show at TOP for visibility
        status = demo_status.get()
        status_line = f"[bold]► {status}[/bold]\n\n" if status else ""

        # Build content with status at top, then title, narration, and key hint
        content = f"{status_line}[bold cyan]{chapter.title}[/bold cyan] {progress}\n\n{chapter.narration}\n\n{chapter.key_hint}"
        self._layout["main"]["narration"].update(
            make_panel(content, "Chapter", "magenta")
        )

    async def _execute_chapter_callback(self, chapter: Chapter) -> None:
        """
        Execute chapter's on_enter callback and handle auto-advance.

        Handles async callback execution and auto-advance if configured.
        IMPORTANT: If this chapter auto-advances, also trigger the next
        chapter's on_enter callback (recursively if needed).

        Args:
            chapter: Chapter whose callback to execute
        """
        # Execute callback if present
        if chapter.on_enter is not None:
            try:
                print(f"[TUI] Executing callback for: {chapter.title}")
                await chapter.on_enter()
                print(f"[TUI] Callback complete for: {chapter.title}")
            except Exception as e:
                print(f"[TUI] ERROR in callback for {chapter.title}: {e}")
                import traceback
                traceback.print_exc()

        # Clear current task since this callback is done
        self._current_task = None

        # Auto-advance if configured
        if chapter.auto_advance and self._demo_state is not None:
            self._demo_state.advance()
            self._update_narration()

            # CRITICAL: Trigger the next chapter's callback (if any)
            # This ensures auto-advance chains work correctly
            next_chapter = self._demo_state.get_current()
            await self._execute_chapter_callback(next_chapter)

    async def _update_loop(self, live: Live) -> None:
        """
        Update loop that refreshes panels until shutdown.

        Runs inside TaskGroup alongside reader tasks.
        Uses wait_for with timeout for interruptible loop.

        Args:
            live: Rich Live context for refreshing display
        """
        while not self._shutdown.is_set():
            self._refresh_panels()
            live.refresh()
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass  # Normal refresh interval

    def _refresh_panels(self) -> None:
        """
        Refresh panel contents from subprocess output and health status.

        Updates all 5 panels:
        - Cluster: Health status (subject-specific formatting)
        - Narration: Current chapter with live status
        - Monitor: Subprocess output
        - Agent: Subprocess output
        - Workload: Placeholder (no workload tracking)
        """
        if self._subprocess_mgr is None:
            return

        # Update narration panel (includes status from chaos callbacks)
        self._update_narration()

        # Calculate available lines based on terminal height
        # Layout uses ratios: narration(2) + monitor(3) + agent(3) + workload(2) = 10 parts
        # Monitor and agent each get 3/10 of terminal height
        # Panel border uses 2 lines
        term_height = self.console.size.height
        panel_rows = (term_height * 3) // 10  # 3/10 of height for monitor/agent
        panel_content_lines = panel_rows - 2  # minus border
        panel_content_lines = max(panel_content_lines, 5)  # minimum 5 lines

        # Update monitor panel
        monitor_buf = self._subprocess_mgr.get_buffer("monitor")
        if monitor_buf:
            self._layout["main"]["monitor"].update(
                make_panel(monitor_buf.get_text(n=panel_content_lines), "Monitor", "blue")
            )

        # Update agent panel
        agent_buf = self._subprocess_mgr.get_buffer("agent")
        if agent_buf:
            self._layout["main"]["agent"].update(
                make_panel(agent_buf.get_text(n=panel_content_lines), "Agent", "green")
            )

        # Update cluster panel with health status
        if self._health_poller is not None:
            health = self._health_poller.get_health()
            if health:
                content = self._format_health_panel(health)
                has_issues = health.get("has_issues", False)
                self._layout["cluster"].update(
                    make_cluster_panel(
                        content,
                        has_issues=has_issues,
                        detection_active=False,  # Could parse monitor output for detection
                    )
                )
                # Update workload panel with counter stats
                workload_content = self._format_workload_panel(health)
                self._layout["main"]["workload"].update(
                    make_panel(workload_content, "Workload", "yellow")
                )

    def _format_health_panel(self, health: dict[str, Any]) -> str:
        """
        Format health panel content based on subject type.

        Detects subject type from health dict structure and formats accordingly:
        - TiKV: Shows TiKV stores and PD members
        - Rate limiter: Shows rate limiter nodes and Redis connectivity

        Args:
            health: Health data dict from HealthPollerProtocol

        Returns:
            Rich markup string for panel content
        """
        # Detect subject type from health dict keys
        nodes = health.get("nodes", [])
        if not nodes:
            return "[dim]No health data available[/dim]"

        # Check if this is TiKV (has "type" field with "tikv"/"pd")
        if nodes and nodes[0].get("type") in ("tikv", "pd"):
            return self._format_tikv_health(health)
        else:
            return self._format_ratelimiter_health(health)

    def _format_tikv_health(self, health: dict[str, Any]) -> str:
        """
        Format TiKV cluster health panel.

        Args:
            health: Health dict with TiKV nodes

        Returns:
            Rich markup string with TiKV stores and PD members
        """
        lines = ["[bold]TiKV Cluster[/bold]", ""]

        nodes = health.get("nodes", [])
        tikv_nodes = [n for n in nodes if n.get("type") == "tikv"]
        pd_nodes = [n for n in nodes if n.get("type") == "pd"]

        lines.append("[dim]TiKV Stores:[/dim]")
        for node in tikv_nodes:
            lines.append(f"  {self._format_node_status(node)}")

        lines.append("")
        lines.append("[dim]PD Members:[/dim]")
        for node in pd_nodes:
            lines.append(f"  {self._format_node_status(node)}")

        return "\n".join(lines)

    def _format_ratelimiter_health(self, health: dict[str, Any]) -> str:
        """
        Format rate limiter cluster health panel.

        Args:
            health: Health dict with rate limiter nodes and Redis status

        Returns:
            Rich markup string with node list and Redis status
        """
        lines = ["[bold]Rate Limiter Cluster[/bold]", ""]

        # Show nodes
        nodes = health.get("nodes", [])
        if nodes:
            lines.append("[dim]Nodes:[/dim]")
            for node in nodes:
                # Node format from management API: {id, address, state, last_seen}
                node_id = node.get("id", "?")
                address = node.get("address", "unknown")
                state = node.get("state", "unknown")

                # Format state with color
                if state == "Up":
                    indicator = f"[green]{UP_SYMBOL}[/green]"
                    status = "[green]Up[/green]"
                else:
                    indicator = f"[red]{DOWN_SYMBOL}[/red]"
                    status = "[bold red]Down[/bold red]"

                lines.append(f"  {indicator} {address}: {status}")
        else:
            lines.append("[dim]No nodes registered[/dim]")

        # Show Redis connectivity
        lines.append("")
        redis_connected = health.get("redis_connected", False)
        if redis_connected:
            lines.append(f"[green]{UP_SYMBOL}[/green] [dim]Redis:[/dim] [green]Connected[/green]")
        else:
            lines.append(f"[red]{DOWN_SYMBOL}[/red] [dim]Redis:[/dim] [bold red]Disconnected[/bold red]")

        return "\n".join(lines)

    def _format_node_status(self, node: dict[str, Any]) -> str:
        """
        Format single node status line with color-coded indicator.

        Args:
            node: Node dict with "name" and "health" keys

        Returns:
            Rich markup string like "[green]●[/green] tikv-1: [green]Up[/green]"
        """
        name = node.get("name", "?")
        health = node.get("health", "unknown")

        if health == "up":
            indicator = f"[green]{UP_SYMBOL}[/green]"
            status = "[green]Up[/green]"
        elif health == "down":
            indicator = f"[red]{DOWN_SYMBOL}[/red]"
            status = "[bold red]Down[/bold red]"
        elif health == "offline":
            indicator = f"[yellow]{DOWN_SYMBOL}[/yellow]"
            status = "[yellow]Offline[/yellow]"
        else:
            indicator = "[dim]?[/dim]"
            status = "[dim]Unknown[/dim]"

        return f"{indicator} {name}: {status}"

    def _format_workload_panel(self, health: dict[str, Any]) -> str:
        """
        Format workload panel based on subject type.

        For rate limiter: Shows counters and their current counts vs limits.
        For TiKV: Shows ops/sec throughput.

        Args:
            health: Health dict with counters list or ops_per_sec

        Returns:
            Rich markup string for workload panel
        """
        # Check if this is TiKV (has ops_per_sec)
        ops_per_sec = health.get("ops_per_sec")
        if ops_per_sec is not None:
            return self._format_tikv_workload(ops_per_sec)

        # Otherwise, format rate limiter counters
        counters = health.get("counters", [])
        if not counters:
            return "[dim]No active counters[/dim]"

        lines = ["[bold]Rate Limit Counters[/bold]", ""]

        # Count anomalies
        over_limit = [c for c in counters if c.get("over_limit")]
        if over_limit:
            lines.append(f"[bold red]⚠ {len(over_limit)} OVER LIMIT[/bold red]")
            lines.append("")

        # Show each counter
        for counter in counters:
            key = counter.get("key", "?")
            count = counter.get("count", 0)
            limit = counter.get("limit", 10)
            is_over = counter.get("over_limit", False)

            if is_over:
                indicator = f"[red]{DOWN_SYMBOL}[/red]"
                status = f"[bold red]{count}/{limit}[/bold red] (OVER!)"
            elif count > limit * 0.8:
                indicator = f"[yellow]{UP_SYMBOL}[/yellow]"
                status = f"[yellow]{count}/{limit}[/yellow]"
            else:
                indicator = f"[green]{UP_SYMBOL}[/green]"
                status = f"[green]{count}/{limit}[/green]"

            lines.append(f"  {indicator} {key}: {status}")

        return "\n".join(lines)

    def _format_tikv_workload(self, ops_per_sec: float) -> str:
        """
        Format TiKV workload panel with ops/sec.

        Args:
            ops_per_sec: Current throughput from Prometheus

        Returns:
            Rich markup string for workload panel
        """
        # Track ops history for sparkline
        if not hasattr(self, "_ops_history"):
            self._ops_history: list[float] = []

        self._ops_history.append(ops_per_sec)
        if len(self._ops_history) > 30:
            self._ops_history = self._ops_history[-30:]

        lines = ["[bold]TiKV Throughput[/bold]", ""]

        # Generate sparkline if we have enough data
        if len(self._ops_history) >= 3:
            try:
                from sparklines import sparklines
                sparkline = list(sparklines(self._ops_history))[0]
                lines.append(f"[green]{sparkline}[/green]")
                lines.append("")
            except Exception:
                pass  # sparklines not available

        # Show current value
        lines.append(f"Current: [bold]{ops_per_sec:.0f}[/bold] ops/sec")

        return "\n".join(lines)

    async def _cleanup_load_generators(self) -> None:
        """
        Stop any running load generators on demo exit.

        For TiKV: Stops YCSB container (ycsb-run)
        For rate limiter: Stops loadgen service (if running)
        """
        if self.compose_file is None:
            return

        try:
            from python_on_whales import DockerClient

            docker = DockerClient(compose_files=[self.compose_file])

            if self.subject_name == "tikv":
                # Stop YCSB container by name
                try:
                    docker.stop("ycsb-run", time=2)
                    docker.remove("ycsb-run", force=True)
                    print("[TUI] Stopped YCSB load generator")
                except Exception:
                    pass  # Container may not exist

            elif self.subject_name == "ratelimiter":
                # Stop loadgen service
                try:
                    docker.compose.stop(["loadgen"])
                    print("[TUI] Stopped loadgen service")
                except Exception:
                    pass  # Service may not be running

        except Exception as e:
            print(f"[TUI] Warning: Could not stop load generators: {e}")
