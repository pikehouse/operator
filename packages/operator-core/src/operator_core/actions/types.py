"""
Action types for the agent execution framework.

This module defines the core data structures for action management:
- ActionStatus: Enum for action lifecycle states
- ActionType: Enum for action source types
- ActionProposal: Proposed action awaiting validation/approval
- ActionRecord: Execution record for completed actions

Per project patterns:
- Use str enum for JSON serialization compatibility
- Pydantic BaseModel for validation and serialization
- Field() with descriptions for documentation
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionStatus(str, Enum):
    """
    Valid action lifecycle states.

    Actions flow through these states:
        proposed -> validated -> executing -> completed/failed/cancelled
    """

    PROPOSED = "proposed"
    """Action requested, awaiting validation/approval."""

    VALIDATED = "validated"
    """Parameters verified, ready to execute."""

    EXECUTING = "executing"
    """Currently running."""

    COMPLETED = "completed"
    """Finished successfully."""

    FAILED = "failed"
    """Execution error occurred."""

    CANCELLED = "cancelled"
    """Halted by kill switch or user."""


class ActionType(str, Enum):
    """
    Source type for actions.

    Determines how actions are validated and executed.
    """

    SUBJECT = "subject"
    """Subject-defined action (e.g., transfer_leader via PD API)."""

    TOOL = "tool"
    """General tool action (future use)."""

    WORKFLOW = "workflow"
    """Multi-step workflow action (future use)."""


class ActionProposal(BaseModel):
    """
    Proposed action awaiting validation and execution.

    Created when the AI agent recommends an action during diagnosis.
    Must be validated (parameters checked) and possibly approved
    before execution.

    Attributes:
        id: Database ID (None before insert)
        ticket_id: Associated ticket (optional, for traceability)
        action_name: Name matching Subject method (e.g., "transfer_leader")
        action_type: Source type for validation routing
        parameters: Action arguments (validated by action registry)
        reason: Why this action is proposed (from diagnosis)
        status: Current lifecycle state
        proposed_at: When created
        proposed_by: "agent" or "user" (for future approval workflows)
    """

    id: int | None = Field(default=None, description="Database ID (None before insert)")
    ticket_id: int | None = Field(
        default=None, description="Associated ticket ID for traceability"
    )
    action_name: str = Field(
        ..., description="Action name matching Subject method (e.g., 'transfer_leader')"
    )
    action_type: ActionType = Field(
        default=ActionType.SUBJECT, description="Source type for validation routing"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Action arguments to be validated"
    )
    reason: str = Field(
        ..., description="Why this action is proposed (from diagnosis)"
    )
    status: ActionStatus = Field(
        default=ActionStatus.PROPOSED, description="Current lifecycle state"
    )
    proposed_at: datetime = Field(
        default_factory=datetime.now, description="When the action was proposed"
    )
    proposed_by: str = Field(
        default="agent", description="Who proposed: 'agent' or 'user'"
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False  # Keep enum instances for type safety


class ActionRecord(BaseModel):
    """
    Execution record for a completed or in-progress action.

    Created when an ActionProposal starts execution. Updated with
    results when execution completes (success or failure).

    Attributes:
        id: Database ID (None before insert)
        proposal_id: Links to the ActionProposal being executed
        started_at: When execution started (None if not started)
        completed_at: When execution ended (None while executing)
        success: Outcome (None while executing, True/False after)
        error_message: Error details if failed
        result_data: Execution output data
    """

    id: int | None = Field(default=None, description="Database ID (None before insert)")
    proposal_id: int = Field(..., description="ID of the ActionProposal being executed")
    started_at: datetime | None = Field(
        default=None, description="Execution start time"
    )
    completed_at: datetime | None = Field(
        default=None, description="Execution end time"
    )
    success: bool | None = Field(
        default=None, description="Outcome: True=success, False=failure, None=executing"
    )
    error_message: str | None = Field(
        default=None, description="Error details if execution failed"
    )
    result_data: dict[str, Any] | None = Field(
        default=None, description="Execution output data"
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False  # Keep enum instances for type safety
