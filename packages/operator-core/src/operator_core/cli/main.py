"""Operator CLI - AI-powered operator for distributed systems."""

import typer

from operator_core.cli.agent import agent_app
from operator_core.cli.audit import audit_app
from operator_core.cli.deploy import deploy_app
from operator_core.cli.monitor import monitor_app
from operator_core.cli.tickets import tickets_app

app = typer.Typer(
    name="operator",
    help="AI-powered operator for distributed systems",
    no_args_is_help=True,
)

# Add command groups
app.add_typer(agent_app, name="agent")
app.add_typer(audit_app, name="audit")
app.add_typer(deploy_app, name="deploy")
app.add_typer(tickets_app, name="tickets")
app.add_typer(monitor_app, name="monitor")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
