"""Deploy commands for managing cluster deployments."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from operator_core.deploy import LocalDeployment, create_local_deployment

deploy_app = typer.Typer(help="Deployment commands")
local_app = typer.Typer(help="Local Docker Compose deployment")
deploy_app.add_typer(local_app, name="local")

console = Console()


def _get_deployment(subject: str) -> LocalDeployment:
    """Get a LocalDeployment for the given subject."""
    try:
        return create_local_deployment(subject)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@local_app.command()
def up(
    subject: str = typer.Argument("tikv", help="Subject to deploy (e.g., tikv)"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for health checks"),
) -> None:
    """Start local cluster for a subject."""
    console.print(f"[bold]Starting {subject} cluster...[/bold]")
    deployment = _get_deployment(subject)
    deployment.up(wait=wait)


@local_app.command()
def down(
    subject: str = typer.Argument("tikv", help="Subject to stop"),
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes too"),
) -> None:
    """Stop local cluster."""
    console.print(f"[bold]Stopping {subject} cluster...[/bold]")
    deployment = _get_deployment(subject)
    deployment.down(remove_volumes=volumes)


@local_app.command()
def status(
    subject: str = typer.Argument("tikv", help="Subject to check"),
) -> None:
    """Show cluster status."""
    deployment = _get_deployment(subject)
    result = deployment.status()

    table = Table(title=f"{subject} Cluster Status")
    table.add_column("Service", style="cyan")
    table.add_column("Running", style="green")
    table.add_column("Health", style="yellow")
    table.add_column("Ports", style="blue")

    for svc in result.services:
        running = "[green]Yes[/green]" if svc.running else "[red]No[/red]"
        health = svc.health
        ports = ", ".join(svc.ports) if svc.ports else "-"
        table.add_row(svc.name, running, health, ports)

    console.print(table)

    if result.all_healthy:
        console.print("\n[green]All services running[/green]")
    else:
        console.print("\n[yellow]Some services not running[/yellow]")


@local_app.command()
def logs(
    subject: str = typer.Argument("tikv", help="Subject to get logs from"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Specific service"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines to show"),
) -> None:
    """View container logs."""
    deployment = _get_deployment(subject)
    deployment.logs(service=service, follow=follow, tail=tail)


@local_app.command()
def restart(
    subject: str = typer.Argument("tikv", help="Subject containing the service"),
    service: str = typer.Argument(..., help="Service to restart"),
) -> None:
    """Restart a specific service."""
    deployment = _get_deployment(subject)
    deployment.restart(service)
