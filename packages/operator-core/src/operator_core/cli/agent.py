"""Agent CLI commands."""

import asyncio
from pathlib import Path

import typer

from operator_core.agent_lab import run_agent_loop
from operator_core.cli import DEFAULT_DB_PATH

agent_app = typer.Typer(help="Run the AI agent")


@agent_app.command("start")
def start_agent(
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to tickets database"),
) -> None:
    """Run the agent loop. Polls for tickets and processes with Claude."""
    asyncio.run(run_agent_loop(db_path))
