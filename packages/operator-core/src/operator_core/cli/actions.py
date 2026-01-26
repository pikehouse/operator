"""CLI commands for action management.

Provides user-facing commands for viewing and managing action proposals:
- list: View pending/all action proposals
- show: View details of a specific proposal
- approve: Approve a validated proposal for execution
- reject: Reject a validated proposal with reason
- cancel: Cancel a pending proposal
- kill-switch: Emergency stop all pending actions
- mode: Set safety mode (observe/execute)
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from operator_core.actions.audit import ActionAuditor
from operator_core.actions.safety import SafetyController, SafetyMode
from operator_core.actions.types import ActionStatus
from operator_core.db.actions import ActionDB

actions_app = typer.Typer(help="Manage action proposals")
console = Console()


def _get_db_path(db_path: Path | None) -> Path:
    """Get database path, defaulting to ~/.operator/operator.db."""
    if db_path is not None:
        return db_path
    return Path.home() / ".operator" / "operator.db"


@actions_app.command("list")
def list_actions(
    status: str = typer.Option(
        None, help="Filter by status (proposed, validated, executing, completed, failed, cancelled)"
    ),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """List action proposals."""

    async def _list():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[yellow]No database found. No proposals to list.[/yellow]")
            return

        # Parse status filter
        status_filter = None
        if status:
            try:
                status_filter = ActionStatus(status.lower())
            except ValueError:
                console.print(
                    f"[red]Invalid status '{status}'. "
                    f"Valid: proposed, validated, executing, completed, failed, cancelled[/red]"
                )
                raise typer.Exit(1)

        async with ActionDB(path) as db:
            proposals = await db.list_proposals(status=status_filter)

        if not proposals:
            filter_msg = f" with status '{status}'" if status else ""
            console.print(f"[dim]No proposals found{filter_msg}.[/dim]")
            return

        table = Table(title="Action Proposals")
        table.add_column("ID", style="cyan")
        table.add_column("Action", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Ticket", style="dim")
        table.add_column("Proposed", style="dim")

        for p in proposals:
            # Format status with color
            status_style = {
                "proposed": "yellow",
                "validated": "blue",
                "executing": "magenta",
                "completed": "green",
                "failed": "red",
                "cancelled": "dim",
            }.get(p.status.value, "white")

            table.add_row(
                str(p.id),
                p.action_name,
                f"[{status_style}]{p.status.value}[/{status_style}]",
                str(p.ticket_id) if p.ticket_id else "-",
                p.proposed_at.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)

    asyncio.run(_list())


@actions_app.command("show")
def show_action(
    proposal_id: int = typer.Argument(..., help="Proposal ID to show"),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Show details of an action proposal."""

    async def _show():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[red]Database not found.[/red]")
            raise typer.Exit(1)

        async with ActionDB(path) as db:
            proposal = await db.get_proposal(proposal_id)

        if not proposal:
            console.print(f"[red]Proposal {proposal_id} not found.[/red]")
            raise typer.Exit(1)

        # Format status with color
        status_style = {
            "proposed": "yellow",
            "validated": "blue",
            "executing": "magenta",
            "completed": "green",
            "failed": "red",
            "cancelled": "dim",
        }.get(proposal.status.value, "white")

        console.print(f"\n[bold]Proposal {proposal.id}[/bold]")
        console.print(f"  Action: [green]{proposal.action_name}[/green]")
        console.print(f"  Status: [{status_style}]{proposal.status.value}[/{status_style}]")
        console.print(f"  Type: {proposal.action_type.value}")
        console.print(f"  Ticket: {proposal.ticket_id or 'None'}")
        console.print(f"  Proposed by: {proposal.proposed_by}")
        console.print(f"  Proposed at: {proposal.proposed_at.isoformat()}")
        if proposal.approved_at:
            console.print(f"  Approved by: {proposal.approved_by}")
            console.print(f"  Approved at: {proposal.approved_at.isoformat()}")
        if proposal.rejected_at:
            console.print(f"  Rejected by: {proposal.rejected_by}")
            console.print(f"  Rejected at: {proposal.rejected_at.isoformat()}")
            console.print(f"  Rejection reason: {proposal.rejection_reason}")
        console.print()
        console.print("[bold]Parameters:[/bold]")
        if proposal.parameters:
            for key, value in proposal.parameters.items():
                console.print(f"  {key}: {value}")
        else:
            console.print("  [dim]None[/dim]")
        console.print()
        console.print("[bold]Reason:[/bold]")
        console.print(f"  {proposal.reason}")

    asyncio.run(_show())


