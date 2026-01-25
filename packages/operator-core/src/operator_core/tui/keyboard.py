"""
KeyboardTask for async keyboard input in TUI.

This module provides non-blocking keyboard reading for integration
with the TUIController's asyncio TaskGroup.

Per RESEARCH.md Pattern 1: Async Keyboard Reader with Executor
- Uses loop.run_in_executor() to wrap blocking readchar.readkey()
- Uses select() to check for input before blocking read
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
from typing import Callable

import readchar


def _readkey_with_timeout(timeout: float) -> str | None:
    """
    Read a keypress with timeout.

    Uses select() to check if input is available before calling
    readchar.readkey(). This ensures the function always returns
    within the timeout, even if no key is pressed.

    Args:
        timeout: Maximum seconds to wait for input

    Returns:
        Key pressed, or None if timeout
    """
    # Check if stdin has data available
    if select.select([sys.stdin], [], [], timeout)[0]:
        return readchar.readkey()
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

    async def run(self) -> None:
        """
        Main task loop. Run inside TaskGroup.

        Uses executor with select-based timeout so threads always
        return quickly, enabling clean shutdown.
        """
        loop = asyncio.get_running_loop()

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

    def stop(self) -> None:
        """Signal task to stop."""
        self._shutdown.set()
