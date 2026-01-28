"""
Action types for the agent execution framework.

This module defines the core data structures for action management:
- ActionStatus: Enum for action lifecycle states
- ActionType: Enum for action source types
- WorkflowStatus: Enum for workflow lifecycle states
- ActionProposal: Proposed action awaiting validation/approval
- WorkflowProposal: Group of related actions to execute as a workflow
- ActionRecord: Execution record for completed actions

Per project patterns:
- Use str enum for JSON serialization compatibility
- Pydantic BaseModel for validation and serialization
- Field() with descriptions for documentation
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


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


class WorkflowStatus(str, Enum):
    """
    Valid workflow lifecycle states.

    Workflows flow through these states:
        pending -> in_progress -> completed/failed/cancelled
    """

    PENDING = "pending"
    """Workflow created, no actions started yet."""

    IN_PROGRESS = "in_progress"
    """At least one action is executing."""

    COMPLETED = "completed"
    """All actions completed successfully."""

    FAILED = "failed"
    """At least one action failed."""

    CANCELLED = "cancelled"
    """Workflow was cancelled."""


class ActionProposal(BaseModel):
    """
    Proposed action awaiting validation and execution.

    Created when the AI agent recommends an action during diagnosis.
    Must be validated (parameters checked) and possibly approved
    before execution.

    Identity Tracking (SAFE-03, SAFE-04):
    This model tracks dual identity for authorization chains:
    - requester_id: WHO initiated the request (user email, system name, or 'agent:autonomous')
    - agent_id: WHICH AI component executes it (if delegated to an agent)
    - requester_type: Type of requester ('user', 'system', or 'agent')

    This follows OAuth delegation patterns where requester_id is the resource owner
    and agent_id is the client acting on their behalf. Dual authorization verifies
    both requester permission AND agent capability before execution.

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
        requester_id: Identity of requester (user email, system name, or 'agent:autonomous')
        requester_type: Type of requester: 'user', 'system', or 'agent'
        agent_id: Identity of agent executing action (if delegated)
        approved_at: When the proposal was approved (None if not approved)
        approved_by: Who approved the proposal (typically "user")
        rejected_at: When the proposal was rejected (None if not rejected)
        rejected_by: Who rejected the proposal
        rejection_reason: Why the proposal was rejected
        workflow_id: Parent workflow ID if part of a chain (WRK-01)
        execution_order: Order within workflow, 0-indexed (WRK-01)
        depends_on_proposal_id: Proposal ID that must complete first (WRK-01)
        scheduled_at: Execute at this time, None for immediate (WRK-02)
        retry_count: Number of retry attempts so far (WRK-03)
        max_retries: Maximum retry attempts (WRK-03)
        next_retry_at: When to retry next, None if not scheduled (WRK-03)
        last_error: Error message from last failed attempt (WRK-03)
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

    # Identity tracking fields (SAFE-03, SAFE-04)
    requester_id: str = Field(
        default="unknown",
        description="Identity of requester (user email, system name, or 'agent:autonomous')",
    )
    requester_type: str = Field(
        default="agent",
        description="Type of requester: 'user', 'system', or 'agent'",
    )
    agent_id: str | None = Field(
        default=None,
        description="Identity of agent executing action (if delegated)",
    )

    approved_at: datetime | None = Field(
        default=None, description="When the proposal was approved"
    )
    approved_by: str | None = Field(
        default=None, description="Who approved: 'user' typically"
    )
    rejected_at: datetime | None = Field(
        default=None, description="When the proposal was rejected"
    )
    rejected_by: str | None = Field(
        default=None, description="Who rejected the proposal"
    )
    rejection_reason: str | None = Field(
        default=None, description="Why the proposal was rejected"
    )

    # Workflow fields (WRK-01)
    workflow_id: int | None = Field(
        default=None, description="Parent workflow ID if part of a chain"
    )
    execution_order: int = Field(
        default=0, description="Order within workflow (0-indexed)"
    )
    depends_on_proposal_id: int | None = Field(
        default=None, description="Proposal ID that must complete before this runs"
    )

    # Scheduling fields (WRK-02)
    scheduled_at: datetime | None = Field(
        default=None, description="Execute at this time (None = immediate)"
    )

    # Retry fields (WRK-03)
    retry_count: int = Field(default=0, description="Number of retry attempts so far")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    next_retry_at: datetime | None = Field(
        default=None, description="When to retry next (None = not scheduled)"
    )
    last_error: str | None = Field(
        default=None, description="Error message from last failed attempt"
    )

    @computed_field
    @property
    def is_approved(self) -> bool:
        """Return True if the proposal has been approved."""
        return self.approved_at is not None

    class Config:
        """Pydantic configuration."""

        use_enum_values = False  # Keep enum instances for type safety


class WorkflowProposal(BaseModel):
    """
    Group of related actions to execute as a workflow.

    A workflow is a sequence of ActionProposals that execute in order.
    Approval can happen at the workflow level (approve once, execute all).

    Attributes:
        id: Database ID (None before insert)
        name: Workflow name (e.g., "drain_and_verify")
        description: What this workflow accomplishes
        ticket_id: Associated ticket (optional, for traceability)
        status: Current lifecycle state
        created_at: When created
    """

    id: int | None = Field(default=None, description="Database ID")
    name: str = Field(..., description="Workflow name")
    description: str = Field(..., description="What this workflow accomplishes")
    ticket_id: int | None = Field(
        default=None, description="Associated ticket ID for traceability"
    )
    status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING, description="Current lifecycle state"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="When the workflow was created"
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = False


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
