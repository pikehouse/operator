"""
Generic demo runner for multi-subject chaos demonstrations.

This module provides a DemoRunner class that orchestrates chapter-based
demos with keyboard-driven progression, health polling, and chapter callbacks.

The runner is subject-agnostic - it accepts a list of chapters and a health
poller protocol implementation, making it reusable across TiKV, rate limiter,
and future subjects.

This is a SIMPLIFIED runner compared to TUIController - it does NOT spawn
subprocess monitors/agents or use the full 5-panel layout. Full TUI integration
comes in later plans. This runner is for testing the chapter/chaos abstraction.
"""

import asyncio
import signal
import sys
from typing import Callable

from rich.console import Console

from demo.types import Chapter, DemoState, HealthPollerProtocol


class DemoRunner:
    """
    Generic demo runner with chapter progression and health polling.

    This runner orchestrates the demo flow:
    1. Initialize DemoState with provided chapters
    2. Start health poller in background
    3. Display current chapter and await keyboard input
    4. Handle chapter callbacks (on_enter) when entering new chapters
    5. Auto-advance chapters that have auto_advance=True
    6. Gracefully shutdown on SIGINT/SIGTERM

    The runner is subject-agnostic - health details and chapter callbacks
    are provided by the caller for their specific subject.
    """

    def __init__(
        self,
        subject_name: str,
        chapters: list[Chapter],
        health_poller: HealthPollerProtocol,
        on_narration_update: Callable[[str], None] | None = None,
    ):
        """
        Initialize demo runner.

        Args:
            subject_name: Name of subject for display title (e.g., "TiKV", "Rate Limiter")
            chapters: List of chapters defining demo progression
            health_poller: Subject-specific health polling implementation
            on_narration_update: Optional callback when narration text changes
        """
        self.subject_name = subject_name
        self.chapters = chapters
        self.health_poller = health_poller
        self.on_narration_update = on_narration_update

        self.console = Console()
        self.demo_state = DemoState(chapters=chapters)
        self.shutdown_event = asyncio.Event()
        self._poller_task: asyncio.Task[None] | None = None

    def _setup_signal_handlers(self) -> None:
        """
        Setup signal handlers for graceful shutdown.

        Handles SIGINT (Ctrl+C) and SIGTERM to trigger shutdown_event.
        """

        def signal_handler(signum: int, frame: object) -> None:
            self.console.print("\n[yellow]Shutdown signal received...[/yellow]")
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def _handle_chapter_enter(self, chapter: Chapter) -> None:
        """
        Handle entering a new chapter.

        If chapter has on_enter callback, run it. If chapter has auto_advance,
        advance to next chapter after callback completes.

        Args:
            chapter: Chapter being entered
        """
        if chapter.on_enter is not None:
            try:
                await chapter.on_enter()
            except Exception as e:
                self.console.print(f"[red]Error in chapter callback: {e}[/red]")

            # Auto-advance if configured
            if chapter.auto_advance:
                await asyncio.sleep(0.5)  # Brief pause for readability
                self.demo_state.advance()
                await self._display_current_chapter()

    async def _display_current_chapter(self) -> None:
        """
        Display current chapter title and narration.

        Calls on_narration_update callback if provided to notify listeners.
        """
        chapter = self.demo_state.get_current()
        progress = self.demo_state.get_progress()

        self.console.clear()
        self.console.print(f"\n[bold cyan]{self.subject_name} Demo {progress}[/bold cyan]")
        self.console.print(f"[bold]{chapter.title}[/bold]\n")
        self.console.print(chapter.narration)
        self.console.print(f"\n{chapter.key_hint}\n")

        if self.on_narration_update:
            self.on_narration_update(chapter.narration)

    async def _process_input(self) -> None:
        """
        Process keyboard input for chapter navigation.

        Handles:
        - SPACE/ENTER: Advance to next chapter (if not blocked)
        - Q: Quit demo
        """
        chapter = self.demo_state.get_current()

        # Read single character (blocking - runs in executor to not block event loop)
        loop = asyncio.get_event_loop()
        char = await loop.run_in_executor(None, sys.stdin.read, 1)

        if char.lower() == "q":
            self.console.print("[yellow]Quitting demo...[/yellow]")
            self.shutdown_event.set()
        elif char in (" ", "\n", "\r"):
            # Advance if not blocked and not at end
            if not chapter.blocks_advance and not self.demo_state.is_complete():
                advanced = self.demo_state.advance()
                if advanced:
                    await self._display_current_chapter()
                    # Handle on_enter for new chapter
                    new_chapter = self.demo_state.get_current()
                    await self._handle_chapter_enter(new_chapter)

    async def run(self) -> None:
        """
        Run the demo.

        Main event loop that:
        1. Sets up signal handlers
        2. Starts health poller in background
        3. Displays first chapter
        4. Handles on_enter for first chapter
        5. Processes keyboard input until shutdown or completion
        6. Cleans up resources
        """
        self._setup_signal_handlers()

        # Start health poller in background
        self._poller_task = asyncio.create_task(self.health_poller.run())

        # Display first chapter
        await self._display_current_chapter()

        # Handle on_enter for first chapter
        first_chapter = self.demo_state.get_current()
        await self._handle_chapter_enter(first_chapter)

        # Main input loop
        try:
            while not self.shutdown_event.is_set() and not self.demo_state.is_complete():
                await self._process_input()

            if self.demo_state.is_complete():
                self.console.print("[green]Demo complete![/green]")
        finally:
            # Cleanup
            self.health_poller.stop()
            if self._poller_task and not self._poller_task.done():
                self._poller_task.cancel()
                try:
                    await self._poller_task
                except asyncio.CancelledError:
                    pass

            self.console.print("[dim]Goodbye![/dim]")
