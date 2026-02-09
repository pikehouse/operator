"""Core agent loop with Claude Agent SDK and database integration."""

import asyncio
import json
import signal
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from operator_core.db.audit_log import AuditLogDB
from operator_core.monitor.types import Ticket

from .prompts import SYSTEM_PROMPT
from .ticket_ops import TicketOpsDB


async def process_ticket(
    ticket: Ticket,
    audit_db: AuditLogDB,
    session_id: str,
) -> tuple[str, str]:
    """Process ticket with Claude using the Agent SDK.

    Variant config is read from ticket.variant_model and ticket.variant_system_prompt
    if set by the eval harness. Otherwise uses defaults.

    Args:
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

    # Use variant model if set, otherwise default
    effective_model = ticket.variant_model or "claude-sonnet-4-5-20250929"

    # Build system prompt: variant override > default, then append subject context
    base_prompt = ticket.variant_system_prompt or SYSTEM_PROMPT
    effective_system_prompt = base_prompt
    if ticket.subject_context:
        effective_system_prompt += "\n\n" + ticket.subject_context

    options = ClaudeAgentOptions(
        model=effective_model,
        system_prompt=effective_system_prompt,
        allowed_tools=["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
        permission_mode="bypassPermissions",
        max_turns=50,
    )

    final_text = ""
    async for message in query(prompt=ticket_text, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    summary = block.text[:200]
                    audit_db.log_entry(
                        session_id, "reasoning", summary, block.text,
                    )
                    final_text = block.text
                    print(f"[Claude] {summary}")
                elif isinstance(block, ToolUseBlock):
                    input_str = json.dumps(block.input)
                    preview = f"{block.name}: {input_str[:60]}"
                    audit_db.log_entry(
                        session_id, "tool_call", preview,
                        tool_name=block.name,
                        tool_params=block.input,
                    )
                    print(f"[Tool Call] {preview}")
                elif isinstance(block, ToolResultBlock):
                    content_str = block.content if isinstance(block.content, str) else json.dumps(block.content)
                    audit_db.log_entry(
                        session_id, "tool_result", content_str[:200],
                        raw_content=content_str,
                        tool_name=None,
                        exit_code=1 if block.is_error else 0,
                    )
                    print(f"[Tool Result] {'ERROR' if block.is_error else 'OK'}: {content_str[:100]}")
        elif isinstance(message, ResultMessage):
            if message.result:
                final_text = message.result

    status = "resolved" if final_text else "escalated"
    return (status, final_text)


async def run_agent_loop(db_path: Path) -> None:
    """Run agent polling loop. Blocks until Ctrl+C.

    Args:
        db_path: Path to tickets database
    """
    print(f"Agent loop starting. Database: {db_path}\nPress Ctrl+C to stop.\n")

    # Shutdown coordination
    shutdown = asyncio.Event()
    current_session: tuple[AuditLogDB, str, int] | None = None  # (audit_db, session_id, ticket_id)

    loop = asyncio.get_running_loop()

    def handle_shutdown(signum: int) -> None:
        """Signal handler for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        print(f"\nReceived {sig_name}, shutting down gracefully...")
        shutdown.set()

        # Mark current session as escalated
        if current_session is not None:
            audit_db, session_id, ticket_id = current_session
            try:
                audit_db.complete_session(session_id, "escalated", f"Interrupted by {sig_name}")
                with TicketOpsDB(db_path) as ticket_db:
                    ticket_db.update_ticket_escalated(ticket_id, f"Agent shutdown ({sig_name})")
            except Exception as e:
                print(f"Error during shutdown cleanup: {e}")

    # Register signal handlers (asyncio-native)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, sig)

    while not shutdown.is_set():
        try:
            with TicketOpsDB(db_path) as ticket_db:
                ticket = ticket_db.poll_for_open_ticket()

            if ticket and ticket.id is not None:
                print(f"\n{'='*60}")
                print(f"Processing ticket #{ticket.id}: {ticket.invariant_name}")
                print(f"{'='*60}\n")

                # Hold ticket to prevent auto-resolution while working
                with TicketOpsDB(db_path) as ticket_db:
                    ticket_db.hold_ticket(ticket.id)

                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(ticket.id)
                    current_session = (audit_db, session_id, ticket.id)

                    try:
                        status, summary = await process_ticket(
                            ticket, audit_db, session_id
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
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            print(f"\nERROR in main loop: {e}\n")
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                pass
