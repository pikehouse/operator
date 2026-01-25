"""
TUI module for multi-panel terminal dashboard.

This module provides the building blocks for the TUI demo:
- OutputBuffer: Ring buffer for capturing daemon output
- create_layout: Factory for 5-panel layout structure
- make_panel: Helper for creating styled panels
- TUIController: Main controller with signal handling
- ManagedProcess: Wrapper for subprocess with buffer
- SubprocessManager: Lifecycle management for daemon subprocesses
"""

from operator_core.tui.buffer import OutputBuffer
from operator_core.tui.controller import TUIController
from operator_core.tui.layout import create_layout, make_panel
from operator_core.tui.subprocess import ManagedProcess, SubprocessManager

__all__ = [
    "ManagedProcess",
    "OutputBuffer",
    "SubprocessManager",
    "TUIController",
    "create_layout",
    "make_panel",
]
