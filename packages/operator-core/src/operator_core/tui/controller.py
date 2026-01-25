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

from operator_core.tui.layout import create_layout, make_panel
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

    def _init_panels(self) -> None:
        """Initialize all panels with placeholder content."""
        self._layout["cluster"].update(
            make_panel("Loading...", "Cluster Status", "cyan")
        )
        self._layout["main"]["narration"].update(
            make_panel("Welcome to Operator TUI Demo", "Chapter", "magenta")
        )
        self._layout["main"]["monitor"].update(
            make_panel("Waiting for monitor...", "Monitor", "blue")
        )
        self._layout["main"]["agent"].update(
            make_panel("Waiting for agent...", "Agent", "green")
        )
        self._layout["main"]["workload"].update(
            make_panel("Waiting for workload...", "Workload", "yellow")
        )

    def _refresh_panels(self) -> None:
        """
        Refresh panel contents from subprocess output buffers.

        Reads from monitor and agent subprocess buffers and updates
        their respective TUI panels with the latest output lines.
        """
        if self._subprocess_mgr is None:
            return

        # Update monitor panel
        monitor_buf = self._subprocess_mgr.get_buffer("monitor")
        if monitor_buf:
            self._layout["main"]["monitor"].update(
                make_panel(monitor_buf.get_text(n=20), "Monitor", "blue")
            )

        # Update agent panel
        agent_buf = self._subprocess_mgr.get_buffer("agent")
        if agent_buf:
            self._layout["main"]["agent"].update(
                make_panel(agent_buf.get_text(n=20), "Agent", "green")
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
