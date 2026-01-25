"""
TUIController for managing TUI lifecycle with signal handling and subprocess management.

This module provides the main TUI controller that:
- Coordinates the 5-panel layout display
- Spawns and manages monitor/agent daemon subprocesses
- Streams subprocess output to TUI panels in real-time
- Handles graceful shutdown on SIGINT/SIGTERM
- Uses Rich Live for flicker-free rendering
- Provides public methods for panel updates

Per RESEARCH.md Pattern 4: Live Context with Signal Handlers
- Registers signal handlers BEFORE entering Live context
- Spawns subprocesses AFTER signal handlers, BEFORE Live context
- Uses asyncio.Event for shutdown coordination
- Uses TaskGroup for reader tasks alongside update loop

Per RESEARCH.md Pitfall 2: Signal Handler Registered Too Late
- Signal handler registration is the FIRST thing in run()
- This ensures Ctrl+C works even during startup

Per RESEARCH.md Pitfall 6: Process Spawn Inside Live Context
- Subprocess spawning happens BEFORE Live context
- Prevents terminal mode conflicts
"""

import asyncio
import functools
import signal

from rich.console import Console
from rich.live import Live

from operator_core.tui.chapters import DEMO_CHAPTERS, DemoState
from operator_core.tui.health import (
    ClusterHealthPoller,
    format_cluster_panel,
    parse_monitor_output_for_detection,
)
from operator_core.tui.keyboard import KeyboardTask
from operator_core.tui.layout import create_layout, make_cluster_panel, make_panel
from operator_core.tui.subprocess import SubprocessManager


