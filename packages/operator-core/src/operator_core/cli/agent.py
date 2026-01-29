"""Agent CLI commands."""

from pathlib import Path

import typer

from operator_core.agent_lab import run_agent_loop

agent_app = typer.Typer(help="Run the AI agent")
DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


@agent_app.command("start")
def start_agent(
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to tickets database"),
) -> None:
    """Run the agent loop. Polls for tickets and processes with Claude."""
    run_agent_loop(db_path)
