"""Evaluation harness CLI."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from eval.runner.db import EvalDB
from eval.runner.harness import run_trial, run_campaign
from eval.subjects.tikv import TiKVEvalSubject
from eval.types import EvalSubject

app = typer.Typer(
    name="eval",
    help="Evaluation harness for chaos engineering trials",
    no_args_is_help=True,
)

run_app = typer.Typer(help="Run evaluation trials")
app.add_typer(run_app, name="run")

console = Console()


def get_subject(subject_name: str) -> EvalSubject:
    """Load eval subject by name.

    Args:
        subject_name: Subject identifier (e.g., 'tikv')

    Returns:
        EvalSubject implementation

    Raises:
        typer.BadParameter: If subject not found
    """
    if subject_name.lower() == "tikv":
        return TiKVEvalSubject()

    raise typer.BadParameter(f"Unknown subject: {subject_name}. Available: tikv")


@run_app.callback(invoke_without_command=True)
def run_single(
    ctx: typer.Context,
    subject: str = typer.Option(
        "tikv",
        "--subject", "-s",
        help="Subject to test (e.g., 'tikv')",
    ),
    chaos: str = typer.Option(
        "node_kill",
        "--chaos", "-c",
        help="Chaos type to inject (e.g., 'node_kill')",
    ),
    baseline: bool = typer.Option(
        False,
        "--baseline", "-b",
        help="Run without agent (self-healing test)",
    ),
    db_path: Path = typer.Option(
        Path("eval.db"),
        "--db",
        help="Path to eval database",
    ),
    operator_db: Optional[Path] = typer.Option(
        None,
        "--operator-db",
        help="Path to operator.db for command extraction",
    ),
    trials: int = typer.Option(
        1,
        "--trials", "-n",
        help="Number of trials to run",
    ),
) -> None:
    """Run evaluation trial(s) against a subject.

    Examples:
        eval run --subject tikv --chaos node_kill
        eval run --baseline
        eval run --trials 5
    """
    # If subcommand was invoked, skip
    if ctx.invoked_subcommand is not None:
        return

    # Validate chaos type
    eval_subject = get_subject(subject)
    available_chaos = eval_subject.get_chaos_types()

    if chaos not in available_chaos:
        raise typer.BadParameter(
            f"Unknown chaos type: {chaos}. Available for {subject}: {available_chaos}"
        )

    # Auto-detect operator.db if not specified
    if operator_db is None and not baseline:
        default_operator_db = Path("data/operator.db")
        if default_operator_db.exists():
            operator_db = default_operator_db
            console.print(f"[dim]Using operator.db: {operator_db}[/dim]")

    # Run evaluation
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()

        if trials == 1:
            # Single trial (CLI-01, CLI-02)
            console.print(f"\n[bold]Running single trial[/bold]")
            console.print(f"Subject: {subject}")
            console.print(f"Chaos: {chaos}")
            console.print(f"Baseline: {baseline}")
            console.print(f"Database: {db_path}\n")

            # Create a single-trial campaign
            from eval.types import Campaign
            from eval.runner.harness import now

            campaign = Campaign(
                subject_name=subject,
                chaos_type=chaos,
                trial_count=1,
                baseline=baseline,
                created_at=now(),
            )
            campaign_id = await db.insert_campaign(campaign)

            trial = await run_trial(
                subject=eval_subject,
                chaos_type=chaos,
                campaign_id=campaign_id,
                baseline=baseline,
                operator_db_path=operator_db,
            )

            trial_id = await db.insert_trial(trial)

            # Print summary
            console.print(f"\n[bold green]Trial complete![/bold green]")
            console.print(f"Campaign ID: {campaign_id}")
            console.print(f"Trial ID: {trial_id}")
            console.print(f"Started: {trial.started_at}")
            console.print(f"Chaos injected: {trial.chaos_injected_at}")
            if trial.ticket_created_at:
                console.print(f"Ticket created: {trial.ticket_created_at}")
            if trial.resolved_at:
                console.print(f"Resolved: {trial.resolved_at}")
            console.print(f"Ended: {trial.ended_at}")

        else:
            # Multiple trials (campaign)
            campaign_id = await run_campaign(
                subject=eval_subject,
                subject_name=subject,
                chaos_type=chaos,
                trial_count=trials,
                db=db,
                baseline=baseline,
                operator_db_path=operator_db,
            )

            console.print(f"\n[bold green]Campaign {campaign_id} complete with {trials} trials[/bold green]")

    asyncio.run(run())


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
