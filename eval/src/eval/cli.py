"""Evaluation harness CLI."""

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from eval.runner.db import EvalDB
from eval.runner.harness import run_trial, run_campaign, run_campaign_from_config
from eval.runner.campaign import load_campaign_config, CampaignConfig
from eval.subjects.tikv import TiKVEvalSubject
from eval.types import EvalSubject
from eval.variants import load_all_variants

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


@run_app.command("campaign")
def run_campaign_cmd(
    config_path: Path = typer.Argument(..., help="Path to campaign YAML config"),
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
) -> None:
    """Run a campaign from YAML configuration file.

    The config file specifies subjects, chaos types, and trial count.
    Matrix expansion generates all combinations.

    Example config:
        name: tikv-chaos-campaign
        subjects: [tikv]
        chaos_types:
          - type: node_kill
          - type: latency
            params: {min_ms: 50, max_ms: 150}
          - type: disk_pressure
            params: {fill_percent: 80}
        trials_per_combination: 3
        parallel: 2
        cooldown_seconds: 5
        include_baseline: true

    Examples:
        eval run campaign config.yaml
        eval run campaign campaign.yaml --operator-db data/operator.db
    """
    # Validate config file exists
    if not config_path.exists():
        console.print(f"[red]Error: Config file not found: {config_path}[/red]")
        raise typer.Exit(1)

    # Load and validate config
    try:
        config = load_campaign_config(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    # Show campaign summary
    console.print(f"\n[bold]Campaign: {config.name}[/bold]")
    console.print(f"Subjects: {config.subjects}")
    console.print(f"Chaos types: {[c.type for c in config.chaos_types]}")
    console.print(f"Trials per combination: {config.trials_per_combination}")
    console.print(f"Parallel: {config.parallel}")
    console.print(f"Cooldown: {config.cooldown_seconds}s")
    console.print(f"Include baseline: {config.include_baseline}")
    console.print(f"Variant: {config.variant}")

    # Auto-detect operator.db if not specified
    if operator_db is None:
        default_operator_db = Path("data/operator.db")
        if default_operator_db.exists():
            operator_db = default_operator_db
            console.print(f"[dim]Using operator.db: {operator_db}[/dim]")

    # Run campaign
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()

        return await run_campaign_from_config(
            config=config,
            db=db,
            operator_db_path=operator_db,
        )

    campaign_id = asyncio.run(run())
    console.print(f"\n[bold green]Campaign {campaign_id} finished[/bold green]")
    console.print(f"Analyze with: eval analyze {campaign_id}")


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


@app.command("compare-variants")
def compare_variants_cmd(
    subject: str = typer.Argument(..., help="Subject name (e.g., 'tikv')"),
    chaos: str = typer.Argument(..., help="Chaos type (e.g., 'node_kill')"),
    variants: Optional[str] = typer.Option(
        None,
        "--variants", "-v",
        help="Comma-separated variant names to compare (default: all)",
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
    """Compare agent performance across variants.

    Shows balanced scorecard of metrics for each variant tested against
    the same subject and chaos type. No winner determination - user
    interprets tradeoffs.

    Requires campaigns to have been run with different variant configurations.

    Examples:
        eval compare-variants tikv node_kill
        eval compare-variants tikv node_kill --variants haiku-v1,sonnet-v1
        eval compare-variants tikv latency --json
    """
    from eval.analysis import compare_variants, VariantComparison

    # Parse variant names if provided
    variant_list: list[str] | None = None
    if variants:
        variant_list = [v.strip() for v in variants.split(",")]

    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        return await compare_variants(db, subject, chaos, variant_list)

    try:
        result: VariantComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Rich table output - balanced scorecard
    table = Table(title=f"Variant Comparison: {result.subject_name}/{result.chaos_type}")

    table.add_column("Variant", style="cyan")
    table.add_column("Trials", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Avg TTD", justify="right", header_style="dim")
    table.add_column("Avg TTR", justify="right", header_style="dim")
    table.add_column("Avg Commands", justify="right")

    # Sort by variant name for consistent output
    for variant_name in sorted(result.variants.keys()):
        metrics = result.variants[variant_name]
        ttd = f"{metrics.avg_time_to_detect_sec:.1f}s" if metrics.avg_time_to_detect_sec else "N/A"
        ttr = f"{metrics.avg_time_to_resolve_sec:.1f}s" if metrics.avg_time_to_resolve_sec else "N/A"

        table.add_row(
            variant_name,
            str(metrics.trial_count),
            f"{metrics.win_rate:.1%}",
            ttd,
            ttr,
            f"{metrics.avg_commands:.1f}",
        )

    console.print(table)
    console.print(f"\n[dim]TTD = Time to Detect, TTR = Time to Resolve[/dim]")
    console.print(f"[dim]{len(result.variants)} variant(s) compared[/dim]")


@app.command("show")
def show_detail(
    id: int = typer.Argument(..., help="Campaign or trial ID"),
    trial: bool = typer.Option(False, "--trial", "-t", help="Treat ID as trial ID"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show details for a campaign or trial.

    By default, treats ID as a campaign ID. Use --trial flag for trial ID.

    Examples:
        eval show 1              # Show campaign 1
        eval show --trial 5      # Show trial 5
    """
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()

        if trial:
            # Fetch trial by ID
            t = await db.get_trial(id)
            if t is None:
                console.print(f"[red]Error: Trial {id} not found[/red]")
                raise typer.Exit(1)
            return ("trial", t, None, None)
        else:
            # Fetch campaign and its trials
            campaign = await db.get_campaign(id)
            if campaign is None:
                console.print(f"[red]Error: Campaign {id} not found[/red]")
                raise typer.Exit(1)
            trials = await db.get_trials(id)

            # Get campaign analysis for aggregate scores
            from eval.analysis import analyze_campaign
            try:
                summary = await analyze_campaign(db, id)
            except ValueError:
                summary = None
            return ("campaign", campaign, trials, summary)

    result_type, obj, trials, summary = asyncio.run(run())

    if result_type == "trial":
        # Trial detail output
        t = obj
        if json_output:
            # Parse commands_json for output
            commands = json.loads(t.commands_json) if t.commands_json else []
            data = {
                "id": t.id,
                "campaign_id": t.campaign_id,
                "started_at": t.started_at,
                "chaos_injected_at": t.chaos_injected_at,
                "ticket_created_at": t.ticket_created_at,
                "resolved_at": t.resolved_at,
                "ended_at": t.ended_at,
                "initial_state": json.loads(t.initial_state) if t.initial_state else None,
                "final_state": json.loads(t.final_state) if t.final_state else None,
                "chaos_metadata": json.loads(t.chaos_metadata) if t.chaos_metadata else None,
                "commands": commands,
            }
            print(json.dumps(data, indent=2))
            return

        # Plain text trial detail
        print(f"Trial {t.id} (Campaign {t.campaign_id})")
        print("-" * 40)
        print(f"Started:        {t.started_at}")
        print(f"Chaos injected: {t.chaos_injected_at}")
        if t.ticket_created_at:
            print(f"Ticket created: {t.ticket_created_at}")
        if t.resolved_at:
            print(f"Resolved:       {t.resolved_at}")
        print(f"Ended:          {t.ended_at}")
        print()

        # Commands list
        commands = json.loads(t.commands_json) if t.commands_json else []
        if commands:
            print("Commands:")
            for i, cmd in enumerate(commands, 1):
                # Each command is a string or dict with 'command' key
                cmd_str = cmd if isinstance(cmd, str) else cmd.get("command", str(cmd))
                # Indent and truncate long commands
                cmd_display = cmd_str[:80] + "..." if len(cmd_str) > 80 else cmd_str
                print(f"  {i}. {cmd_display}")
        else:
            print("Commands: (none recorded)")
        print()

        # Show initial/final state summary
        print("States (use --json for full detail):")
        print(f"  Initial: {len(t.initial_state)} bytes")
        print(f"  Final:   {len(t.final_state)} bytes")

    else:
        # Campaign detail output
        campaign = obj
        if json_output:
            data = {
                "id": campaign.id,
                "subject_name": campaign.subject_name,
                "chaos_type": campaign.chaos_type,
                "trial_count": campaign.trial_count,
                "baseline": campaign.baseline,
                "created_at": campaign.created_at,
                "trials": [
                    {
                        "id": t.id,
                        "started_at": t.started_at,
                        "resolved_at": t.resolved_at,
                        "ended_at": t.ended_at,
                    }
                    for t in trials
                ],
            }
            if summary:
                data["win_rate"] = summary.win_rate
                data["success_count"] = summary.success_count
                data["failure_count"] = summary.failure_count
                data["timeout_count"] = summary.timeout_count
            print(json.dumps(data, indent=2))
            return

        # Plain text campaign detail
        print(f"Campaign {campaign.id}: {campaign.subject_name}/{campaign.chaos_type}")
        print("-" * 50)
        print(f"Created:  {campaign.created_at}")
        print(f"Trials:   {campaign.trial_count}")
        print(f"Baseline: {'Yes' if campaign.baseline else 'No'}")
        print()

        # Aggregate scores if available
        if summary:
            print("Scores:")
            print(f"  Win rate:   {summary.win_rate:.1%}")
            print(f"  Success:    {summary.success_count}")
            print(f"  Failure:    {summary.failure_count}")
            print(f"  Timeout:    {summary.timeout_count}")
            if summary.avg_time_to_detect_sec:
                print(f"  Avg detect: {summary.avg_time_to_detect_sec:.1f}s")
            if summary.avg_time_to_resolve_sec:
                print(f"  Avg resolve: {summary.avg_time_to_resolve_sec:.1f}s")
            print()

        # Trial list table
        if trials:
            print("Trials:")
            # Header: ID(6), Started(20), Resolved(20), Status
            print(f"  {'ID':<6} {'Started':<20} {'Resolved':<20}")
            for t in trials:
                resolved_str = t.resolved_at[:19] if t.resolved_at else "N/A"
                started_str = t.started_at[:19] if t.started_at else "N/A"
                print(f"  {t.id:<6} {started_str:<20} {resolved_str:<20}")
        else:
            print("No trials recorded.")


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
        # Output JSON array with keys: id, subject_name, chaos_type, trial_count, baseline, variant_name, created_at
        data = [
            {
                "id": c.id,
                "subject_name": c.subject_name,
                "chaos_type": c.chaos_type,
                "trial_count": c.trial_count,
                "baseline": c.baseline,
                "variant_name": getattr(c, 'variant_name', 'default'),
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

    # Header row with fixed widths: ID(6), Date(12), Subject(10), Chaos(12), Variant(12), Trials(8), Baseline(8)
    print(f"{'ID':<6} {'Date':<12} {'Subject':<10} {'Chaos':<12} {'Variant':<12} {'Trials':<8} {'Baseline':<8}")
    print("-" * 70)
    for c in campaigns:
        date_str = c.created_at[:10] if c.created_at else "N/A"
        baseline_str = "Yes" if c.baseline else "No"
        variant_str = getattr(c, 'variant_name', 'default')[:10]
        print(f"{c.id:<6} {date_str:<12} {c.subject_name:<10} {c.chaos_type:<12} {variant_str:<12} {c.trial_count:<8} {baseline_str:<8}")

    # Show pagination info
    showing_end = min(offset + limit, total)
    print(f"\nShowing {offset + 1}-{showing_end} of {total} campaigns")


@app.command()
def viewer(
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    operator_db: Optional[Path] = typer.Option(None, "--operator-db", help="Path to operator.db for reasoning"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
) -> None:
    """Start the web viewer for browsing campaigns and trials."""
    import uvicorn
    from eval.viewer import create_app

    # Auto-detect operator.db if not specified
    if operator_db is None:
        default = Path("data/operator.db")
        if default.exists():
            operator_db = default
            console.print(f"[dim]Using operator.db: {operator_db}[/dim]")

    if not db_path.exists():
        console.print(f"[yellow]Warning: Database {db_path} does not exist. Will be created on first access.[/yellow]")

    app_instance = create_app(db_path, operator_db)
    console.print(f"Starting viewer at http://{host}:{port}")
    uvicorn.run(app_instance, host=host, port=port)


@app.command("list-variants")
def list_variants_cmd(
    variants_dir: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Path to variants directory (default: eval/variants/)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List available agent configuration variants.

    Shows all variants found in the variants directory with their model and
    system prompt preview.

    Examples:
        eval list-variants
        eval list-variants --json
        eval list-variants --dir ./my-variants/
    """
    variants = load_all_variants(variants_dir)

    if not variants:
        console.print("[yellow]No variants found[/yellow]")
        if variants_dir:
            console.print(f"Directory: {variants_dir}")
        else:
            console.print("Default directory: eval/variants/")
        return

    if json_output:
        data = [
            {
                "name": v.name,
                "model": v.model,
                "system_prompt_preview": v.system_prompt[:100] + "..." if len(v.system_prompt) > 100 else v.system_prompt,
                "tools_config": v.tools_config,
            }
            for v in variants.values()
        ]
        print(json.dumps(data, indent=2))
        return

    # Plain text table
    table = Table(title="Available Variants")
    table.add_column("Name", style="cyan")
    table.add_column("Model")
    table.add_column("System Prompt Preview")
    table.add_column("Tools")

    for v in sorted(variants.values(), key=lambda x: x.name):
        prompt_preview = v.system_prompt.split('\n')[0][:50]
        if len(v.system_prompt) > 50 or '\n' in v.system_prompt:
            prompt_preview += "..."
        tools = ", ".join(v.tools_config.get("enabled_tools", ["(default)"])[:3])
        table.add_row(v.name, v.model, prompt_preview, tools)

    console.print(table)
    console.print(f"\n{len(variants)} variant(s) found")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
