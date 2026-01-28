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


@beta_tool
def shell(command: str, reasoning: str) -> str:
    """Execute a shell command. Synchronous for tool_runner compatibility."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, timeout=120, text=True)
        output = result.stdout
        if result.returncode != 0:
            output += f"\n\nSTDERR: {result.stderr}\nExit code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 120 seconds"
    except Exception as e:
        return f"Error: {e}"


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
        return response.content[0].text
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
    for message in runner:
        if message.content:
            for block in message.content:
                if hasattr(block, "text") and block.text:
                    summary = summarize_with_haiku(client, block.text)
                    audit_db.log_entry(session_id, "reasoning", summary, block.text, None, None, None)
                    print(f"[Claude] {summary}")
        final_message = message

    # Determine outcome
    if final_message and final_message.stop_reason == "end_turn":
        summary_text = final_message.content[0].text if final_message.content else "Completed"
        return "resolved", summarize_with_haiku(client, summary_text)
    else:
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

            if ticket:
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
