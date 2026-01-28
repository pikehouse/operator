"""Core agent loop with tool_runner and database integration."""

import json
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

import anthropic
from anthropic import beta_tool

from operator_core.db.audit_log import AuditLogDB
from operator_core.monitor.types import Ticket, TicketStatus

from .prompts import HAIKU_SUMMARIZE_PROMPT, SYSTEM_PROMPT

# Global state for capturing shell execution results
_last_shell_result = None


@beta_tool
def shell(command: str, reasoning: str) -> str:
    """Execute a shell command. Synchronous for tool_runner compatibility."""
    global _last_shell_result
    try:
        result = subprocess.run(command, shell=True, capture_output=True, timeout=120, text=True)
        output = result.stdout
        exit_code = result.returncode
        if exit_code != 0:
            output += f"\n\nSTDERR: {result.stderr}\nExit code: {exit_code}"
        _last_shell_result = {"output": output, "exit_code": exit_code, "command": command}
        return output
    except subprocess.TimeoutExpired:
        output = "Command timed out after 120 seconds"
        _last_shell_result = {"output": output, "exit_code": 124, "command": command}
        return output
    except Exception as e:
        output = f"Error: {e}"
        _last_shell_result = {"output": output, "exit_code": 1, "command": command}
        return output


def summarize_with_haiku(client: anthropic.Anthropic, text: str) -> str:
    """Summarize text using Haiku. Returns truncated if summarization fails."""
    if len(text) < 100:
        return text
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20250929",
            max_tokens=150,
            messages=[{"role": "user", "content": f"{HAIKU_SUMMARIZE_PROMPT}\n\n{text}"}],
        )
        return response.content[0].text  # type: ignore
    except Exception:
        return text[:200] + "..." if len(text) > 200 else text


def process_ticket(client: anthropic.Anthropic, ticket: Ticket, audit_db: AuditLogDB, session_id: str) -> tuple[str, str]:
    """Process ticket with Claude. Returns (status, summary)."""
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
    global _last_shell_result
    for message in runner:
        if message.content:
            for block in message.content:
                if block.type == "text" and hasattr(block, "text"):
                    summary = summarize_with_haiku(client, block.text)  # type: ignore
                    audit_db.log_entry(session_id, "reasoning", summary, block.text, None, None, None)  # type: ignore
                    print(f"[Claude] {summary}")
                elif block.type == "tool_use" and hasattr(block, "input") and hasattr(block, "name"):
                    tool_params = block.input if isinstance(block.input, dict) else {}  # type: ignore
                    cmd = str(tool_params.get("command", ""))
                    cmd_preview = cmd[:60] + "..." if len(cmd) > 60 else cmd
                    audit_db.log_entry(session_id, "tool_call", f"shell: {cmd_preview}", None, block.name, tool_params, None)  # type: ignore
                    print(f"[Tool Call] {block.name}: {cmd_preview}")  # type: ignore

        # After each message, check if a tool was executed
        if _last_shell_result:
            result = _last_shell_result
            _last_shell_result = None
            summary = summarize_with_haiku(client, result["output"])
            audit_db.log_entry(session_id, "tool_result", summary, result["output"], "shell", None, result["exit_code"])
            print(f"[Tool Result] Exit {result['exit_code']}: {summary}")

        final_message = message

    # Determine outcome
    if final_message and final_message.stop_reason == "end_turn":
        summary_text = "Completed"
        if final_message.content and len(final_message.content) > 0 and hasattr(final_message.content[0], "text"):
            summary_text = final_message.content[0].text  # type: ignore
        return "resolved", summarize_with_haiku(client, summary_text)
    return "escalated", f"Session ended: {final_message.stop_reason if final_message else 'unknown'}"


def poll_for_open_ticket(db_path: Path) -> Ticket | None:
    """Poll for first open ticket."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at ASC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return Ticket(
        id=row["id"],
        violation_key=row["violation_key"],
        invariant_name=row["invariant_name"],
        message=row["message"],
        severity=row["severity"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        status=TicketStatus(row["status"]),
        store_id=row["store_id"],
        held=bool(row["held"]),
        batch_key=row["batch_key"],
        occurrence_count=row["occurrence_count"],
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        diagnosis=row["diagnosis"],
        metric_snapshot=json.loads(row["metric_snapshot"]) if row["metric_snapshot"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def update_ticket_resolved(db_path: Path, ticket_id: int, summary: str) -> None:
    """Mark ticket as resolved."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tickets SET status = 'resolved', resolved_at = ?, diagnosis = ? WHERE id = ?",
                 (datetime.now().isoformat(), summary, ticket_id))
    conn.commit()
    conn.close()


def update_ticket_escalated(db_path: Path, ticket_id: int, reason: str) -> None:
    """Mark ticket as escalated."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE tickets SET status = 'diagnosed', diagnosis = ? WHERE id = ?",
                 (f"ESCALATED: {reason}", ticket_id))
    conn.commit()
    conn.close()


def run_agent_loop(db_path: Path, audit_dir: Path | None = None) -> None:
    """Run agent polling loop. Blocks until Ctrl+C."""
    client = anthropic.Anthropic()
    print(f"Agent loop starting. Database: {db_path}\nPress Ctrl+C to stop.\n")

    while True:
        try:
            ticket = poll_for_open_ticket(db_path)

            if ticket and ticket.id is not None:
                print(f"\n{'='*60}\nProcessing ticket #{ticket.id}: {ticket.invariant_name}\n{'='*60}\n")

                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(ticket.id)

                    try:
                        status, summary = process_ticket(client, ticket, audit_db, session_id)
                        audit_db.complete_session(session_id, status, summary)

                        if status == "resolved":
                            update_ticket_resolved(db_path, ticket.id, summary)
                        else:
                            update_ticket_escalated(db_path, ticket.id, summary)

                        print(f"\n{'='*60}\nTicket #{ticket.id} -> {status}\nSummary: {summary}\n{'='*60}\n")

                    except Exception as e:
                        print(f"\nERROR processing ticket #{ticket.id}: {e}\n")
                        audit_db.complete_session(session_id, "failed", str(e))
                        update_ticket_escalated(db_path, ticket.id, f"Error: {str(e)}")

            time.sleep(1)

        except KeyboardInterrupt:
            print("\n\nAgent loop stopped by user.")
            break
        except Exception as e:
            print(f"\nERROR in main loop: {e}\n")
            time.sleep(1)
