"""
General-purpose tools for agent workflows.

This module provides tools that work independently of the subject,
enabling the agent to perform common operations like:
- Waiting between actions (for timing/pacing)
- Logging messages to the audit trail

Per ACT-03: Agent can use general tools beyond subject-defined actions.

These tools have ActionType.TOOL and are discoverable via get_general_tools().
"""

import asyncio
from datetime import datetime
from typing import Any

from operator_core.actions.registry import ActionDefinition, ParamDef
from operator_core.actions.types import ActionType


def get_general_tools() -> list[ActionDefinition]:
    """
    Get list of general-purpose tool definitions.

    These tools are available regardless of subject and can be used
    in any workflow for common operations.

    Returns:
        List of ActionDefinition for general tools
    """
    return [
        ActionDefinition(
            name="wait",
            description="Wait for a specified duration before continuing. Useful for timing between actions or waiting for systems to stabilize.",
            parameters={
                "seconds": ParamDef(
                    type="int",
                    description="Number of seconds to wait (1-300)",
                    required=True,
                ),
                "reason": ParamDef(
                    type="str",
                    description="Why we're waiting (for audit trail)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="low",
            requires_approval=False,
        ),
        ActionDefinition(
            name="log_message",
            description="Log a message to the audit trail. Useful for marking workflow progress or recording observations.",
            parameters={
                "message": ParamDef(
                    type="str",
                    description="Message to log",
                    required=True,
                ),
                "level": ParamDef(
                    type="str",
                    description="Log level: info, warning, error (default: info)",
                    required=False,
                ),
            },
            action_type=ActionType.TOOL,
            risk_level="low",
            requires_approval=False,
        ),
    ]


async def execute_wait(seconds: int, reason: str | None = None) -> dict[str, Any]:
    """
    Execute the wait tool.

    Pauses execution for the specified number of seconds.

    Args:
        seconds: Number of seconds to wait (capped at 300)
        reason: Optional reason for the wait

    Returns:
        Dict with wait duration and timestamp
    """
    # Cap at 5 minutes to prevent very long waits
    capped_seconds = min(seconds, 300)
    if capped_seconds != seconds:
        print(f"Wait capped from {seconds}s to {capped_seconds}s (max 300s)")

    start = datetime.now()
    print(f"Waiting {capped_seconds}s" + (f" ({reason})" if reason else ""))

    await asyncio.sleep(capped_seconds)

    return {
        "waited_seconds": capped_seconds,
        "reason": reason,
        "started_at": start.isoformat(),
        "completed_at": datetime.now().isoformat(),
    }


async def execute_log_message(
    message: str,
    level: str | None = None,
) -> dict[str, Any]:
    """
    Execute the log_message tool.

    Logs a message at the specified level.

    Args:
        message: Message to log
        level: Log level (info, warning, error)

    Returns:
        Dict with logged message and timestamp
    """
    level = level or "info"
    timestamp = datetime.now()

    # Print with level prefix
    prefix = {
        "info": "[INFO]",
        "warning": "[WARN]",
        "error": "[ERROR]",
    }.get(level.lower(), "[INFO]")

    print(f"{prefix} {message}")

    return {
        "message": message,
        "level": level,
        "timestamp": timestamp.isoformat(),
    }


# Map tool names to their execution functions
TOOL_EXECUTORS = {
    "wait": execute_wait,
    "log_message": execute_log_message,
}


async def execute_tool(tool_name: str, parameters: dict[str, Any]) -> Any:
    """
    Execute a general tool by name.

    Args:
        tool_name: Name of the tool to execute
        parameters: Parameters to pass to the tool

    Returns:
        Tool execution result

    Raises:
        ValueError: If tool not found
    """
    executor = TOOL_EXECUTORS.get(tool_name)
    if executor is None:
        raise ValueError(
            f"Unknown tool '{tool_name}'. "
            f"Available tools: {list(TOOL_EXECUTORS.keys())}"
        )

    return await executor(**parameters)
