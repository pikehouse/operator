"""Core agent loop with tool_runner and database integration."""

import json
import signal
import threading
import time
from pathlib import Path

import anthropic

from operator_core.db.audit_log import AuditLogDB
from operator_core.monitor.types import Ticket

from .prompts import SYSTEM_PROMPT
from .summarize import summarize_with_haiku
from .ticket_ops import TicketOpsDB
from .tools import get_last_result, shell


def process_ticket(
    client: anthropic.Anthropic,
    ticket: Ticket,
    audit_db: AuditLogDB,
    session_id: str,
) -> tuple[str, str]:
    """Process ticket with Claude using tool_runner.

    Args:
        client: Anthropic client
        ticket: Ticket to process
        audit_db: Audit database for logging
        session_id: Current session ID

    Returns:
        Tuple of (status, summary) where status is 'resolved' or 'escalated'
    """
    # Build ticket description
    ticket_text = f"Ticket #{ticket.id}: {ticket.invariant_name}\n{ticket.message}"
    if ticket.metric_snapshot:
        ticket_text += f"\n\nMetrics:\n{json.dumps(ticket.metric_snapshot, indent=2)}"

    # Run Claude with tool_runner
    runner = client.beta.messages.tool_runner(
        model="claude-opus-4-20250514",
        max_tokens=8192,
        tools=[shell],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": ticket_text}],
    )

    final_message = None
    for message in runner:
        if message.content:
            for block in message.content:
                if block.type == "text" and hasattr(block, "text"):
                    summary = summarize_with_haiku(client, block.text)  # type: ignore
                    audit_db.log_entry(
                        session_id, "reasoning", summary, block.text, None, None, None  # type: ignore
                    )
                    print(f"[Claude] {summary}")
                elif block.type == "tool_use" and hasattr(block, "input"):
                    tool_params = block.input if isinstance(block.input, dict) else {}  # type: ignore
                    cmd = str(tool_params.get("command", ""))
                    cmd_preview = cmd[:60] + "..." if len(cmd) > 60 else cmd
                    audit_db.log_entry(
                        session_id, "tool_call", f"shell: {cmd_preview}",
                        None, block.name, tool_params, None,  # type: ignore
                    )
                    print(f"[Tool Call] {block.name}: {cmd_preview}")  # type: ignore

        # After each message, check if a tool was executed
        result = get_last_result()
        if result:
            summary = summarize_with_haiku(client, result["output"])
            audit_db.log_entry(
                session_id, "tool_result", summary,
                result["output"], "shell", None, result["exit_code"],
            )
            print(f"[Tool Result] Exit {result['exit_code']}: {summary}")

        final_message = message

    # Determine outcome
    if final_message and final_message.stop_reason == "end_turn":
        summary_text = "Completed"
        if final_message.content and len(final_message.content) > 0:
            first_block = final_message.content[0]
            if hasattr(first_block, "text"):
                summary_text = first_block.text  # type: ignore
        return "resolved", summarize_with_haiku(client, summary_text)
    return "escalated", f"Session ended: {final_message.stop_reason if final_message else 'unknown'}"


def run_agent_loop(db_path: Path, audit_dir: Path | None = None) -> None:
    """Run agent polling loop. Blocks until Ctrl+C.

    Args:
        db_path: Path to tickets database
        audit_dir: Unused, kept for API compatibility
    """
    client = anthropic.Anthropic()
    print(f"Agent loop starting. Database: {db_path}\nPress Ctrl+C to stop.\n")

    # Shutdown coordination
    shutdown = threading.Event()
    current_session: tuple[AuditLogDB, str, int] | None = None  # (audit_db, session_id, ticket_id)

    def handle_shutdown(signum: int, frame) -> None:
        """Signal handler for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        print(f"\nReceived {sig_name}, shutting down gracefully...")
        shutdown.set()

        # Mark current session as escalated (DEMO-07)
        if current_session is not None:
            audit_db, session_id, ticket_id = current_session
            try:
                audit_db.complete_session(session_id, "escalated", f"Interrupted by {sig_name}")
                with TicketOpsDB(db_path) as ticket_db:
                    ticket_db.update_ticket_escalated(ticket_id, f"Agent shutdown ({sig_name})")
            except Exception as e:
                print(f"Error during shutdown cleanup: {e}")

    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while not shutdown.is_set():
        try:
            with TicketOpsDB(db_path) as ticket_db:
                ticket = ticket_db.poll_for_open_ticket()

            if ticket and ticket.id is not None:
                print(f"\n{'='*60}")
                print(f"Processing ticket #{ticket.id}: {ticket.invariant_name}")
                print(f"{'='*60}\n")

                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(ticket.id)
                    current_session = (audit_db, session_id, ticket.id)

                    try:
                        status, summary = process_ticket(
                            client, ticket, audit_db, session_id
                        )
                        audit_db.complete_session(session_id, status, summary)

                        with TicketOpsDB(db_path) as ticket_db:
                            if status == "resolved":
                                ticket_db.update_ticket_resolved(ticket.id, summary)
                            else:
                                ticket_db.update_ticket_escalated(ticket.id, summary)

                        print(f"\n{'='*60}")
                        print(f"Ticket #{ticket.id} -> {status}")
                        print(f"Summary: {summary}")
                        print(f"{'='*60}\n")

                    except Exception as e:
                        print(f"\nERROR processing ticket #{ticket.id}: {e}\n")
                        audit_db.complete_session(session_id, "failed", str(e))
                        with TicketOpsDB(db_path) as ticket_db:
                            ticket_db.update_ticket_escalated(ticket.id, f"Error: {str(e)}")
                    finally:
                        current_session = None

            # Interruptible sleep
            if shutdown.wait(timeout=1.0):
                break

        except Exception as e:
            print(f"\nERROR in main loop: {e}\n")
            if shutdown.wait(timeout=1.0):
                break
