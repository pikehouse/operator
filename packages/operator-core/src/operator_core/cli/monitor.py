"""Monitor daemon CLI command.

This module provides the CLI command for running the monitor daemon:
- run: Start continuous invariant checking

Per RESEARCH.md patterns:
- Use envvar parameter for environment variable fallback
- Create httpx clients with timeout for HTTP operations
- Wire up TiKVSubject, InvariantChecker, MonitorLoop
"""

import asyncio
import os
from pathlib import Path

import httpx
import typer

from operator_core.monitor.loop import MonitorLoop
from operator_tikv.invariants import InvariantChecker
from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient
from operator_tikv.subject import TiKVSubject

monitor_app = typer.Typer(help="Run the operator monitor daemon")

# Default database path
DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


@monitor_app.command("run")
def run_monitor(
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

    print("Starting monitor daemon...")
    print(f"  PD endpoint: {pd_endpoint}")
    print(f"  Prometheus: {prometheus_url}")
    print(f"  Interval: {interval}s")
    print(f"  Database: {db_path}")
    print()
    print("Press Ctrl+C to stop")
    print()

    async def _run() -> None:
        async with httpx.AsyncClient(base_url=pd_endpoint, timeout=10.0) as pd_http:
            async with httpx.AsyncClient(
                base_url=prometheus_url, timeout=10.0
            ) as prom_http:
                subject = TiKVSubject(
                    pd=PDClient(http=pd_http),
                    prom=PrometheusClient(http=prom_http),
                )
                checker = InvariantChecker()

                loop = MonitorLoop(
                    subject=subject,
                    checker=checker,
                    db_path=db_path,
                    interval_seconds=interval,
                )

                await loop.run()

    asyncio.run(_run())
