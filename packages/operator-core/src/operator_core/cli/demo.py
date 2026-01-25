"""Demo CLI commands for showcasing operator capabilities.

This module provides demo commands that run polished showcase experiences:
- chaos: End-to-end chaos demo (node kill -> detect -> diagnose)

Per CONTEXT.md decisions:
- Single command invocation runs the whole cycle
- Press-enter prompts at key moments for pacing
- Colored terminal output with Rich
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from operator_core.demo.chaos import ChaosDemo

demo_app = typer.Typer(help="Demo commands for showcasing operator capabilities")


@demo_app.command("chaos")
def chaos(
    timeout: float = typer.Option(
        30.0, "--timeout", "-t", help="Detection timeout in seconds"
    ),
    subject: str = typer.Option(
        "tikv", "--subject", "-s", help="Subject to demo (default: tikv)"
    ),
) -> None:
    """Run end-to-end chaos demo: kill node -> detect -> diagnose.

    This demo showcases the full operator pipeline:
    1. Ensures cluster is healthy (starts if needed)
    2. Starts YCSB load for realistic traffic
    3. Kills a random TiKV store
    4. Waits for detection (with live countdown)
    5. Runs AI diagnosis
    6. Displays structured reasoning
    7. Cleans up (restarts killed container)

    Press Enter at each stage to continue.
    """
    console = Console()

    # Find compose file
    base_path = Path.cwd()
    compose_file = base_path / "subjects" / subject / "docker-compose.yaml"

    if not compose_file.exists():
        console.print(f"[red]Compose file not found: {compose_file}[/red]")
        console.print(
            f"[yellow]Run from project root or ensure subjects/{subject}/docker-compose.yaml exists[/yellow]"
        )
        raise typer.Exit(1)

    console.print()
    console.rule("[bold magenta]Operator Chaos Demo[/bold magenta]")
    console.print()
    console.print("This demo will:")
    console.print("  1. Ensure cluster is healthy")
    console.print("  2. Start YCSB load generation")
    console.print("  3. Kill a random TiKV store")
    console.print("  4. Wait for detection")
    console.print("  5. Run AI diagnosis")
    console.print("  6. Display reasoning")
    console.print("  7. Restore cluster")
    console.print()

    demo = ChaosDemo(
        console=console,
        compose_file=compose_file,
        subject=subject,
        detection_timeout=timeout,
    )

    async def _run() -> None:
        await demo.run()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted[/yellow]")
        raise typer.Exit(1)

    console.print()
    console.rule("[bold green]Demo Complete[/bold green]")
    console.print()