class TUIController:
    """
    Controls TUI lifecycle with proper signal handling and subprocess management.

    Manages the 5-panel TUI layout, coordinates refresh cycles,
    spawns daemon subprocesses, streams their output to panels,
    and ensures clean terminal restoration on shutdown.

    Uses asyncio.Event for shutdown coordination per RESEARCH.md.
    Uses SubprocessManager for daemon lifecycle per RESEARCH.md.

    Example:
        controller = TUIController()
        await controller.run()  # Runs until Ctrl+C
    """

    def __init__(self, console: Console | None = None) -> None:
        """
        Initialize TUI controller.

        Args:
            console: Rich Console to use (creates default if None)
        """
        self.console = console if console is not None else Console()
        self._shutdown = asyncio.Event()
        self._layout = create_layout()
        self._subprocess_mgr: SubprocessManager | None = None
        self._health_poller: ClusterHealthPoller | None = None
        self._demo_state: DemoState | None = None
        self._keyboard: KeyboardTask | None = None

    async def run(self) -> None:
        """
        Run the TUI until shutdown signal.

        CRITICAL ORDER (per RESEARCH.md Pitfall 2 and Pitfall 6):
        1. Register signal handlers BEFORE Live context
        2. Spawn subprocesses AFTER signal handlers, BEFORE Live context
        3. Initialize panels with placeholder content
        4. Enter Live context for rendering
        5. Run TaskGroup with reader tasks and update loop
        6. Exit cleanly, terminate subprocesses, let Live context restore terminal

        Registers SIGINT and SIGTERM handlers for graceful shutdown.
        """
        loop = asyncio.get_running_loop()

        # 1. Register signal handlers BEFORE Live context
        # Per RESEARCH.md Pattern 4: This ensures Ctrl+C works even during startup
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        # 2. Spawn subprocesses AFTER signal handlers, BEFORE Live context
        # Per RESEARCH.md Pitfall 6: Prevents terminal mode conflicts
        self._subprocess_mgr = SubprocessManager()
        monitor_proc = await self._subprocess_mgr.spawn(
            "monitor",
            ["-m", "operator_core.cli.main", "monitor", "run", "-i", "5"],
            buffer_size=50,
        )
        agent_proc = await self._subprocess_mgr.spawn(
            "agent",
            ["-m", "operator_core.cli.main", "agent", "start", "-i", "5"],
            buffer_size=50,
        )

        # Create health poller for cluster status
        self._health_poller = ClusterHealthPoller(
            pd_endpoint="http://localhost:2379",
            poll_interval=2.0,
        )

        # Initialize demo state and keyboard
        self._demo_state = DemoState(chapters=list(DEMO_CHAPTERS))
        self._keyboard = KeyboardTask(on_key=self._handle_key)

        # 3. Initialize panels with placeholder content
        self._init_panels()

        # 4. Enter Live context for flicker-free rendering
        # screen=False: Don't use alternate screen for demo visibility
        with Live(
            self._layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,
        ) as live:
            # 5. Run TaskGroup with reader tasks and update loop
            # Per RESEARCH.md Pattern 4: TaskGroup automatically cancels sibling tasks
            try:
                async with asyncio.TaskGroup() as tg:
                    # Reader tasks for subprocess output
                    tg.create_task(self._subprocess_mgr.read_output(monitor_proc))
                    tg.create_task(self._subprocess_mgr.read_output(agent_proc))
                    # Health poller task
                    tg.create_task(self._health_poller.run())
                    # Keyboard task for demo flow control
                    tg.create_task(self._keyboard.run())
                    # Update loop
                    tg.create_task(self._update_loop(live))
            except* Exception:
                pass  # TaskGroup handles cancellation

        # 6. Clean shutdown - terminate subprocesses
        await self._subprocess_mgr.terminate_all()
        self.console.print("[green]TUI shutdown complete[/green]")

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

    def _handle_signal(self, sig: signal.Signals) -> None:
        """
        Handle shutdown signal by setting shutdown events.

        Sets both the controller shutdown event and the subprocess manager
        shutdown event for coordinated cleanup.

        Note: Signal handlers run outside async context, so we just set
        the events and let the run() loop handle cleanup.

        Args:
            sig: Signal received (SIGINT or SIGTERM)
        """
        self._shutdown.set()
        # Also signal subprocess manager to stop readers
        if self._subprocess_mgr is not None:
            self._subprocess_mgr.shutdown.set()
        # Stop health poller
        if self._health_poller is not None:
            self._health_poller.stop()
        # Stop keyboard reader
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
            make_panel("Waiting for workload...", "Workload", "yellow")
        )

    def _handle_key(self, key: str) -> None:
        """
        Handle keypress for demo flow control.

        Per RESEARCH.md Pattern 3: Key-to-Action Dispatch
        - SPACE/ENTER/RIGHT: Advance to next chapter
        - Q: Quit demo

        Args:
            key: Key pressed (raw character or escape sequence)
        """
        if self._demo_state is None:
            return

        # Check for advance keys
        # Space: " ", Enter: "\r" or "\n", Right arrow: "\x1b[C"
        if key in (" ", "\r", "\n", "\x1b[C"):
            self._demo_state.advance()
            self._update_narration()
        # Check for quit keys
        elif key in ("q", "Q"):
            self._shutdown.set()
            # Also signal all subsystems
            if self._subprocess_mgr is not None:
                self._subprocess_mgr.shutdown.set()
            if self._health_poller is not None:
                self._health_poller.stop()
            if self._keyboard is not None:
                self._keyboard.stop()

    def _update_narration(self) -> None:
        """
        Update narration panel with current chapter content.

        Per RESEARCH.md Pattern 4: Narration Panel Update
        - Shows chapter title, narration text, and key hints
        - Includes progress indicator [X/Y] for visual feedback
        """
        if self._demo_state is None:
            return

        chapter = self._demo_state.get_current()
        progress = self._demo_state.get_progress()
        # Build content with progress, title, narration, and key hint
        content = f"[bold cyan]{chapter.title}[/bold cyan] {progress}\n\n{chapter.narration}\n\n{chapter.key_hint}"
        self._layout["main"]["narration"].update(
            make_panel(content, "Chapter", "magenta")
        )

    def _refresh_panels(self) -> None:
        """
        Refresh panel contents from subprocess output and health status.

        Reads from monitor and agent subprocess buffers and updates
        their respective TUI panels with the latest output lines.
        Also updates cluster panel with health status from PD API.
        """
        if self._subprocess_mgr is None:
            return

        # Update monitor panel and check for detection events
        monitor_buf = self._subprocess_mgr.get_buffer("monitor")
        if monitor_buf:
            # Check recent lines for detection events
            for line in monitor_buf.get_lines(n=5):
                detection = parse_monitor_output_for_detection(line)
                if detection is not None and self._health_poller is not None:
                    self._health_poller.set_detection_active(detection)

            self._layout["main"]["monitor"].update(
                make_panel(monitor_buf.get_text(n=20), "Monitor", "blue")
            )

        # Update agent panel
        agent_buf = self._subprocess_mgr.get_buffer("agent")
        if agent_buf:
            self._layout["main"]["agent"].update(
                make_panel(agent_buf.get_text(n=20), "Agent", "green")
            )

        # Update cluster panel with health status
        if self._health_poller is not None:
            health = self._health_poller.get_health()
            if health:
                content = format_cluster_panel(health)
                self._layout["cluster"].update(
                    make_cluster_panel(
                        content,
                        has_issues=health.has_issues,
                        detection_active=self._health_poller.is_detection_active(),
                    )
                )

    def update_panel(
        self, name: str, content: str, title: str, style: str = "blue"
    ) -> None:
        """
        Update a specific panel's content.

        Public method for external callers to update panel content.
        Uses make_panel() to create styled panel.

        Args:
            name: Panel name ("cluster", "narration", "monitor", "agent", "workload")
            content: Text content for the panel
            title: Panel title
            style: Border style color (default "blue")

        Raises:
            KeyError: If panel name is not found
        """
        panel = make_panel(content, title, style)
        if name == "cluster":
            self._layout["cluster"].update(panel)
        else:
            self._layout["main"][name].update(panel)
