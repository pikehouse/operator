"""
TUI module providing reusable components for terminal dashboards.

This module provides building blocks for TUI applications:
- OutputBuffer: Ring buffer for capturing daemon output
- create_layout: Factory for panel layout structures
- make_panel, make_cluster_panel, make_workload_panel: Panel creation helpers
- ManagedProcess, SubprocessManager: Subprocess lifecycle management
- KeyboardTask: Non-blocking keyboard input handling

Demo-specific logic (chapters, health polling, fault injection) lives in the
demo/ module at project root, not here.
"""

from operator_core.tui.buffer import OutputBuffer
from operator_core.tui.keyboard import KeyboardTask
from operator_core.tui.layout import (
    create_layout,
    make_cluster_panel,
    make_panel,
    make_workload_panel,
)
from operator_core.tui.subprocess import ManagedProcess, SubprocessManager

__all__ = [
    "KeyboardTask",
    "ManagedProcess",
    "OutputBuffer",
    "SubprocessManager",
    "create_layout",
    "make_cluster_panel",
    "make_panel",
    "make_workload_panel",
]
