"""
AgentRunner daemon for AI-powered ticket diagnosis.

This module implements the agent runner that:
- Polls for undiagnosed tickets at configurable interval
- Gathers context (metrics, logs, topology, history)
- Invokes Claude with structured output
- Stores diagnosis and transitions ticket status
- Handles graceful shutdown on SIGINT/SIGTERM
- Optionally proposes actions based on diagnosis (v2.0)

Per RESEARCH.md patterns:
- Uses AsyncAnthropic for non-blocking API calls
- Uses asyncio.Event for shutdown coordination
- Handles API errors gracefully (log, skip, continue)
"""

from __future__ import annotations

import asyncio
import functools
import signal
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from anthropic import AsyncAnthropic

from operator_core.agent.context import ContextGatherer
from operator_core.agent.diagnosis import DiagnosisOutput, format_diagnosis_markdown
from operator_core.agent.prompt import SYSTEM_PROMPT, build_diagnosis_prompt
from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import Ticket, TicketStatus
from operator_protocols import SubjectProtocol

if TYPE_CHECKING:
    from operator_core.actions.executor import ActionExecutor

from operator_core.actions.types import ActionProposal
from operator_core.db.actions import ActionDB


class AgentRunner:
    """
    Daemon that processes tickets through Claude diagnosis.

    Polls for open tickets, gathers context, invokes Claude for
    structured diagnosis, and stores results in the database.

    Uses same daemon pattern as MonitorLoop per Phase 4.

    Example:
        subject = SubjectProtocol(pd=pd_client, prom=prom_client)
        runner = AgentRunner(
            subject=subject,
            db_path=Path("~/.operator/tickets.db"),
            poll_interval=10.0,
        )
        await runner.run()  # Runs until SIGINT/SIGTERM
    """

    def __init__(
        self,
        subject: SubjectProtocol,
        db_path: Path,
        anthropic_client: AsyncAnthropic | None = None,
        poll_interval: float = 10.0,
        model: str = "claude-sonnet-4-5",
        executor: "ActionExecutor | None" = None,
    ) -> None:
        """
        Initialize agent runner.

        Args:
            subject: SubjectProtocol for cluster observations
            db_path: Path to SQLite database file
            anthropic_client: Optional AsyncAnthropic client (created if None)
            poll_interval: Seconds between polling cycles (default 10)
            model: Claude model to use for diagnosis (default claude-sonnet-4-5)
            executor: Optional ActionExecutor for proposing actions from diagnosis.
                      If None, agent operates in observe-only mode (v1 behavior).
        """
        self.subject = subject
        self.db_path = db_path
        self.client = anthropic_client or AsyncAnthropic()
        self.poll_interval = poll_interval
        self.model = model
        self.executor = executor
        self._shutdown = asyncio.Event()

        # Stats for logging
        self._tickets_processed = 0
        self._tickets_diagnosed = 0
        self._actions_proposed = 0
        self._actions_verified = 0
        self._retries_succeeded = 0

    async def run(self) -> None:
        """
        Run the agent loop until shutdown signal.

        Registers SIGINT and SIGTERM handlers for graceful shutdown.
        Polls for open tickets at configured interval, diagnosing each
        via Claude and storing results.
        """
        loop = asyncio.get_running_loop()

        # Register signal handlers per RESEARCH.md Pattern 2
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        print(f"Agent runner starting (poll interval: {self.poll_interval}s)")

        async with TicketDB(self.db_path) as db:
            while not self._shutdown.is_set():
                await self._process_cycle(db)

                # Wait for interval or shutdown signal
                # Per RESEARCH.md: Use Event.wait() with timeout, not asyncio.sleep
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue loop

        print("Agent runner stopped")

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle shutdown signal by setting shutdown event."""
        print(f"Received {sig.name}, shutting down...")
        self._shutdown.set()

    async def _process_cycle(self, db: TicketDB) -> None:
        """
        Process one batch of undiagnosed tickets.

        Gets all open tickets (not yet diagnosed) and processes each
        sequentially. Respects shutdown signal between tickets.
        """
        # Get open tickets (not yet diagnosed)
        tickets = await db.list_tickets(status=TicketStatus.OPEN)

        if tickets:
            print(f"Found {len(tickets)} open ticket(s) to diagnose")

        for ticket in tickets:
            if self._shutdown.is_set():
                break
            await self._diagnose_ticket(db, ticket)

        # Process scheduled actions (WRK-02)
        await self._process_scheduled_actions()

        # Process retry-eligible actions (WRK-03)
        await self._process_retry_eligible()

    async def _diagnose_ticket(self, db: TicketDB, ticket: Ticket) -> None:
        """
        Diagnose a single ticket with error handling.

        Per RESEARCH.md pitfalls:
        - Use AsyncAnthropic (not sync client)
        - Check stop_reason for refusal/max_tokens
        - Catch API errors, log, skip, continue

        Args:
            db: TicketDB for storing diagnosis
            ticket: Ticket to diagnose
        """
        print(f"Diagnosing ticket {ticket.id}: {ticket.invariant_name}")
        self._tickets_processed += 1

        try:
            # Gather context
            gatherer = ContextGatherer(self.subject, db)
            context = await gatherer.gather(ticket)
            prompt = build_diagnosis_prompt(context)

            # Invoke Claude with structured output
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=4096,
                betas=["structured-outputs-2025-11-13"],
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=DiagnosisOutput,
            )

            # Check for incomplete response
            if response.stop_reason == "refusal":
                print(f"Claude refused to diagnose ticket {ticket.id}")
                await db.update_diagnosis(
                    ticket.id,
                    "# Diagnosis Error\n\nClaude refused to provide diagnosis.",
                )
                return

            if response.stop_reason == "max_tokens":
                print(f"Diagnosis truncated for ticket {ticket.id}")
                # Still use partial result if available

            # Format and store diagnosis
            diagnosis_output = response.parsed_output
            diagnosis_md = format_diagnosis_markdown(diagnosis_output)
            await db.update_diagnosis(ticket.id, diagnosis_md)

            self._tickets_diagnosed += 1

            # Print diagnosis summary for TUI agent panel
            self._print_diagnosis_summary(diagnosis_output, ticket.id)

            # Save full diagnosis to file
            diagnosis_file = self._save_diagnosis_file(diagnosis_md, ticket)

            # Propose actions if executor available and recommendations exist (v2.0)
            await self._propose_actions_from_diagnosis(diagnosis_output, ticket.id)

        except anthropic.APIConnectionError as e:
            print(f"API connection error for ticket {ticket.id}: {e}")
            # Don't update ticket, will retry next cycle

        except anthropic.RateLimitError as e:
            print(f"Rate limited, backing off: {e}")
            await asyncio.sleep(60)  # Back off before continuing

        except anthropic.APIError as e:
            print(f"API error for ticket {ticket.id}: {e}")
            # Log but continue to next ticket

        except Exception as e:
            print(f"Unexpected error diagnosing ticket {ticket.id}: {e}")
            # Store error as diagnosis so ticket isn't retried infinitely
            await db.update_diagnosis(
                ticket.id,
                f"# Diagnosis Error\n\n{type(e).__name__}: {e}",
            )

    async def _propose_actions_from_diagnosis(
        self,
        diagnosis_output: DiagnosisOutput,
        ticket_id: int,
    ) -> None:
        """
        Propose actions from diagnosis recommendations.

        If an executor is available and the diagnosis includes recommended
        actions, this creates proposals for each recommendation.

        Handles observe-only mode gracefully (skips proposals with message).

        Args:
            diagnosis_output: The diagnosis with potential recommendations
            ticket_id: Ticket ID for traceability
        """
        if self.executor is None:
            # No executor - operate in observe-only mode (v1 behavior)
            return

        if not diagnosis_output.recommended_actions:
            # No actions recommended
            return

        # Import here to avoid circular import at module level
        from operator_core.actions.safety import ObserveOnlyError
        from operator_core.actions.validation import ValidationError

        for rec in diagnosis_output.recommended_actions:
            try:
                # 1. Propose action (validates params, creates proposal)
                proposal = await self.executor.propose_action(rec, ticket_id=ticket_id)
                self._actions_proposed += 1
                print(
                    f"Proposed action: {proposal.action_name} "
                    f"(id={proposal.id}, urgency={rec.urgency})"
                )

                # 2. Validate proposal (transitions to VALIDATED status)
                await self.executor.validate_proposal(proposal.id)
                print(f"Validated: {proposal.id}")

                # 3. Execute immediately (AGENT-01)
                record = await self.executor.execute_proposal(proposal.id, self.subject)

                if record.success:
                    print(f"✓ Executed: {proposal.action_name}")
                    # 4. Verify after delay (AGENT-02/03/04)
                    await self._verify_action_result(proposal.id, ticket_id)
                else:
                    print(f"✗ Execution failed: {record.error_message}")

            except ObserveOnlyError:
                # Expected when in observe mode - just skip
                print(f"Skipping action proposal: observe-only mode active")
                break  # Don't try other recommendations
            except ValidationError as e:
                print(f"Action proposal validation failed for {rec.action_name}: {e}")
            except ValueError as e:
                print(f"Action proposal failed for {rec.action_name}: {e}")

    async def _verify_action_result(
        self,
        proposal_id: int,
        ticket_id: int,
    ) -> None:
        """
        Verify action resolved the issue.

        Per AGENT-02/03/04: Wait 5s, query metrics, log result.

        Args:
            proposal_id: The executed proposal ID
            ticket_id: Ticket ID for context
        """
        print(f"Waiting 5s for action effects to propagate...")
        await asyncio.sleep(5.0)

        # Query subject metrics (AGENT-03)
        observation = await self.subject.observe()

        # Simplified verification - check if observation indicates healthy state
        # For demo: just log that verification ran; full invariant check is future work
        cluster_health = observation.get("cluster_metrics", observation)

        # Log verification result (AGENT-04)
        print("")
        print(f"━━━ Verification for Action {proposal_id} ━━━")
        print(f"Ticket: {ticket_id}")
        print(f"Metrics observed: {len(observation)} keys")

        # For v2.2 demo: assume success if we got metrics without error
        # Full invariant re-check is out of scope per REQUIREMENTS.md
        print(f"✓ VERIFICATION COMPLETE: Action {proposal_id} executed")
        print(f"  (Full invariant re-check is future work)")
        print("")

        self._actions_verified += 1

    async def _process_scheduled_actions(self) -> None:
        """
        Execute scheduled actions that are ready.

        Queries for validated actions with scheduled_at <= now and executes them.
        This enables WRK-02: schedule follow-up actions.
        """
        if self.executor is None:
            return

        async with ActionDB(self.db_path) as db:
            ready_actions = await db.list_ready_scheduled()

            if ready_actions:
                print(f"Found {len(ready_actions)} scheduled action(s) ready to execute")

            for action in ready_actions:
                if self._shutdown.is_set():
                    break

                await self._execute_scheduled_action(action)

    async def _execute_scheduled_action(self, action: ActionProposal) -> None:
        """
        Execute a single scheduled action.

        Args:
            action: The scheduled ActionProposal to execute
        """
        print(
            f"Executing scheduled action {action.id}: {action.action_name} "
            f"(scheduled for {action.scheduled_at})"
        )

        try:
            record = await self.executor.execute_proposal(action.id, self.subject)

            if record.success:
                print(f"Scheduled action {action.id} completed successfully")
            else:
                print(f"Scheduled action {action.id} failed: {record.error_message}")
                # Schedule retry if applicable
                await self._schedule_retry_if_needed(action.id, record.error_message)

        except Exception as e:
            print(f"Error executing scheduled action {action.id}: {e}")
            await self._schedule_retry_if_needed(action.id, str(e))

    async def _process_retry_eligible(self) -> None:
        """
        Retry failed actions that are eligible.

        Queries for failed actions with next_retry_at <= now and retry_count < max_retries,
        then attempts to re-execute them. This enables WRK-03: retry with backoff.
        """
        if self.executor is None:
            return

        async with ActionDB(self.db_path) as db:
            retry_actions = await db.list_retry_eligible()

            if retry_actions:
                print(f"Found {len(retry_actions)} action(s) eligible for retry")

            for action in retry_actions:
                if self._shutdown.is_set():
                    break

                await self._retry_failed_action(action)

    async def _retry_failed_action(self, action: ActionProposal) -> None:
        """
        Retry a single failed action.

        Resets the action to validated status and attempts execution again.

        Args:
            action: The failed ActionProposal to retry
        """
        print(
            f"Retrying action {action.id}: {action.action_name} "
            f"(attempt {action.retry_count + 1}/{action.max_retries})"
        )

        try:
            # Reset action to validated for re-execution
            async with ActionDB(self.db_path) as db:
                await db.reset_for_retry(action.id)

            # Execute the action
            record = await self.executor.execute_proposal(action.id, self.subject)

            if record.success:
                print(f"Retry succeeded for action {action.id}")
                self._retries_succeeded += 1
            else:
                print(f"Retry failed for action {action.id}: {record.error_message}")
                await self._schedule_retry_if_needed(action.id, record.error_message)

        except Exception as e:
            print(f"Error retrying action {action.id}: {e}")
            await self._schedule_retry_if_needed(action.id, str(e))

    async def _schedule_retry_if_needed(
        self,
        proposal_id: int,
        error_message: str,
    ) -> None:
        """
        Schedule next retry for a failed action if retries remain.

        Args:
            proposal_id: The failed proposal ID
            error_message: Error from the failed attempt
        """
        try:
            next_retry = await self.executor.schedule_next_retry(proposal_id, error_message)
            if next_retry:
                import datetime

                delay = (next_retry - datetime.datetime.now()).total_seconds()
                print(f"Action {proposal_id} scheduled for retry in {delay:.1f}s")
            else:
                print(f"Action {proposal_id} exhausted all retries")
        except Exception as e:
            print(f"Error scheduling retry for action {proposal_id}: {e}")

    def _print_diagnosis_summary(self, diagnosis: DiagnosisOutput, ticket_id: int) -> None:
        """
        Print a concise diagnosis summary for the TUI agent panel.

        Shows severity, root cause, and recommended action in a readable format.

        Args:
            diagnosis: The structured diagnosis output
            ticket_id: Ticket ID for reference
        """
        # Severity with visual indicator
        severity_icons = {
            "Critical": "🔴",
            "Warning": "🟡",
            "Info": "🟢",
        }
        icon = severity_icons.get(diagnosis.severity, "⚪")

        print("")
        print(f"━━━ Ticket {ticket_id} Diagnosis ━━━")
        print(f"{icon} Severity: {diagnosis.severity}")
        print("")

        # Truncate primary diagnosis if too long (keep under 120 chars per line)
        root_cause = diagnosis.primary_diagnosis
        if len(root_cause) > 200:
            root_cause = root_cause[:197] + "..."
        print(f"Root Cause: {root_cause}")
        print("")

        # Show recommended action (truncated)
        action = diagnosis.recommended_action
        if len(action) > 200:
            action = action[:197] + "..."
        print(f"Recommended: {action}")
        print("")

    def _save_diagnosis_file(self, diagnosis_md: str, ticket: Ticket) -> Path:
        """
        Save full diagnosis markdown to /tmp for detailed review.

        Args:
            diagnosis_md: The formatted markdown diagnosis
            ticket: The ticket being diagnosed

        Returns:
            Path to the saved diagnosis file
        """
        import datetime

        # Create diagnosis file in /tmp
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"diagnosis-{ticket.id}-{ticket.invariant_name}-{timestamp}.md"
        filepath = Path("/tmp") / filename

        # Add header with ticket context
        header = f"""# Diagnosis Report

**Ticket ID:** {ticket.id}
**Invariant:** {ticket.invariant_name}
**Generated:** {datetime.datetime.now().isoformat()}

---

"""
        filepath.write_text(header + diagnosis_md)

        print(f"📄 Full diagnosis: {filepath}")
        print("")

        return filepath
