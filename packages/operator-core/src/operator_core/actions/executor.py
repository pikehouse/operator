"""
Action executor for orchestrating proposal and execution flow.

This module provides ActionExecutor, the central coordinator for action
lifecycle management:
- Propose actions from diagnosis recommendations
- Validate parameters before execution
- Execute approved actions against subjects
- Cancel pending actions

The executor integrates with:
- ActionRegistry for action validation
- SafetyController for execution gating
- ActionAuditor for lifecycle logging
- ActionDB for persistence

Per project patterns:
- Check safety controller before any execution
- Validate parameters via registry before storing
- Log all lifecycle events via auditor
"""

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from operator_core.actions.audit import ActionAuditor
from operator_core.actions.registry import ActionDefinition, ActionRegistry
from operator_core.actions.retry import RetryConfig
from operator_core.actions.safety import ObserveOnlyError, SafetyController
from operator_core.actions.tools import execute_tool, get_general_tools
from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)
from operator_core.actions.validation import ValidationError, validate_action_params

if TYPE_CHECKING:
    from operator_core.agent.diagnosis import ActionRecommendation
    from operator_core.db.actions import ActionDB
    from operator_core.subject import Subject


class ApprovalRequiredError(Exception):
    """Raised when action requires approval but hasn't been approved."""

    def __init__(self, proposal_id: int, action_name: str) -> None:
        self.proposal_id = proposal_id
        self.action_name = action_name
        super().__init__(
            f"Action '{action_name}' (proposal {proposal_id}) requires approval. "
            f"Run: operator actions approve {proposal_id}"
        )


