"""
TUIController for managing TUI lifecycle with signal handling.

This module provides the main TUI controller that:
- Coordinates the 5-panel layout display
- Handles graceful shutdown on SIGINT/SIGTERM
- Uses Rich Live for flicker-free rendering
- Provides public methods for panel updates

Per RESEARCH.md Pattern 4: Live Context with Signal Handlers
- Registers signal handlers BEFORE entering Live context
- Uses asyncio.Event for shutdown coordination
- Uses wait_for with timeout for interruptible refresh loop

Per RESEARCH.md Pitfall 2: Signal Handler Registered Too Late
- Signal handler registration is the FIRST thing in run()
- This ensures Ctrl+C works even during startup
"""

import asyncio
import functools
import signal

from rich.console import Console
from rich.live import Live

from operator_core.tui.layout import create_layout, make_panel


class TUIController:
    """
    Controls TUI lifecycle with proper signal handling.

    Manages the 5-panel TUI layout, coordinates refresh cycles,
    and ensures clean terminal restoration on shutdown.

    Uses asyncio.Event for shutdown coordination per RESEARCH.md.

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

    async def run(self) -> None:
        """
        Run the TUI until shutdown signal.

        CRITICAL ORDER (per RESEARCH.md Pitfall 2):
        1. Register signal handlers BEFORE Live context
        2. Initialize panels with placeholder content
        3. Enter Live context for rendering
        4. Run refresh loop with Event.wait() timeout
        5. Exit cleanly, let Live context restore terminal

        Registers SIGINT and SIGTERM handlers for graceful shutdown.
        """
        loop = asyncio.get_running_loop()

        # Register signal handlers BEFORE Live context
        # Per RESEARCH.md Pattern 4: This ensures Ctrl+C works even during startup
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        # Initialize panels with placeholder content
        self._init_panels()

        # Enter Live context for flicker-free rendering
        # screen=False: Don't use alternate screen for demo visibility
        with Live(
            self._layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,
        ) as live:
            # Per RESEARCH.md Pattern 4: wait_for with timeout for interruptible loop
            while not self._shutdown.is_set():
                self._refresh_panels()
                live.refresh()
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    pass  # Normal refresh interval

        # Terminal restored by Live.__exit__
        self.console.print("[green]TUI shutdown complete[/green]")

    def _handle_signal(self, sig: signal.Signals) -> None:
        """
        Handle shutdown signal by setting shutdown event.

        Note: Signal handlers run outside async context, so we just set
        the event and let the run() loop handle cleanup.

        Args:
            sig: Signal received (SIGINT or SIGTERM)
        """
        self._shutdown.set()

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
        Refresh all panel contents.

        For now, panels show static placeholder text.
        This will be extended in later phases to show real content
        from subprocess output buffers.
        """
        # Panels are static for now; later phases will update dynamically
        pass

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
