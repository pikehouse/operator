"""Ticket management CLI commands.

This module provides CLI commands for interacting with the ticket database:
- list: Display all tickets in table or JSON format
- resolve: Manually resolve a ticket
- hold: Prevent auto-resolve while investigating
- unhold: Allow auto-resolve for a previously held ticket

Per RESEARCH.md patterns:
- Use typer.Typer() subcommand group
- asyncio.run() to execute async database operations in sync CLI commands
- Rich Table for formatted output, JSON for automation
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import TicketStatus

tickets_app = typer.Typer(help="Manage operator tickets")

# Default database path per RESEARCH.md
DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


def _get_db_path() -> Path:
    """Get database path, ensuring parent directory exists."""
    db_path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@tickets_app.command("list")
def list_tickets(
    status: str = typer.Option(
        None, "--status", "-s", help="Filter by status (open, acknowledged, diagnosed, resolved)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """List all tickets."""

    async def _list() -> None:
        db_path = _get_db_path()
        status_filter = TicketStatus(status) if status else None

        async with TicketDB(db_path) as db:
            tickets = await db.list_tickets(status=status_filter)

        if json_output:
            data = [t.to_dict() for t in tickets]
            print(json.dumps(data, indent=2, default=str))
            return

        # Rich table output per RESEARCH.md Pattern 5
        console = Console()
        table = Table(title="Tickets")
        table.add_column("ID", justify="right", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Invariant")
        table.add_column("Store", justify="center")
        table.add_column("Count", justify="right")
        table.add_column("First Seen")
        table.add_column("Held", justify="center")

        for t in tickets:
            held_mark = "[red]HELD[/red]" if t.held else ""
            table.add_row(
                str(t.id),
                t.status.value,
                t.invariant_name,
                t.store_id or "-",
                str(t.occurrence_count),
                t.first_seen_at.strftime("%Y-%m-%d %H:%M:%S"),
                held_mark,
            )

        console.print(table)

    asyncio.run(_list())


@tickets_app.command("resolve")
def resolve_ticket(
    ticket_id: int = typer.Argument(..., help="Ticket ID to resolve"),
) -> None:
    """Manually resolve a ticket."""

    async def _resolve() -> None:
        db_path = _get_db_path()
        async with TicketDB(db_path) as db:
            ticket = await db.get_ticket(ticket_id)
            if ticket is None:
                print(f"Ticket {ticket_id} not found")
                raise typer.Exit(1)

            if ticket.status == TicketStatus.RESOLVED:
                print(f"Ticket {ticket_id} is already resolved")
                return

            if ticket.held:
                # Per CONTEXT.md: resolve overrides hold for manual resolution
                await db.unhold_ticket(ticket_id)

            # Manual resolve - db.resolve_ticket will work now that held=0
            await db.resolve_ticket(ticket_id)
            print(f"Resolved ticket {ticket_id}")

    asyncio.run(_resolve())


@tickets_app.command("hold")
def hold_ticket(
    ticket_id: int = typer.Argument(..., help="Ticket ID to hold"),
) -> None:
    """Prevent auto-resolve while investigating a ticket."""

    async def _hold() -> None:
        db_path = _get_db_path()
        async with TicketDB(db_path) as db:
            ticket = await db.get_ticket(ticket_id)
            if ticket is None:
                print(f"Ticket {ticket_id} not found")
                raise typer.Exit(1)

            if ticket.held:
                print(f"Ticket {ticket_id} is already held")
                return

            await db.hold_ticket(ticket_id)
            print(f"Holding ticket {ticket_id} - will not auto-resolve")

    asyncio.run(_hold())


@tickets_app.command("unhold")
def unhold_ticket(
    ticket_id: int = typer.Argument(..., help="Ticket ID to unhold"),
) -> None:
    """Allow auto-resolve for a previously held ticket."""

    async def _unhold() -> None:
        db_path = _get_db_path()
        async with TicketDB(db_path) as db:
            ticket = await db.get_ticket(ticket_id)
            if ticket is None:
                print(f"Ticket {ticket_id} not found")
                raise typer.Exit(1)

            if not ticket.held:
                print(f"Ticket {ticket_id} is not held")
                return

            await db.unhold_ticket(ticket_id)
            print(f"Ticket {ticket_id} can now auto-resolve")

    asyncio.run(_unhold())


@tickets_app.command("show")
def show_ticket(
    ticket_id: int = typer.Argument(..., help="Ticket ID to show"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
) -> None:
    """Show ticket details including diagnosis."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    async def _show() -> None:
        db_path = _get_db_path()
        async with TicketDB(db_path) as db:
            ticket = await db.get_ticket(ticket_id)
            if ticket is None:
                print(f"Ticket {ticket_id} not found")
                raise typer.Exit(1)

        if json_output:
            print(json.dumps(ticket.to_dict(), indent=2, default=str))
            return

        # Rich formatted output
        console = Console()

        # Ticket metadata panel
        metadata = f"""[bold]ID:[/bold] {ticket.id}
[bold]Status:[/bold] {ticket.status.value}
[bold]Invariant:[/bold] {ticket.invariant_name}
[bold]Store:[/bold] {ticket.store_id or 'N/A'}
[bold]Severity:[/bold] {ticket.severity}
[bold]First seen:[/bold] {ticket.first_seen_at.strftime('%Y-%m-%d %H:%M:%S')}
[bold]Last seen:[/bold] {ticket.last_seen_at.strftime('%Y-%m-%d %H:%M:%S')}
[bold]Occurrences:[/bold] {ticket.occurrence_count}
[bold]Held:[/bold] {'Yes' if ticket.held else 'No'}"""

        console.print(Panel(metadata, title=f"Ticket #{ticket.id}", border_style="cyan"))

        # Message
        console.print()
        console.print("[bold]Message:[/bold]")
        console.print(f"  {ticket.message}")

        # Diagnosis section
        console.print()
        if ticket.diagnosis:
            console.print(Panel(
                Markdown(ticket.diagnosis),
                title="AI Diagnosis",
                border_style="green",
            ))
        else:
            console.print("[yellow]No diagnosis yet[/yellow]")

    asyncio.run(_show())
