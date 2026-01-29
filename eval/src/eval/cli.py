"""Evaluation harness CLI."""

import asyncio
import json
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


@app.command()
def analyze(
    campaign_id: int = typer.Argument(..., help="Campaign ID to analyze"),
    db_path: Path = typer.Option(
        Path("eval.db"),
        "--db",
        help="Path to eval database",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
    include_commands: bool = typer.Option(
        False,
        "--commands",
        help="Include LLM-based command analysis (requires ANTHROPIC_API_KEY)",
    ),
) -> None:
    """Analyze a campaign and display scores.

    Computes win rate, average detection/resolution times, and outcome breakdown.
    Use --commands flag to include LLM-based command classification for
    destructive command detection (requires ANTHROPIC_API_KEY).

    Examples:
        eval analyze 1
        eval analyze 1 --json
        eval analyze 1 --commands  # Include command analysis
    """
    from eval.analysis import analyze_campaign, CampaignSummary

    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        return await analyze_campaign(db, campaign_id, include_command_analysis=include_commands)

    try:
        summary: CampaignSummary = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(summary.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Campaign {campaign_id}: {summary.subject_name}/{summary.chaos_type}")
    print(f"Trials: {summary.trial_count}")
    print()
    print("Outcomes:")
    print(f"  Success: {summary.success_count} ({summary.win_rate:.1%})")
    print(f"  Failure: {summary.failure_count}")
    print(f"  Timeout: {summary.timeout_count}")
    print()
    print("Timing (successful trials):")
    if summary.avg_time_to_detect_sec is not None:
        print(f"  Avg detection: {summary.avg_time_to_detect_sec:.1f}s")
    else:
        print("  Avg detection: N/A")
    if summary.avg_time_to_resolve_sec is not None:
        print(f"  Avg resolution: {summary.avg_time_to_resolve_sec:.1f}s")
    else:
        print("  Avg resolution: N/A")
    print()
    print("Commands:")
    print(f"  Total: {summary.total_commands}")
    print(f"  Unique: {summary.total_unique_commands}")
    if include_commands:
        print(f"  Destructive: {summary.total_destructive_commands}")


@app.command()
def compare(
    campaign_a: int = typer.Argument(..., help="First campaign ID"),
    campaign_b: int = typer.Argument(..., help="Second campaign ID"),
    db_path: Path = typer.Option(
        Path("eval.db"),
        "--db",
        help="Path to eval database",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
) -> None:
    """Compare two campaigns by win rate.

    Primary metric is win rate. Resolution time is tiebreaker for equal win rates.

    Examples:
        eval compare 1 2
        eval compare 1 2 --json
    """
    from eval.analysis import compare_campaigns, CampaignComparison

    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        return await compare_campaigns(db, campaign_a, campaign_b)

    try:
        result: CampaignComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Campaign Comparison: {result.subject_name}/{result.chaos_type}")
    print()
    print(f"{'Metric':<20} {'Campaign A':<15} {'Campaign B':<15} {'Delta':<15}")
    print("-" * 65)
    print(f"{'Trials':<20} {result.a_trial_count:<15} {result.b_trial_count:<15} {'':<15}")
    print(f"{'Win Rate':<20} {result.a_win_rate:.1%:<15} {result.b_win_rate:.1%:<15} {result.win_rate_delta:+.1%}")

    a_resolve = f"{result.a_avg_resolve_sec:.1f}s" if result.a_avg_resolve_sec else "N/A"
    b_resolve = f"{result.b_avg_resolve_sec:.1f}s" if result.b_avg_resolve_sec else "N/A"
    delta_resolve = f"{result.resolve_time_delta:+.1f}s" if result.resolve_time_delta else ""
    print(f"{'Avg Resolution':<20} {a_resolve:<15} {b_resolve:<15} {delta_resolve}")
    print()
    print(f"Winner: Campaign {result.winner}")
    print(f"Reason: {result.winner_reason}")


@app.command("compare-baseline")
def compare_baseline_cmd(
    campaign_id: int = typer.Argument(..., help="Agent campaign ID"),
    baseline_id: Optional[int] = typer.Option(
        None,
        "--baseline",
        "-b",
        help="Baseline campaign ID (auto-detects if not specified)",
    ),
    db_path: Path = typer.Option(
        Path("eval.db"),
        "--db",
        help="Path to eval database",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
) -> None:
    """Compare agent campaign to baseline (self-healing).

    Shows full metric breakdown: win rate, detection time, resolution time.
    Auto-detects matching baseline campaign if not specified.

    Examples:
        eval compare-baseline 1
        eval compare-baseline 1 --baseline 2
        eval compare-baseline 1 --json
    """
    from eval.analysis import compare_baseline, BaselineComparison

    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        return await compare_baseline(db, campaign_id, baseline_id)

    try:
        result: BaselineComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Baseline Comparison: {result.subject_name}/{result.chaos_type}")
    print(f"Agent Campaign: {result.agent_campaign_id}")
    print(f"Baseline Campaign: {result.baseline_campaign_id}")
    print()
    print(f"{'Metric':<20} {'Agent':<15} {'Baseline':<15} {'Delta':<15}")
    print("-" * 65)
    print(f"{'Trials':<20} {result.agent_trial_count:<15} {result.baseline_trial_count:<15} {'':<15}")
    print(f"{'Win Rate':<20} {result.agent_win_rate:.1%:<15} {result.baseline_win_rate:.1%:<15} {result.win_rate_delta:+.1%}")

    agent_detect = f"{result.agent_avg_detect_sec:.1f}s" if result.agent_avg_detect_sec else "N/A"
    print(f"{'Avg Detection':<20} {agent_detect:<15} {'N/A':<15} {'':<15}")

    agent_resolve = f"{result.agent_avg_resolve_sec:.1f}s" if result.agent_avg_resolve_sec else "N/A"
    baseline_resolve = f"{result.baseline_avg_resolve_sec:.1f}s" if result.baseline_avg_resolve_sec else "N/A"
    delta_resolve = f"{result.resolve_time_delta:+.1f}s" if result.resolve_time_delta else ""
    print(f"{'Avg Resolution':<20} {agent_resolve:<15} {baseline_resolve:<15} {delta_resolve}")
    print()
    print(f"Winner: {result.winner.title()}")
    print(f"Reason: {result.winner_reason}")


@app.command("list")
def list_campaigns(
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of campaigns to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N campaigns"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all campaigns in the database."""
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        campaigns = await db.get_all_campaigns(limit=limit, offset=offset)
        total = await db.count_campaigns()
        return campaigns, total

    campaigns, total = asyncio.run(run())

    if json_output:
        # Output JSON array with keys: id, subject_name, chaos_type, trial_count, baseline, created_at
        data = [
            {
                "id": c.id,
                "subject_name": c.subject_name,
                "chaos_type": c.chaos_type,
                "trial_count": c.trial_count,
                "baseline": c.baseline,
                "created_at": c.created_at,
            }
            for c in campaigns
        ]
        print(json.dumps(data, indent=2))
        return

    # Plain text table with fixed column widths (no Rich tables)
    # Handle empty database case
    if not campaigns:
        print("No campaigns found.")
        print(f"Database: {db_path}")
        return

    # Header row with fixed widths: ID(6), Date(12), Subject(10), Chaos(12), Trials(8), Baseline(8)
    print(f"{'ID':<6} {'Date':<12} {'Subject':<10} {'Chaos':<12} {'Trials':<8} {'Baseline':<8}")
    print("-" * 58)
    for c in campaigns:
        date_str = c.created_at[:10] if c.created_at else "N/A"
        baseline_str = "Yes" if c.baseline else "No"
        print(f"{c.id:<6} {date_str:<12} {c.subject_name:<10} {c.chaos_type:<12} {c.trial_count:<8} {baseline_str:<8}")

    # Show pagination info
    showing_end = min(offset + limit, total)
    print(f"\nShowing {offset + 1}-{showing_end} of {total} campaigns")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
