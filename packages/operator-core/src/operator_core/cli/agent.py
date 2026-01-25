"""Agent daemon CLI commands.

This module provides CLI commands for the AI diagnosis agent:
- start: Run the agent daemon continuously
- diagnose: Process a single ticket

Per RESEARCH.md patterns:
- Use envvar parameter for environment variable fallback
- Create httpx clients with timeout for HTTP operations
- Wire up TiKVSubject and AgentRunner
"""

import asyncio
import os
from pathlib import Path

import httpx
import typer

from operator_core.agent.runner import AgentRunner
from operator_core.db.tickets import TicketDB
from operator_core.monitor.types import TicketStatus
from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient
from operator_tikv.subject import TiKVSubject

agent_app = typer.Typer(help="Run the AI diagnosis agent")

# Default database path
DEFAULT_DB_PATH = Path.home() / ".operator" / "tickets.db"


@agent_app.command("start")
def start_agent(
    interval: float = typer.Option(
        10.0, "--interval", "-i", help="Poll interval in seconds"
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
    model: str = typer.Option(
        "claude-sonnet-4-5", "--model", "-m", help="Claude model for diagnosis"
    ),
) -> None:
    """
    Run the agent daemon.

    Continuously polls for open tickets, gathers context, and invokes
    Claude for AI diagnosis. Runs until interrupted with Ctrl+C.

    Environment variables:
        PD_ENDPOINT: PD API endpoint
        PROMETHEUS_URL: Prometheus API URL
        ANTHROPIC_API_KEY: API key for Claude
    """
    # Validate endpoints - use defaults if not provided via option or env var
    if not pd_endpoint:
        pd_endpoint = os.environ.get("PD_ENDPOINT", "http://localhost:2379")
    if not prometheus_url:
        prometheus_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

    # Ensure database directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print("Starting agent daemon...")
    print(f"  PD endpoint: {pd_endpoint}")
    print(f"  Prometheus: {prometheus_url}")
    print(f"  Poll interval: {interval}s")
    print(f"  Database: {db_path}")
    print(f"  Model: {model}")
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

                runner = AgentRunner(
                    subject=subject,
                    db_path=db_path,
                    poll_interval=interval,
                    model=model,
                )

                await runner.run()

    asyncio.run(_run())


@agent_app.command("diagnose")
def diagnose_ticket(
    ticket_id: int = typer.Argument(..., help="Ticket ID to diagnose"),
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
    model: str = typer.Option(
        "claude-sonnet-4-5", "--model", "-m", help="Claude model for diagnosis"
    ),
) -> None:
    """
    Diagnose a single ticket.

    Fetches the specified ticket, gathers context, and runs AI diagnosis.
    Does not start the daemon loop - processes just this one ticket.

    Environment variables:
        PD_ENDPOINT: PD API endpoint
        PROMETHEUS_URL: Prometheus API URL
        ANTHROPIC_API_KEY: API key for Claude
    """
    from anthropic import AsyncAnthropic

    from operator_core.agent.context import ContextGatherer
    from operator_core.agent.diagnosis import DiagnosisOutput, format_diagnosis_markdown
    from operator_core.agent.prompt import SYSTEM_PROMPT, build_diagnosis_prompt

    # Validate endpoints
    if not pd_endpoint:
        pd_endpoint = os.environ.get("PD_ENDPOINT", "http://localhost:2379")
    if not prometheus_url:
        prometheus_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

    async def _diagnose() -> None:
        # Fetch ticket
        async with TicketDB(db_path) as db:
            ticket = await db.get_ticket(ticket_id)
            if ticket is None:
                print(f"Ticket {ticket_id} not found")
                raise typer.Exit(1)

            if ticket.status == TicketStatus.DIAGNOSED:
                print(f"Ticket {ticket_id} is already diagnosed")
                raise typer.Exit(0)

            if ticket.status == TicketStatus.RESOLVED:
                print(f"Ticket {ticket_id} is resolved")
                raise typer.Exit(0)

            print(f"Diagnosing ticket {ticket_id}: {ticket.invariant_name}")

            async with httpx.AsyncClient(base_url=pd_endpoint, timeout=10.0) as pd_http:
                async with httpx.AsyncClient(
                    base_url=prometheus_url, timeout=10.0
                ) as prom_http:
                    subject = TiKVSubject(
                        pd=PDClient(http=pd_http),
                        prom=PrometheusClient(http=prom_http),
                    )

                    # Gather context
                    gatherer = ContextGatherer(subject, db)
                    context = await gatherer.gather(ticket)
                    prompt = build_diagnosis_prompt(context)

                    print("Calling Claude for diagnosis...")

                    # Invoke Claude
                    client = AsyncAnthropic()
                    response = await client.beta.messages.parse(
                        model=model,
                        max_tokens=4096,
                        betas=["structured-outputs-2025-11-13"],
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                        output_format=DiagnosisOutput,
                    )

                    if response.stop_reason == "refusal":
                        print("Claude refused to diagnose this ticket")
                        raise typer.Exit(1)

                    # Format and store diagnosis
                    diagnosis_output = response.parsed_output
                    diagnosis_md = format_diagnosis_markdown(diagnosis_output)
                    await db.update_diagnosis(ticket_id, diagnosis_md)

                    print(f"Diagnosis complete (severity: {diagnosis_output.severity})")
                    print(f"View with: operator tickets show {ticket_id}")

    asyncio.run(_diagnose())