@actions_app.command("approve")
def approve_action(
    proposal_id: int = typer.Argument(..., help="Proposal ID to approve"),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Approve a validated action proposal for execution."""

    async def _approve():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[red]Database not found.[/red]")
            raise typer.Exit(1)

        async with ActionDB(path) as db:
            proposal = await db.get_proposal(proposal_id)

            if not proposal:
                console.print(f"[red]Proposal {proposal_id} not found.[/red]")
                raise typer.Exit(1)

            if proposal.status != ActionStatus.VALIDATED:
                console.print(
                    f"[red]Proposal {proposal_id} is {proposal.status.value}, "
                    f"expected 'validated'.[/red]"
                )
                raise typer.Exit(1)

            await db.approve_proposal(proposal_id, approved_by="user")

            console.print(
                f"[green]Proposal {proposal_id} approved.[/green]\n"
                f"  Action: {proposal.action_name}\n"
                f"  The action will execute on next agent cycle."
            )

    asyncio.run(_approve())


@actions_app.command("reject")
def reject_action(
    proposal_id: int = typer.Argument(..., help="Proposal ID to reject"),
    reason: str = typer.Option(
        "Rejected by user",
        help="Rejection reason",
    ),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Reject a validated action proposal (cancels it with reason)."""

    async def _reject():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[red]Database not found.[/red]")
            raise typer.Exit(1)

        async with ActionDB(path) as db:
            proposal = await db.get_proposal(proposal_id)

            if not proposal:
                console.print(f"[red]Proposal {proposal_id} not found.[/red]")
                raise typer.Exit(1)

            if proposal.status != ActionStatus.VALIDATED:
                console.print(
                    f"[red]Proposal {proposal_id} is {proposal.status.value}, "
                    f"expected 'validated'.[/red]"
                )
                raise typer.Exit(1)

            await db.reject_proposal(proposal_id, rejected_by="user", reason=reason)

            console.print(
                f"[yellow]Proposal {proposal_id} rejected.[/yellow]\n"
                f"  Action: {proposal.action_name}\n"
                f"  Reason: {reason}"
            )

    asyncio.run(_reject())


@actions_app.command("cancel")
def cancel_action(
    proposal_id: int = typer.Argument(..., help="Proposal ID to cancel"),
    reason: str = typer.Option(
        "Cancelled by user",
        help="Cancellation reason",
    ),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Cancel a pending action proposal."""

    async def _cancel():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[red]Database not found.[/red]")
            raise typer.Exit(1)

        # Import executor to use cancel_proposal
        from operator_core.actions.executor import ActionExecutor
        from operator_core.actions.registry import ActionRegistry

        # Create minimal components needed for cancel
        auditor = ActionAuditor(path)

        # We need a mock subject just to create registry
        # (cancel doesn't actually use it)
        class MinimalSubject:
            def get_action_definitions(self):
                return []

        registry = ActionRegistry(MinimalSubject())
        safety = SafetyController(path, auditor, mode=SafetyMode.EXECUTE)
        executor = ActionExecutor(path, registry, safety, auditor)

        try:
            await executor.cancel_proposal(proposal_id, reason)
            console.print(
                f"[green]Proposal {proposal_id} cancelled.[/green] Reason: {reason}"
            )
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)

    asyncio.run(_cancel())


@actions_app.command("kill-switch")
def kill_switch(
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Emergency stop - cancel all pending actions and switch to observe mode."""

    async def _kill_switch():
        path = _get_db_path(db_path)

        if not path.exists():
            console.print("[yellow]Database not found. Nothing to cancel.[/yellow]")
            return

        auditor = ActionAuditor(path)
        safety = SafetyController(path, auditor, mode=SafetyMode.EXECUTE)

        cancelled_count = await safety.kill_switch()

        if cancelled_count > 0:
            console.print(
                f"[red bold]KILL SWITCH ACTIVATED[/red bold]\n"
                f"  Cancelled {cancelled_count} pending proposal(s)\n"
                f"  Safety mode: [yellow]OBSERVE[/yellow] (actions blocked)"
            )
        else:
            console.print(
                f"[yellow]Kill switch activated.[/yellow]\n"
                f"  No pending proposals to cancel\n"
                f"  Safety mode: [yellow]OBSERVE[/yellow] (actions blocked)"
            )

    asyncio.run(_kill_switch())


@actions_app.command("mode")
def set_mode(
    mode: str = typer.Argument(..., help="Safety mode: 'observe' or 'execute'"),
    db_path: Path = typer.Option(
        None,
        help="Database path (default: ~/.operator/operator.db)",
    ),
) -> None:
    """Set safety mode (observe or execute)."""

    async def _set_mode():
        path = _get_db_path(db_path)

        # Validate mode
        mode_lower = mode.lower()
        if mode_lower not in ("observe", "execute"):
            console.print(
                f"[red]Invalid mode '{mode}'. Must be 'observe' or 'execute'.[/red]"
            )
            raise typer.Exit(1)

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        auditor = ActionAuditor(path)
        # Start in opposite mode so we can demonstrate the change
        current_mode = SafetyMode.OBSERVE if mode_lower == "execute" else SafetyMode.EXECUTE
        safety = SafetyController(path, auditor, mode=current_mode)

        target_mode = SafetyMode(mode_lower)
        await safety.set_mode(target_mode)

        if target_mode == SafetyMode.OBSERVE:
            console.print(
                f"[yellow]Safety mode: OBSERVE[/yellow]\n"
                f"  Action execution is blocked\n"
                f"  Agent will diagnose but not propose actions"
            )
        else:
            console.print(
                f"[green]Safety mode: EXECUTE[/green]\n"
                f"  Action execution is enabled\n"
                f"  Agent can propose and execute actions"
            )

    asyncio.run(_set_mode())
