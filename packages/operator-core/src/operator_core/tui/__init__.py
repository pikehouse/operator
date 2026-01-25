"""
TUI module for multi-panel terminal dashboard.

This module provides the building blocks for the TUI demo:
- OutputBuffer: Ring buffer for capturing daemon output
- create_layout: Factory for 5-panel layout structure
- make_panel: Helper for creating styled panels
- TUIController: Main controller with signal handling
- ManagedProcess: Wrapper for subprocess with buffer
- SubprocessManager: Lifecycle management for daemon subprocesses
- ClusterHealthPoller: Async poller for cluster health status
- NodeHealth, NodeStatus, ClusterHealth: Health data types
- format_cluster_panel: Rich markup formatting for health display
- parse_monitor_output_for_detection: Monitor output parser for detection events
- WorkloadTracker: Workload throughput tracking with sparkline visualization
- FaultWorkflow: Fault injection and recovery workflow
"""

from operator_core.tui.buffer import OutputBuffer
from operator_core.tui.controller import TUIController
from operator_core.tui.fault import FaultWorkflow
from operator_core.tui.health import (
    ClusterHealth,
    ClusterHealthPoller,
    NodeHealth,
    NodeStatus,
    format_cluster_panel,
    parse_monitor_output_for_detection,
)
from operator_core.tui.layout import create_layout, make_panel
from operator_core.tui.subprocess import ManagedProcess, SubprocessManager
from operator_core.tui.workload import WorkloadTracker

__all__ = [
    "ClusterHealth",
    "ClusterHealthPoller",
    "FaultWorkflow",
    "ManagedProcess",
    "NodeHealth",
    "NodeStatus",
    "OutputBuffer",
    "SubprocessManager",
    "TUIController",
    "WorkloadTracker",
    "create_layout",
    "format_cluster_panel",
    "make_panel",
    "parse_monitor_output_for_detection",
]
