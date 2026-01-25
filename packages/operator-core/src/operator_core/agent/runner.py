"""
AgentRunner daemon for AI-powered ticket diagnosis.

This module implements the agent runner that:
- Polls for undiagnosed tickets at configurable interval
- Gathers context (metrics, logs, topology, history)
- Invokes Claude with structured output
- Stores diagnosis and transitions ticket status
- Handles graceful shutdown on SIGINT/SIGTERM

Per RESEARCH.md patterns:
- Uses AsyncAnthropic for non-blocking API calls
- Uses asyncio.Event for shutdown coordination
- Handles API errors gracefully (log, skip, continue)
"""

import asyncio
import functools
import signal
from pathlib import Path

import anthropic
from anthropic import AsyncAnthropic

from operator_core.agent.context import ContextGatherer
from operator_core.agent.diagnosis import DiagnosisOutput, format_diagnosis_markdown
from operator_core.agent.prompt import SYSTEM_PROMPT, build_diagnosis_prompt
from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import Ticket, TicketStatus
from operator_tikv.subject import TiKVSubject


class AgentRunner:
    """
    Daemon that processes tickets through Claude diagnosis.

    Polls for open tickets, gathers context, invokes Claude for
    structured diagnosis, and stores results in the database.

    Uses same daemon pattern as MonitorLoop per Phase 4.

    Example:
        subject = TiKVSubject(pd=pd_client, prom=prom_client)
        runner = AgentRunner(
            subject=subject,
            db_path=Path("~/.operator/tickets.db"),
            poll_interval=10.0,
        )
        await runner.run()  # Runs until SIGINT/SIGTERM
    """

    def __init__(
        self,
        subject: TiKVSubject,
        db_path: Path,
        anthropic_client: AsyncAnthropic | None = None,
        poll_interval: float = 10.0,
        model: str = "claude-sonnet-4-5",
    ) -> None:
        """
        Initialize agent runner.

        Args:
            subject: TiKVSubject for cluster observations
            db_path: Path to SQLite database file
            anthropic_client: Optional AsyncAnthropic client (created if None)
            poll_interval: Seconds between polling cycles (default 10)
            model: Claude model to use for diagnosis (default claude-sonnet-4-5)
        """
        self.subject = subject
        self.db_path = db_path
        self.client = anthropic_client or AsyncAnthropic()
        self.poll_interval = poll_interval
        self.model = model
        self._shutdown = asyncio.Event()

        # Stats for logging
        self._tickets_processed = 0
        self._tickets_diagnosed = 0

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
            print(f"Ticket {ticket.id} diagnosed (severity: {diagnosis_output.severity})")

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
