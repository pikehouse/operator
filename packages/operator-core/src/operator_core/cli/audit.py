"""Agent audit log CLI commands.

This module provides CLI commands for reviewing agent session history:
- list: Display recent sessions in table format
- show: Display full conversation for a specific session

Per CONTEXT.md: CLI tool, not Web UI. Formatted text output with
timestamps and indentation. Show Haiku summaries, not full tool output.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

audit_app = typer.Typer(help="Review agent audit logs")

DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


def _format_timestamp(iso_str: str | None) -> str:
    """Format ISO timestamp to human-readable."""
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso_str


@audit_app.command("list")
def list_sessions(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to database"),
) -> None:
    """List recent agent sessions."""
    console = Console()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute(
        """
        SELECT session_id, ticket_id, status, started_at, ended_at, outcome_summary
        FROM agent_sessions
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No sessions found[/yellow]")
        return

    table = Table(title="Agent Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Ticket", justify="right")
    table.add_column("Status", style="green")
    table.add_column("Started", style="dim")
    table.add_column("Duration")
    table.add_column("Outcome")

    for row in rows:
        # Calculate duration
        duration = "-"
        if row["started_at"] and row["ended_at"]:
            try:
                start = datetime.fromisoformat(row["started_at"])
                end = datetime.fromisoformat(row["ended_at"])
                delta = end - start
                duration = f"{delta.total_seconds():.1f}s"
            except ValueError:
                pass

        # Truncate outcome for table
        outcome = row["outcome_summary"] or "-"
        if len(outcome) > 50:
            outcome = outcome[:47] + "..."

        table.add_row(
            row["session_id"],
            str(row["ticket_id"]) if row["ticket_id"] else "-",
            row["status"] or "unknown",
            _format_timestamp(row["started_at"]),
            duration,
            outcome,
        )

    console.print(table)


@audit_app.command("show")
def show_session(
    session_id: str = typer.Argument(..., help="Session ID to display"),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to database"),
) -> None:
    """Show full conversation for an agent session."""
    console = Console()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get session metadata
    cursor = conn.execute(
        "SELECT * FROM agent_sessions WHERE session_id = ?",
        (session_id,),
    )
    session = cursor.fetchone()

    if not session:
        console.print(f"[red]Session not found: {session_id}[/red]")
        raise typer.Exit(1)

    # Get log entries
    cursor = conn.execute(
        """
        SELECT * FROM agent_log_entries
        WHERE session_id = ?
        ORDER BY timestamp ASC
        """,
        (session_id,),
    )
    entries = cursor.fetchall()
    conn.close()

    # Session header
    metadata = f"""[bold]Session:[/bold] {session["session_id"]}
[bold]Ticket:[/bold] {session["ticket_id"] or "N/A"}
[bold]Status:[/bold] {session["status"]}
[bold]Started:[/bold] {_format_timestamp(session["started_at"])}
[bold]Ended:[/bold] {_format_timestamp(session["ended_at"])}"""

    console.print(Panel(metadata, title="Session Info", border_style="cyan"))
    console.print()

    # Outcome summary
    if session["outcome_summary"]:
        console.print(Panel(
            session["outcome_summary"],
            title="Outcome Summary",
            border_style="green",
        ))
        console.print()

    # Log entries with timestamps and indentation
    console.print("[bold]Conversation Log:[/bold]")
    console.print()

    for entry in entries:
        timestamp = _format_timestamp(entry["timestamp"])
        entry_type = entry["entry_type"]
        content = entry["content"] or ""

        # Format based on entry type
        if entry_type == "reasoning":
            console.print(f"[dim]{timestamp}[/dim] [cyan][Claude][/cyan]")
            console.print(f"    {content}")
        elif entry_type == "tool_call":
            tool_name = entry["tool_name"] or "unknown"
            console.print(f"[dim]{timestamp}[/dim] [yellow][Tool Call: {tool_name}][/yellow]")
            console.print(f"    {content}")
        elif entry_type == "tool_result":
            exit_code = entry["exit_code"]
            exit_str = f" (exit {exit_code})" if exit_code is not None else ""
            console.print(f"[dim]{timestamp}[/dim] [green][Result{exit_str}][/green]")
            console.print(f"    {content}")
        else:
            console.print(f"[dim]{timestamp}[/dim] [{entry_type}]")
            console.print(f"    {content}")

        console.print()
