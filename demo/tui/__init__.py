"""
TUI components for demo visualization.

This module provides the terminal UI infrastructure for operator demos:
- OutputBuffer: Ring buffer for capturing daemon output
- KeyboardTask: Async keyboard reader for TUI control
- Layout utilities: 5-panel dashboard layout
- SubprocessManager: Daemon process lifecycle management
"""

from demo.tui.buffer import OutputBuffer
from demo.tui.keyboard import KeyboardTask
from demo.tui.layout import (
    create_layout,
    make_cluster_panel,
    make_panel,
    make_workload_panel,
)
from demo.tui.subprocess import ManagedProcess, SubprocessManager

__all__ = [
    "OutputBuffer",
    "KeyboardTask",
    "create_layout",
    "make_cluster_panel",
    "make_panel",
    "make_workload_panel",
    "ManagedProcess",
    "SubprocessManager",
]
