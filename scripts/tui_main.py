#!/usr/bin/env python3
"""
Entry point for TUI demo.

This must be a separate file (not -c inline) to ensure stdin is properly
connected as a TTY for keyboard input via readchar.
"""

import asyncio

from operator_core.tui import TUIController


async def main() -> None:
    """Run the TUI controller."""
    controller = TUIController()
    await controller.run()


if __name__ == "__main__":
    asyncio.run(main())
