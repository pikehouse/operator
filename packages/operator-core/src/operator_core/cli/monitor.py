"""Monitor daemon CLI command.

This module provides the CLI command for running the monitor daemon:
- run: Start continuous invariant checking

Per RESEARCH.md patterns:
- Use envvar parameter for environment variable fallback
- Uses factory pattern for subject creation (no direct TiKV imports)
- Wire up subject, checker, MonitorLoop via factory
"""

import asyncio
import os
from pathlib import Path

import typer

from operator_core.cli.subject_factory import AVAILABLE_SUBJECTS, create_subject
from operator_core.monitor.loop import MonitorLoop

monitor_app = typer.Typer(help="Run the operator monitor daemon")

# Default database path
DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


@monitor_app.command("run")
def run_monitor(
    subject: str = typer.Option(
        ...,  # Required (no default)
        "--subject",
        "-s",
        help=f"Subject to monitor ({', '.join(AVAILABLE_SUBJECTS)})",
    ),
    interval: float = typer.Option(
        30.0, "--interval", "-i", help="Check interval in seconds"
    ),
    pd_endpoint: str = typer.Option(
        None, "--pd", envvar="PD_ENDPOINT", help="PD endpoint (e.g., http://pd:2379)"
    ),
    prometheus_url: str = typer.Option(
        None,
        "--prometheus",
        envvar="PROMETHEUS_URL",
        help="Prometheus URL (e.g., http://prometheus:9090)",
    ),
    db_path: Path = typer.Option(DEFAULT_DB_PATH, "--db", help="Path to tickets database"),
) -> None:
    """
    Run the monitor daemon.

    Continuously checks invariants at the specified interval and creates
    tickets for violations. Runs until interrupted with Ctrl+C.

    Environment variables:
        PD_ENDPOINT: PD API endpoint
        PROMETHEUS_URL: Prometheus API URL
    """
    # Validate endpoints - use defaults if not provided via option or env var
    if not pd_endpoint:
        pd_endpoint = os.environ.get("PD_ENDPOINT", "http://localhost:2379")
    if not prometheus_url:
        prometheus_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

    # Ensure database directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Starting monitor daemon for subject: {subject}")
    print(f"  PD endpoint: {pd_endpoint}")
    print(f"  Prometheus: {prometheus_url}")
    print(f"  Interval: {interval}s")
    print(f"  Database: {db_path}")
    print()
    print("Press Ctrl+C to stop")
    print()

    async def _run() -> None:
        try:
            # Use factory to create subject and checker
            subject_instance, checker = await create_subject(
                subject,
                pd_endpoint=pd_endpoint,
                prometheus_url=prometheus_url,
            )

            loop = MonitorLoop(
                subject=subject_instance,
                checker=checker,
                db_path=db_path,
                interval_seconds=interval,
            )

            await loop.run()
        except ValueError as e:
            # Handle unknown subject error with user-friendly message
            print(f"Error: {e}")
            raise typer.Exit(1)

    asyncio.run(_run())
