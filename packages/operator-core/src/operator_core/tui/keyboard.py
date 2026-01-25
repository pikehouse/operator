"""
KeyboardTask for async keyboard input in TUI.

This module provides non-blocking keyboard reading for integration
with the TUIController's asyncio TaskGroup.

Per RESEARCH.md Pattern 1: Async Keyboard Reader with Executor
- Uses loop.run_in_executor() to wrap blocking readchar.readkey()
- Uses asyncio.wait_for() with timeout for responsive shutdown checking
- Handles asyncio.CancelledError for TaskGroup cancellation

Per RESEARCH.md Pitfall 1: Blocking the Event Loop
- Never calls readchar.readkey() directly in async context
- Always uses executor for non-blocking integration

Per RESEARCH.md Pitfall 2: Race Condition on Shutdown
- Uses asyncio.wait_for() with timeout around executor call
- Checks shutdown event in loop for clean exit
"""

import asyncio
from typing import Callable

import readchar


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

        Uses executor for blocking readkey(), with timeout for
        responsive shutdown checking.
        """
        loop = asyncio.get_running_loop()

        while not self._shutdown.is_set():
            try:
                # Timeout allows checking shutdown event
                key = await asyncio.wait_for(
                    loop.run_in_executor(None, readchar.readkey),
                    timeout=0.5,
                )
                self._on_key(key)
            except asyncio.TimeoutError:
                continue  # No key pressed, check shutdown
            except asyncio.CancelledError:
                break  # TaskGroup cancelled us

    def stop(self) -> None:
        """Signal task to stop."""
        self._shutdown.set()
