"""Operator CLI - AI-powered operator for distributed systems."""

import typer

from operator_core.cli.deploy import deploy_app

app = typer.Typer(
    name="operator",
    help="AI-powered operator for distributed systems",
    no_args_is_help=True,
)

# Add deploy command group
app.add_typer(deploy_app, name="deploy")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