class ActionExecutor:
    """
    Executor for orchestrating action proposal and execution.

    The ActionExecutor coordinates the full action lifecycle:
    1. propose_action - Create proposal from recommendation
    2. validate_proposal - Verify parameters (pre-execution check)
    3. execute_proposal - Run action against subject (future)
    4. cancel_proposal - Halt pending action

    All operations are gated by SafetyController and logged via ActionAuditor.

    Example:
        executor = ActionExecutor(db_path, registry, safety, auditor)

        # From diagnosis
        proposal = await executor.propose_action(recommendation, ticket_id=1)

        # Before execution
        validated = await executor.validate_proposal(proposal.id)

        # Execute (Phase 14 will trigger this)
        record = await executor.execute_proposal(proposal.id, subject)
    """

    def __init__(
        self,
        db_path: Path,
        registry: ActionRegistry,
        safety: SafetyController,
        auditor: ActionAuditor,
        approval_mode: bool | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """
        Initialize the action executor.

        Args:
            db_path: Path to SQLite database
            registry: ActionRegistry for action discovery and validation
            safety: SafetyController for execution gating
            auditor: ActionAuditor for lifecycle logging
            approval_mode: If True, require approval before execution.
                           If None, read from OPERATOR_APPROVAL_MODE env var.
                           Default is False (autonomous execution).
            retry_config: Configuration for retry behavior. If None, uses defaults.
        """
        self.db_path = db_path
        self._registry = registry
        self._safety = safety
        self._auditor = auditor
        self._retry_config = retry_config or RetryConfig()

        # Resolve approval mode from parameter or environment
        if approval_mode is None:
            self._approval_mode = (
                os.environ.get("OPERATOR_APPROVAL_MODE", "false").lower() == "true"
            )
        else:
            self._approval_mode = approval_mode

    def _requires_approval(self, proposal: ActionProposal) -> bool:
        """
        Check if a proposal requires human approval before execution.

        Currently implements global approval mode:
        - approval_mode=False: no approval needed (autonomous)
        - approval_mode=True: all actions need approval

        Per research recommendation, start with global mode only.
        Per-action requires_approval can be added later.

        Args:
            proposal: The proposal to check

        Returns:
            True if approval is required, False otherwise
        """
        return self._approval_mode

    def get_all_definitions(self) -> list[ActionDefinition]:
        """
        Get all available action definitions (subject + general tools).

        Returns:
            Combined list of ActionDefinition from registry and general tools
        """
        subject_actions = self._registry.get_definitions()
        general_tools = get_general_tools()
        return subject_actions + general_tools

    async def propose_action(
        self,
        recommendation: "ActionRecommendation",
        ticket_id: int | None = None,
    ) -> ActionProposal:
        """
        Create an action proposal from a diagnosis recommendation.

        Validates that the action exists in the registry and parameters
        match expected types before storing. Respects observe-only mode.

        Args:
            recommendation: ActionRecommendation from diagnosis output
            ticket_id: Optional ticket ID for traceability

        Returns:
            Created ActionProposal with ID populated

        Raises:
            ObserveOnlyError: If safety mode is OBSERVE
            ValueError: If action not found in registry
            ValidationError: If parameters fail validation
        """
        # Check safety - proposals blocked in observe mode
        self._safety.check_can_execute()

        # Validate action exists in registry or general tools
        definition = self._registry.get_definition(recommendation.action_name)

        # Check if it's a general tool
        if definition is None:
            for tool in get_general_tools():
                if tool.name == recommendation.action_name:
                    definition = tool
                    break

        if definition is None:
            raise ValueError(
                f"Unknown action '{recommendation.action_name}'. "
                f"Available actions: {self._registry.list_action_names()}"
            )

        # Validate parameters against definition
        validate_action_params(definition, recommendation.parameters)

        # Create proposal (use definition's action_type)
        proposal = ActionProposal(
            ticket_id=ticket_id,
            action_name=recommendation.action_name,
            action_type=definition.action_type,
            parameters=recommendation.parameters,
            reason=recommendation.reason,
            status=ActionStatus.PROPOSED,
            proposed_at=datetime.now(),
            proposed_by="agent",
        )

        # Store in database (lazy import to avoid circular import)
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            created = await db.create_proposal(proposal)

        # Log proposal created event
        await self._auditor.log_proposal_created(created)

        return created

    async def propose_workflow(
        self,
        name: str,
        description: str,
        action_recommendations: list["ActionRecommendation"],
        ticket_id: int | None = None,
    ) -> int:
        """
        Create a workflow proposal from multiple action recommendations.

        Validates all actions exist and parameters are valid before
        creating the workflow. All actions in a workflow share approval
        (approve workflow = approve all actions).

        Args:
            name: Workflow name (e.g., "drain_and_verify")
            description: What this workflow accomplishes
            action_recommendations: List of ActionRecommendations to include
            ticket_id: Optional ticket ID for traceability

        Returns:
            Created workflow ID

        Raises:
            ObserveOnlyError: If safety mode is OBSERVE
            ValueError: If any action not found in registry
            ValidationError: If any action parameters fail validation
        """
        # Check safety - proposals blocked in observe mode
        self._safety.check_can_execute()

        if not action_recommendations:
            raise ValueError("Workflow must contain at least one action")

        # Validate all actions exist and parameters are valid
        for rec in action_recommendations:
            definition = self._registry.get_definition(rec.action_name)
            if definition is None:
                raise ValueError(
                    f"Unknown action '{rec.action_name}' in workflow. "
                    f"Available actions: {self._registry.list_action_names()}"
                )
            validate_action_params(definition, rec.parameters)

        # Create proposals from recommendations
        proposals = [
            ActionProposal(
                ticket_id=ticket_id,
                action_name=rec.action_name,
                action_type=ActionType.SUBJECT,
                parameters=rec.parameters,
                reason=rec.reason,
                status=ActionStatus.PROPOSED,
                proposed_at=datetime.now(),
                proposed_by="agent",
            )
            for rec in action_recommendations
        ]

        # Create workflow in database
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            workflow_id = await db.create_workflow(
                name=name,
                description=description,
                actions=proposals,
                ticket_id=ticket_id,
            )

        # Log workflow created
        await self._auditor.log_event(
            proposal_id=None,
            event_type="workflow_created",
            event_data={
                "workflow_id": workflow_id,
                "name": name,
                "action_count": len(proposals),
            },
            actor="agent",
        )

        return workflow_id

    async def validate_proposal(self, proposal_id: int) -> ActionProposal:
        """
        Validate a proposal's parameters (pre-execution check).

        Re-validates parameters against the current registry definition
        in case action definitions have changed since proposal.

        Args:
            proposal_id: ID of the proposal to validate

        Returns:
            Updated ActionProposal with VALIDATED status

        Raises:
            ValueError: If proposal not found or in wrong state
            ValidationError: If parameters fail validation
        """
        # Lazy import to avoid circular import
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            proposal = await db.get_proposal(proposal_id)

            if proposal is None:
                raise ValueError(f"Proposal {proposal_id} not found")

            if proposal.status != ActionStatus.PROPOSED:
                raise ValueError(
                    f"Proposal {proposal_id} is {proposal.status.value}, "
                    "expected 'proposed'"
                )

            # Re-validate parameters
            definition = self._registry.get_definition(proposal.action_name)
            if definition is None:
                raise ValueError(
                    f"Action '{proposal.action_name}' no longer available"
                )

            validate_action_params(definition, proposal.parameters)

            # Update status to validated
            await db.update_proposal_status(proposal_id, ActionStatus.VALIDATED)
            updated = await db.get_proposal(proposal_id)

        # Log validation passed
        await self._auditor.log_validation_passed(proposal_id)

        return updated

    async def execute_proposal(
        self,
        proposal_id: int,
        subject: "Subject",
    ) -> ActionRecord:
        """
        Execute a validated proposal against the subject.

        Note: This method exists for foundation completeness. Actual
        execution is triggered by the approval workflow in Phase 14.

        Args:
            proposal_id: ID of the proposal to execute
            subject: Subject instance to execute action against

        Returns:
            ActionRecord with execution results

        Raises:
            ObserveOnlyError: If safety mode is OBSERVE
            ApprovalRequiredError: If approval mode is on but proposal not approved
            ValueError: If proposal not found or not validated
        """
        # Check safety - execution blocked in observe mode
        self._safety.check_can_execute()

        # Lazy import to avoid circular import
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            proposal = await db.get_proposal(proposal_id)

            if proposal is None:
                raise ValueError(f"Proposal {proposal_id} not found")

            # Check if approval is required
            if self._requires_approval(proposal):
                if not proposal.is_approved:
                    raise ApprovalRequiredError(proposal.id, proposal.action_name)

            if proposal.status != ActionStatus.VALIDATED:
                raise ValueError(
                    f"Proposal {proposal_id} is {proposal.status.value}, "
                    "expected 'validated'"
                )

            # Update status to executing
            await db.update_proposal_status(proposal_id, ActionStatus.EXECUTING)

            # Log execution started
            await self._auditor.log_execution_started(proposal_id)

            # Create execution record
            record = ActionRecord(
                proposal_id=proposal_id,
                started_at=datetime.now(),
            )
            record = await db.create_record(record)

            # Execute the action
            start_time = datetime.now()
            success = False
            error_message: str | None = None
            result_data: dict[str, Any] | None = None

            try:
                if proposal.action_type == ActionType.TOOL:
                    # Execute general tool
                    result = await execute_tool(
                        proposal.action_name,
                        proposal.parameters,
                    )
                else:
                    # Execute subject method dynamically
                    method = getattr(subject, proposal.action_name, None)
                    if method is None:
                        raise ValueError(
                            f"Subject has no method '{proposal.action_name}'"
                        )
                    result = await method(**proposal.parameters)

                success = True
                result_data = {"result": result} if result is not None else None

            except Exception as e:
                error_message = f"{type(e).__name__}: {e}"

            # Calculate duration
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            # Update record with results
            await db.update_record(
                record.id,
                success=success,
                error_message=error_message,
                result_data=result_data,
            )

            # Update proposal status
            final_status = ActionStatus.COMPLETED if success else ActionStatus.FAILED
            await db.update_proposal_status(proposal_id, final_status)

            # Log completion
            await self._auditor.log_execution_completed(
                proposal_id,
                success=success,
                error=error_message,
                duration_ms=duration_ms,
                result=result_data,
            )

            # Fetch final record
            final_record = await db.get_record(record.id)

        return final_record

    async def schedule_next_retry(
        self,
        proposal_id: int,
        error_message: str,
    ) -> datetime | None:
        """
        Schedule the next retry attempt for a failed action.

        Uses exponential backoff with jitter to calculate the next retry time.
        If max retries exceeded, returns None and logs final failure.

        Args:
            proposal_id: ID of the failed proposal
            error_message: Error message from the failed attempt

        Returns:
            datetime of next retry, or None if max retries exceeded
        """
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            proposal = await db.get_proposal(proposal_id)

            if proposal is None:
                raise ValueError(f"Proposal {proposal_id} not found")

            # Increment retry count and record error
            await db.increment_retry_count(proposal_id, error_message)

            # Check if more retries allowed
            new_retry_count = proposal.retry_count + 1
            if not self._retry_config.should_retry(new_retry_count):
                # Max retries exceeded
                await self._auditor.log_event(
                    proposal_id=proposal_id,
                    event_type="retry_exhausted",
                    event_data={
                        "retry_count": new_retry_count,
                        "max_retries": self._retry_config.max_attempts,
                        "last_error": error_message,
                    },
                    actor="system",
                )
                return None

            # Calculate next retry time
            next_retry = self._retry_config.calculate_next_retry(new_retry_count)
            await db.update_next_retry(proposal_id, next_retry)

            # Log retry scheduled
            await self._auditor.log_event(
                proposal_id=proposal_id,
                event_type="retry_scheduled",
                event_data={
                    "retry_count": new_retry_count,
                    "next_retry_at": next_retry.isoformat(),
                },
                actor="system",
            )

            return next_retry

    async def cancel_proposal(self, proposal_id: int, reason: str) -> None:
        """
        Cancel a pending action proposal.

        Args:
            proposal_id: ID of the proposal to cancel
            reason: Reason for cancellation

        Raises:
            ValueError: If proposal not found or already terminal
        """
        # Lazy import to avoid circular import
        from operator_core.db.actions import ActionDB

        async with ActionDB(self.db_path) as db:
            proposal = await db.get_proposal(proposal_id)

            if proposal is None:
                raise ValueError(f"Proposal {proposal_id} not found")

            if proposal.status in (
                ActionStatus.COMPLETED,
                ActionStatus.FAILED,
                ActionStatus.CANCELLED,
            ):
                raise ValueError(
                    f"Proposal {proposal_id} is already {proposal.status.value}"
                )

            await db.update_proposal_status(proposal_id, ActionStatus.CANCELLED)

        # Log cancellation
        await self._auditor.log_cancelled(proposal_id, reason)
