"""
KeyboardTask for async keyboard input in TUI.

This module provides non-blocking keyboard reading for integration
with the TUIController's asyncio TaskGroup.

Per RESEARCH.md Pattern 1: Async Keyboard Reader with Executor
- Uses loop.run_in_executor() to wrap blocking readchar.readkey()
- Sets cbreak mode for proper single-keypress detection
- Handles asyncio.CancelledError for TaskGroup cancellation

Per RESEARCH.md Pitfall 1: Blocking the Event Loop
- Never calls readchar.readkey() directly in async context
- Always uses executor for non-blocking integration

Per RESEARCH.md Pitfall 2: Race Condition on Shutdown
- Uses select() with timeout so thread always returns quickly
- Checks shutdown event in loop for clean exit
"""

import asyncio
import select
import sys
import termios
import tty
from typing import Callable


def _readkey_with_timeout(timeout: float) -> str | None:
    """
    Read a keypress with timeout.

    Uses select() to check if input is available, then reads from stdin.
    Does NOT change terminal modes - caller must ensure cbreak mode is set.

    Args:
        timeout: Maximum seconds to wait for input

    Returns:
        Key pressed, or None if timeout
    """
    # Check if stdin has data available
    if select.select([sys.stdin], [], [], timeout)[0]:
        # Read directly
        char = sys.stdin.read(1)
        # Handle escape sequences (arrow keys, etc.)
        if char == "\x1b":  # Escape
            if select.select([sys.stdin], [], [], 0.05)[0]:
                char += sys.stdin.read(1)
                if char == "\x1b[" and select.select([sys.stdin], [], [], 0.05)[0]:
                    char += sys.stdin.read(1)
        return char
    return None


class KeyboardTask:
    """
    Async keyboard reader for integration with TUIController TaskGroup.

    Designed to run alongside other tasks (subprocess readers, health poller)
    without blocking the event loop.

    Example:
        keyboard = KeyboardTask(on_key=handle_key)
        tg.create_task(keyboard.run())
        # Later:
        keyboard.stop()
    """

    def __init__(self, on_key: Callable[[str], None]) -> None:
        """
        Initialize keyboard task.

        Args:
            on_key: Callback invoked with each keypress
        """
        self._on_key = on_key
        self._shutdown = asyncio.Event()
        self._old_settings: list | None = None

    async def run(self) -> None:
        """
        Main task loop. Run inside TaskGroup.

        Sets cbreak mode once at startup, restores at shutdown.
        Uses executor with select-based timeout so threads always
        return quickly, enabling clean shutdown.
        """
        loop = asyncio.get_running_loop()

        # Set cbreak mode once at startup
        fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)

            while not self._shutdown.is_set():
                try:
                    # Use select-based timeout so thread returns quickly
                    key = await loop.run_in_executor(
                        None,
                        lambda: _readkey_with_timeout(0.3),
                    )
                    if key is not None:
                        self._on_key(key)
                except asyncio.CancelledError:
                    break  # TaskGroup cancelled us
        finally:
            # Restore terminal settings
            if self._old_settings is not None:
                termios.tcsetattr(fd, termios.TCSADRAIN, self._old_settings)

    def stop(self) -> None:
        """Signal task to stop."""
        self._shutdown.set()
