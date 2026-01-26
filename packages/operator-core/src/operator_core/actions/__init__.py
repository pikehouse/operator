"""
Actions module for the agent execution framework.

This module provides the data structures for action management:
- ActionStatus: Lifecycle states for actions
- ActionType: Source types for actions
- ActionProposal: Proposed actions awaiting validation/execution
- ActionRecord: Execution records for completed actions

Exports:
    ActionStatus: Enum of action lifecycle states
    ActionType: Enum of action source types
    ActionProposal: Pydantic model for action proposals
    ActionRecord: Pydantic model for execution records
"""

from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)

__all__ = [
    "ActionProposal",
    "ActionRecord",
    "ActionStatus",
    "ActionType",
]
