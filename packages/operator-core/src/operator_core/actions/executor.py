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

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from operator_core.actions.audit import ActionAuditor
from operator_core.actions.registry import ActionRegistry
from operator_core.actions.safety import ObserveOnlyError, SafetyController
from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)
from operator_core.actions.validation import ValidationError, validate_action_params
from operator_core.db.actions import ActionDB

if TYPE_CHECKING:
    from operator_core.agent.diagnosis import ActionRecommendation
    from operator_core.subject import Subject


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
    ) -> None:
        """
        Initialize the action executor.

        Args:
            db_path: Path to SQLite database
            registry: ActionRegistry for action discovery and validation
            safety: SafetyController for execution gating
            auditor: ActionAuditor for lifecycle logging
        """
        self.db_path = db_path
        self._registry = registry
        self._safety = safety
        self._auditor = auditor

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

        # Validate action exists in registry
        definition = self._registry.get_definition(recommendation.action_name)
        if definition is None:
            raise ValueError(
                f"Unknown action '{recommendation.action_name}'. "
                f"Available actions: {self._registry.list_action_names()}"
            )

        # Validate parameters against definition
        validate_action_params(definition, recommendation.parameters)

        # Create proposal
        proposal = ActionProposal(
            ticket_id=ticket_id,
            action_name=recommendation.action_name,
            action_type=ActionType.SUBJECT,
            parameters=recommendation.parameters,
            reason=recommendation.reason,
            status=ActionStatus.PROPOSED,
            proposed_at=datetime.now(),
            proposed_by="agent",
        )

        # Store in database
        async with ActionDB(self.db_path) as db:
            created = await db.create_proposal(proposal)

        # Log proposal created event
        await self._auditor.log_proposal_created(created)

        return created

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
            ValueError: If proposal not found or not validated
        """
        # Check safety - execution blocked in observe mode
        self._safety.check_can_execute()

        async with ActionDB(self.db_path) as db:
            proposal = await db.get_proposal(proposal_id)

            if proposal is None:
                raise ValueError(f"Proposal {proposal_id} not found")

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
                # Call subject method dynamically
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

    async def cancel_proposal(self, proposal_id: int, reason: str) -> None:
        """
        Cancel a pending action proposal.

        Args:
            proposal_id: ID of the proposal to cancel
            reason: Reason for cancellation

        Raises:
            ValueError: If proposal not found or already terminal
        """
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
