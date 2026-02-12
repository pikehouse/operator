"""Evaluation harness CLI."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from eval.runner.db import EvalDB, EvalDBProtocol, get_db
from eval.runner.harness import run_trial, run_campaign, run_campaign_from_config, get_repo_info
from eval.runner.campaign import load_campaign_config, CampaignConfig
from eval.subjects.factory import SubjectRegistry
from eval.types import EvalSubject, get_chaos_description, safe_json_loads
from eval.variants import load_all_variants


def _load_dotenv() -> None:
    """Auto-discover and load .env files, walking up from cwd.

    Searches current directory and ancestors for .env files.
    Does not override variables already set in the environment.
    """
    directory = Path.cwd()
    while True:
        env_file = directory / ".env"
        if env_file.is_file():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        parent = directory.parent
        if parent == directory:
            break
        directory = parent


_load_dotenv()

app = typer.Typer(
    name="eval",
    help="Evaluation harness for chaos engineering trials",
    no_args_is_help=True,
)

run_app = typer.Typer(help="Run evaluation trials")
app.add_typer(run_app, name="run")

worker_app = typer.Typer(help="Distributed worker commands")
app.add_typer(worker_app, name="worker")

console = Console()


async def _get_db_or_exit(remote: bool, db_path: Path) -> EvalDBProtocol:
    """CLI wrapper around get_db() that exits on error."""
    try:
        return await get_db(remote=remote, db_path=db_path)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def get_subject(subject_name: str, mode: str = "local") -> EvalSubject:
    """Load eval subject by name and mode.

    Args:
        subject_name: Subject identifier (e.g., 'tikv')
        mode: Execution mode ('local' or 'cloud-gcp')

    Returns:
        EvalSubject implementation

    Raises:
        typer.BadParameter: If subject not found
    """
    try:
        return SubjectRegistry.create(subject_name.lower(), instance_id=0, mode=mode)
    except ValueError as e:
        available = SubjectRegistry.list_subjects()
        raise typer.BadParameter(f"Unknown subject: {subject_name}. Available: {available}")


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
    operator_running: bool = typer.Option(
        False,
        "--operator-running",
        help="Operator monitor/agent already running externally (skip managed mode)",
    ),
) -> None:
    """Run evaluation trial(s) against a subject.

    By default, starts operator monitor and agent automatically (managed mode).
    Use --operator-running if you already have them running externally.

    Examples:
        eval run --subject tikv --chaos node_kill
        eval run --baseline
        eval run --trials 5
        eval run --operator-running  # Skip managed mode
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

    # Set operator.db path
    # In managed mode, we control the path; in external mode, try to auto-detect
    if operator_db is None:
        operator_db = Path("data/operator.db")

    # Run evaluation
    async def run():
        from eval.runner.operator import OperatorProcesses

        db = EvalDB(db_path)
        await db.ensure_schema()

        # Capture git info
        commit_hash, is_operator_repo = get_repo_info()

        # Display config
        console.print(f"\n[bold]Running {'single trial' if trials == 1 else f'{trials} trials'}[/bold]")
        console.print(f"Subject: {subject}")
        console.print(f"Chaos: {chaos}")
        console.print(f"Baseline: {baseline}")
        console.print(f"Database: {db_path}")
        console.print(f"Git commit: {commit_hash[:8]}")
        managed_mode = not operator_running and not baseline
        console.print(f"Operator: {'managed' if managed_mode else 'external' if operator_running else 'skipped (baseline)'}")
        if not is_operator_repo:
            console.print("[yellow]Warning: not running from operator repo — commit hash may not reflect operator code[/yellow]")
        console.print()

        async def execute_trials(skip_reset: bool = False, resolved_db_path: Path | None = None):
            """Execute the actual trials."""
            db_path_to_use = resolved_db_path or operator_db
            if trials == 1:
                # Single trial (CLI-01, CLI-02)
                from eval.types import Campaign
                from eval.runner.harness import now

                campaign = Campaign(
                    subject_name=subject,
                    name=f"{subject}/{chaos}",
                    trial_count=1,
                    baseline=baseline,
                    git_commit_hash=commit_hash,
                    created_at=now(),
                )
                campaign_id = await db.insert_campaign(campaign)

                trial = await run_trial(
                    subject=eval_subject,
                    chaos_type=chaos,
                    campaign_id=campaign_id,
                    baseline=baseline,
                    operator_db_path=db_path_to_use,
                    skip_reset=skip_reset,
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
                    operator_db_path=db_path_to_use,
                    git_commit_hash=commit_hash,
                )

                console.print(f"\n[bold green]Campaign {campaign_id} complete with {trials} trials[/bold green]")

        # Run with managed operator or external
        if managed_mode:
            # Managed mode: start/stop operator automatically
            # Pass eval_subject so it can reset cluster before starting monitor
            async with OperatorProcesses(subject, operator_db, eval_subject=eval_subject) as op:
                # skip_reset=True because OperatorProcesses already reset the cluster
                # Use op.operator_db_path which is resolved to absolute path
                await execute_trials(skip_reset=True, resolved_db_path=op.operator_db_path)
        else:
            # External mode or baseline: just run trials
            await execute_trials(skip_reset=False)

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
    operator_running: bool = typer.Option(
        False,
        "--operator-running",
        help="Operator monitor/agent already running externally (skip managed mode)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model", "-m",
        help="Override model (e.g., 'claude-sonnet-4-20250514', 'claude-opus-4-20250514')",
    ),
    cloud: Optional[str] = typer.Option(
        None,
        "--cloud",
        help="Run on cloud (e.g., 'gcp'). Enables dangerous chaos types.",
    ),
    parallel_workers: int = typer.Option(
        1,
        "--parallel",
        help="Number of parallel workers (cloud mode only)",
    ),
) -> None:
    """Run a campaign from YAML configuration file.

    The config file specifies subjects, chaos types, and trial count.
    Matrix expansion generates all combinations.

    By default, starts operator monitor and agent automatically (managed mode).
    Use --operator-running if you already have them running externally.

    Cloud Mode (--cloud=gcp):
        - Uses GCP VMs for execution
        - Enables dangerous chaos types (disk_pressure, memory_exhaustion)
        - Requires EVAL_DATABASE_URL env var for PostgreSQL

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
        eval run campaign config.yaml --operator-running
        eval run campaign config.yaml --cloud=gcp --parallel 5
    """
    import os
    from eval.runner.operator import OperatorProcesses

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

    # Determine cloud mode (CLI flag takes precedence over config)
    cloud_mode = cloud or (config.cloud.provider if config.cloud else None)
    execution_mode = f"cloud-{cloud_mode}" if cloud_mode else "local"

    # Validate cloud-only chaos types
    if not cloud_mode:
        cloud_only_types = {"disk_pressure", "memory_exhaustion", "cpu_starvation"}
        requested_types = {c.type for c in config.chaos_types}
        invalid_types = requested_types & cloud_only_types
        if invalid_types:
            console.print(
                f"[red]Error: Chaos types {invalid_types} require --cloud flag[/red]"
            )
            raise typer.Exit(1)

    # Set operator.db path
    if operator_db is None:
        operator_db = Path("data/operator.db")

    # Determine if managed mode
    # Note: include_baseline doesn't affect this - baseline trials run without
    # chaos but still need the operator running for non-baseline trials
    managed_mode = not operator_running and not cloud_mode

    # Capture git info
    commit_hash, is_operator_repo = get_repo_info()

    # Show campaign summary
    console.print(f"\n[bold]Campaign: {config.name}[/bold]")
    console.print(f"Subjects: {config.subjects}")
    console.print(f"Chaos types: {[c.type for c in config.chaos_types]}")
    console.print(f"Trials per combination: {config.trials_per_combination}")
    console.print(f"Parallel: {parallel_workers if cloud_mode else config.parallel}")
    console.print(f"Cooldown: {config.cooldown_seconds}s")
    console.print(f"Include baseline: {config.include_baseline}")
    if config.continuous:
        console.print(f"Continuous: [bold cyan]true[/bold cyan] (state persists between trials)")
    console.print(f"Variant: {config.variant}")
    if model:
        console.print(f"Model override: {model}")
    console.print(f"Mode: {execution_mode}")
    console.print(f"Operator: {'managed' if managed_mode else 'external' if operator_running else 'cloud'}")
    console.print(f"Git commit: {commit_hash[:8]}")
    if not is_operator_repo:
        console.print("[yellow]Warning: not running from operator repo — commit hash may not reflect operator code[/yellow]")

    # Cloud mode execution
    if cloud_mode:
        async def run_cloud():
            from eval.runner.db_postgres import PostgresDB
            from eval.runner.queue import WorkQueue
            from eval.runner.campaign import expand_campaign_matrix

            # Get PostgreSQL connection URL
            db_url = os.environ.get("EVAL_DATABASE_URL")
            if config.cloud and config.cloud.database_url:
                db_url = config.cloud.database_url

            if not db_url:
                console.print(
                    "[red]Error: EVAL_DATABASE_URL env var or cloud.database_url required for cloud mode[/red]"
                )
                raise typer.Exit(1)

            # Connect to PostgreSQL
            db = PostgresDB(db_url)
            await db.ensure_schema()
            queue = WorkQueue(db)

            # Create campaign
            from eval.types import Campaign
            from eval.runner.harness import now

            trial_specs = expand_campaign_matrix(config)
            campaign = Campaign(
                subject_name=config.subjects[0] if config.subjects else "tikv",
                name=config.name,
                trial_count=len(trial_specs),
                baseline=config.include_baseline,
                continuous=config.continuous,
                variant_name=config.variant,
                git_commit_hash=commit_hash,
                created_at=now(),
            )
            campaign_id = await db.insert_campaign(campaign)
            console.print(f"[green]Created campaign {campaign_id} in cloud database[/green]")

            # Enqueue work items
            work_items = [
                {
                    "subject_type": spec["subject"],
                    "chaos_type": spec["chaos_type"],
                    "chaos_params": spec["chaos_params"],
                    "baseline": spec["baseline"],
                    "sequence_number": spec["sequence_number"],
                }
                for spec in trial_specs
            ]
            work_ids = await queue.enqueue(campaign_id, work_items)
            console.print(f"[green]Enqueued {len(work_ids)} work items[/green]")

            # Show operator status
            if config.cloud and config.cloud.operator and config.cloud.operator.enabled:
                console.print(
                    f"[green]Operator enabled: {config.cloud.operator.image}[/green]"
                )
                operator_flag = f" --operator-image={config.cloud.operator.image}"
            else:
                operator_flag = ""

            # In cloud mode, we just enqueue - workers run separately
            console.print(f"\n[bold cyan]Work enqueued. Start workers with:[/bold cyan]")
            console.print(f"  eval worker start --cloud={cloud_mode}{operator_flag}")

            await db.close()
            return campaign_id

        campaign_id = asyncio.run(run_cloud())
        console.print(f"\n[bold green]Campaign {campaign_id} created (cloud mode)[/bold green]")
        console.print(f"Monitor with: eval show {campaign_id}")
        return

    # Local mode execution
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()

        async def execute_campaign(resolved_db_path: Path):
            return await run_campaign_from_config(
                config=config,
                db=db,
                operator_db_path=resolved_db_path,
                model_override=model,
                git_commit_hash=commit_hash,
            )

        if managed_mode:
            # Managed mode: start/stop operator for the campaign
            # Use first subject for monitor (campaigns usually test one subject)
            subject_name = config.subjects[0] if config.subjects else "tikv"

            # For subjects with code workspaces, create the eval subject first
            # so we can pass workspace context to the operator
            eval_subject = None
            subject_context_extra = None
            if subject_name == "chat-db-app":
                from eval.subjects.factory import SubjectRegistry
                eval_subject = SubjectRegistry.create(subject_name, instance_id=0)
                # Ensure workspace is set up
                await eval_subject._ensure_workspace()
                subject_context_extra = eval_subject.get_agent_context()

            async with OperatorProcesses(
                subject_name,
                operator_db,
                eval_subject=eval_subject,
                subject_context_extra=subject_context_extra,
            ) as op:
                # Use the resolved path from OperatorProcesses (relative to project root)
                return await execute_campaign(op.operator_db_path)
        else:
            # External mode: use path as-is (user is responsible for correct path)
            return await execute_campaign(operator_db)

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
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
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
        eval analyze 1 --remote    # Query cloud database
    """
    from eval.analysis import analyze_campaign, CampaignSummary

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            return await analyze_campaign(db, campaign_id, include_command_analysis=include_commands)
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        summary: CampaignSummary = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(summary.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Campaign {campaign_id}: {summary.name}")
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
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Compare two campaigns by win rate.

    Primary metric is win rate. Resolution time is tiebreaker for equal win rates.

    Examples:
        eval compare 1 2
        eval compare 1 2 --json
        eval compare 1 2 --remote
    """
    from eval.analysis import compare_campaigns, CampaignComparison

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            return await compare_campaigns(db, campaign_a, campaign_b)
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        result: CampaignComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Campaign Comparison: {result.name}")
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
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Compare agent campaign to baseline (self-healing).

    Shows full metric breakdown: win rate, detection time, resolution time.
    Auto-detects matching baseline campaign if not specified.

    Examples:
        eval compare-baseline 1
        eval compare-baseline 1 --baseline 2
        eval compare-baseline 1 --json
        eval compare-baseline 1 --remote
    """
    from eval.analysis import compare_baseline, BaselineComparison

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            return await compare_baseline(db, campaign_id, baseline_id)
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        result: BaselineComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Plain text output
    print(f"Baseline Comparison: {result.name}")
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
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
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
        eval compare-variants tikv latency --remote
    """
    from eval.analysis import compare_variants, VariantComparison

    # Parse variant names if provided
    variant_list: list[str] | None = None
    if variants:
        variant_list = [v.strip() for v in variants.split(",")]

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            return await compare_variants(db, subject, chaos, variant_list)
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        result: VariantComparison = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Rich table output - balanced scorecard
    table = Table(title=f"Variant Comparison: {result.name}")

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


@app.command("behavior")
def behavior_cmd(
    campaign_id: int = typer.Argument(..., help="Campaign ID to classify"),
    trial_id: Optional[int] = typer.Option(
        None,
        "--trial", "-t",
        help="Classify a single trial only",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-classify even if already done",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output as JSON",
    ),
    db_path: Path = typer.Option(
        Path("eval.db"),
        "--db",
        help="Path to eval database",
    ),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Classify agent behavior into strategic phases.

    Analyzes each trial's reasoning/command timeline and classifies it
    into high-level behavioral phases (investigate, change_config, deploy,
    etc.) using Haiku. Results are stored and displayed as colored timelines.

    Examples:
        eval behavior 1
        eval behavior 1 -t 5         # Single trial
        eval behavior 1 --force      # Re-classify
        eval behavior 1 --json       # JSON output
        eval behavior 1 --remote     # Use PostgreSQL
    """
    from eval.analysis.behavior import (
        classify_campaign_behavior,
        BehaviorTimeline,
        ACTION_COLORS,
    )
    from eval.analysis.scoring import score_trial
    from rich.text import Text

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            timelines = await classify_campaign_behavior(
                db, campaign_id, force=force, trial_id=trial_id,
            )
            # Also fetch campaign and trials for display context
            campaign = await db.get_campaign(campaign_id)
            trials = await db.get_trials(campaign_id)
            return timelines, campaign, trials
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        timelines, campaign, trials = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if json_output:
        data = [t.model_dump() for t in timelines]
        print(json.dumps(data, indent=2))
        return

    # Build trial_id -> score lookup
    trial_scores = {}
    for t in trials:
        score = score_trial(t, campaign.subject_name)
        trial_scores[t.id] = score

    console.print(f"\n[bold]Campaign {campaign_id}: {campaign.name}[/bold]\n")

    # Build trial_id -> timeline lookup
    timeline_map = {tl.trial_id: tl for tl in timelines}

    for t in trials:
        if trial_id is not None and t.id != trial_id:
            continue

        tl = timeline_map.get(t.id)
        score = trial_scores.get(t.id)

        # Build colored pill line using Rich markup
        line = Text()
        line.append(f"T-{t.id:02d}: ", style="bold")

        if tl and tl.phases:
            for i, phase in enumerate(tl.phases):
                colors = ACTION_COLORS.get(phase.action_type.value, ACTION_COLORS["investigate"])
                # Use Rich style approximation
                style_map = {
                    "investigate": "dim",
                    "change_config": "yellow",
                    "change_code": "green",
                    "change_db": "cyan",
                    "deploy": "bold",
                    "observe": "blue",
                    "bad_action": "red bold",
                    "revert": "dark_orange",
                }
                style = style_map.get(phase.action_type.value, "")
                line.append(f"[{phase.label}]", style=style)
                if i < len(tl.phases) - 1:
                    line.append(" \u2192 ", style="dim")
        else:
            line.append("(no behavior data)", style="dim italic")

        # Append outcome
        if score:
            outcome_style = "green" if score.resolved else "red"
            line.append(f"  {score.outcome.value.upper()}", style=outcome_style)

        console.print(line)

    console.print()


@app.command("export")
def export_cmd(
    campaign_id: int = typer.Argument(..., help="Campaign ID to export"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output HTML file path (default: campaign-<id>.html)"
    ),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
) -> None:
    """Export a campaign as a self-contained HTML file.

    Generates a single HTML file with all campaign data, trial details,
    reasoning timelines, code diffs, and timing — viewable in any browser
    with no server required.

    Examples:
        eval export 1
        eval export 1 -o results.html
        eval export 1 --remote
    """
    from eval.export import export_campaign_html

    out_path = output or Path(f"campaign-{campaign_id}.html")

    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            return await export_campaign_html(db, campaign_id)
        finally:
            if hasattr(db, 'close'):
                await db.close()

    try:
        html = asyncio.run(run())
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    out_path.write_text(html)
    size_kb = out_path.stat().st_size / 1024
    console.print(f"[green]Exported campaign {campaign_id} to {out_path} ({size_kb:.0f} KB)[/green]")


@app.command("show")
def show_detail(
    id: int = typer.Argument(..., help="Campaign or trial ID"),
    trial: bool = typer.Option(False, "--trial", "-t", help="Treat ID as trial ID"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    diff: bool = typer.Option(False, "--diff", help="Output raw diff for trial (pipe-friendly)"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
) -> None:
    """Show details for a campaign or trial.

    By default, treats ID as a campaign ID. Use --trial flag for trial ID.

    Examples:
        eval show 1              # Show campaign 1
        eval show --trial 5      # Show trial 5
        eval show --trial 5 --diff  # Output raw diff
        eval show 1 --remote     # Show from cloud database
    """
    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
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
        finally:
            if hasattr(db, 'close'):
                await db.close()

    result_type, obj, trials, summary = asyncio.run(run())

    if result_type == "trial":
        # Trial detail output
        t = obj
        chaos_meta = json.loads(t.chaos_metadata) if t.chaos_metadata else {}

        if json_output:
            commands = safe_json_loads(t.commands_json, [])
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
                "chaos_metadata": chaos_meta,
                "commands": commands,
            }
            print(json.dumps(data, indent=2))
            return

        if diff:
            # Raw diff output (pipe-friendly)
            final_state = safe_json_loads(t.final_state)
            raw_diff = ""
            if isinstance(final_state, dict):
                raw_diff = final_state.get("code_diff", "")
                if not raw_diff:
                    cw = final_state.get("code_workspace")
                    if isinstance(cw, dict):
                        raw_diff = cw.get("diff_full") or cw.get("diff", "")
            if raw_diff:
                print(raw_diff)
            else:
                console.print("[yellow]No diff found in trial final_state[/yellow]")
            return

        # Plain text trial detail
        print(f"Trial {t.id} (Campaign {t.campaign_id})")
        print("-" * 40)

        # Chaos injection details
        print("Chaos Injection:")
        chaos_type = chaos_meta.get("chaos_type", "unknown")
        print(f"  Type:   {chaos_type}")
        if chaos_meta.get("target_container"):
            print(f"  Target: {chaos_meta['target_container']}")
        if chaos_meta.get("signal"):
            print(f"  Signal: {chaos_meta['signal']}")
        if chaos_meta.get("min_ms") is not None:
            print(f"  Latency: {chaos_meta.get('min_ms')}-{chaos_meta.get('max_ms')}ms")
        if chaos_meta.get("fill_percent") is not None:
            print(f"  Disk fill: {chaos_meta['fill_percent']}%")
        if chaos_meta.get("blocked_ips"):
            print(f"  Blocked IPs: {', '.join(chaos_meta['blocked_ips'])}")
        print()

        # Timing with deltas
        print("Timing:")
        print(f"  Started:        {t.started_at[:19] if t.started_at else 'N/A'}")
        print(f"  Chaos injected: {t.chaos_injected_at[:19] if t.chaos_injected_at else 'N/A'}")

        # Calculate time deltas
        from eval.analysis.scoring import compute_duration_seconds

        delta_detect = compute_duration_seconds(t.chaos_injected_at, t.ticket_created_at)
        if delta_detect is not None:
            print(f"  Ticket created: {t.ticket_created_at[:19]} (+{delta_detect:.0f}s after chaos)")
        elif t.ticket_created_at:
            print(f"  Ticket created: {t.ticket_created_at[:19]}")

        delta_resolve = compute_duration_seconds(t.ticket_created_at or "", t.resolved_at)
        if delta_resolve is not None:
            print(f"  Resolved:       {t.resolved_at[:19]} (+{delta_resolve:.0f}s to resolve)")
        elif t.resolved_at:
            print(f"  Resolved:       {t.resolved_at[:19]}")
        else:
            print(f"  Resolved:       Not resolved")

        print(f"  Ended:          {t.ended_at[:19] if t.ended_at else 'N/A'}")
        print()

        # Commands list
        commands = safe_json_loads(t.commands_json, [])
        if commands:
            print(f"Commands ({len(commands)}):")
            for i, cmd in enumerate(commands, 1):
                # Extract command string - handle various formats
                if isinstance(cmd, str):
                    cmd_str = cmd
                elif isinstance(cmd, dict):
                    # Try to get command from tool_params (JSON string)
                    tool_params = cmd.get("tool_params", "")
                    if tool_params:
                        try:
                            params = json.loads(tool_params) if isinstance(tool_params, str) else tool_params
                            cmd_str = params.get("command", str(cmd))
                        except json.JSONDecodeError:
                            cmd_str = cmd.get("command", str(cmd))
                    else:
                        cmd_str = cmd.get("command", str(cmd))
                else:
                    cmd_str = str(cmd)
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

        # Code workspace summary
        final_state = safe_json_loads(t.final_state)
        if isinstance(final_state, dict):
            cw = final_state.get("code_workspace")
            if isinstance(cw, dict):
                print()
                print("Code Workspace:")
                print(f"  Commit: {cw.get('commit', cw.get('commit_hash', 'N/A'))}")
                print(f"  Dirty:  {cw.get('dirty', 'N/A')}")
                if cw.get("log"):
                    print("  Log:")
                    for line in cw["log"].split("\n")[:10]:
                        print(f"    {line}")
            code_diff = final_state.get("code_diff") or ((cw.get("diff_full") or cw.get("diff")) if isinstance(cw, dict) else None)
            if code_diff:
                lines = code_diff.strip().split("\n")
                print(f"\n  Diff ({len(lines)} lines, use --diff for full):")
                for line in lines[:20]:
                    print(f"    {line}")
                if len(lines) > 20:
                    print(f"    ... ({len(lines) - 20} more lines)")

            # Database config changes
            initial_state = safe_json_loads(t.initial_state)
            if isinstance(initial_state, dict):
                init_db = initial_state.get("db_config")
                final_db = final_state.get("db_config")
                if init_db or final_db:
                    from eval.analysis.db_config_diff import diff_db_config

                    db_diff = diff_db_config(init_db, final_db)
                    if db_diff["has_changes"]:
                        print(f"\nDatabase Config Changes:")
                        for s in db_diff["settings_changed"]:
                            print(f"  Setting {s['name']}: {s['before']} -> {s['after']}")
                        for idx in db_diff["indexes_added"]:
                            print(f"  + Index: {idx['definition']}")
                        for idx in db_diff["indexes_removed"]:
                            print(f"  - Index: {idx['definition']}")
                        for tbl in db_diff["tables_added"]:
                            print(f"  + Table: {tbl}")
                        for tbl in db_diff["tables_removed"]:
                            print(f"  - Table: {tbl}")
                        for col in db_diff["columns_added"]:
                            print(f"  + Column: {col['table']}.{col['name']} ({col['type']})")
                        for col in db_diff["columns_removed"]:
                            print(f"  - Column: {col['table']}.{col['name']} ({col['type']})")

    else:
        # Campaign detail output
        campaign = obj
        if json_output:
            data = {
                "id": campaign.id,
                "subject_name": campaign.subject_name,
                "name": campaign.name,
                "trial_count": campaign.trial_count,
                "baseline": campaign.baseline,
                "notable": campaign.notable,
                "notes": campaign.notes,
                "git_commit_hash": campaign.git_commit_hash,
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
        print(f"Campaign {campaign.id}: {campaign.name}")
        print("-" * 50)
        print(f"Name:     {campaign.name}")
        print(f"Subject:  {campaign.subject_name}")
        print(f"Created:  {campaign.created_at}")
        print(f"Trials:   {campaign.trial_count}")
        print(f"Baseline: {'Yes' if campaign.baseline else 'No'}")
        if campaign.notable:
            print(f"Notable:  Yes")
        if campaign.notes:
            print(f"Notes:    {campaign.notes}")
        if campaign.git_commit_hash:
            print(f"Commit:   {campaign.git_commit_hash}")
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
            # Header: ID(6), Started(20), Resolved(20), Status(10)
            print(f"  {'ID':<6} {'Started':<20} {'Resolved':<20} {'Status':<10}")
            for t in trials:
                resolved_str = t.resolved_at[:19] if t.resolved_at else "N/A"
                started_str = t.started_at[:19] if t.started_at else "N/A"
                # Determine status
                if t.resolved_at:
                    status = "Success"
                elif t.ended_at:
                    status = "Timeout"
                else:
                    status = "Running"
                print(f"  {t.id:<6} {started_str:<20} {resolved_str:<20} {status:<10}")
        else:
            print("No trials recorded.")


@app.command("notable")
def notable_cmd(
    campaign_id: int = typer.Argument(..., help="Campaign ID to mark/unmark"),
    clear: bool = typer.Option(False, "--clear", help="Remove notable mark"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
) -> None:
    """Mark or unmark a campaign as notable.

    Notable campaigns are significant results worth revisiting — reference
    baselines, interesting agent behavior, etc.

    Examples:
        eval notable 42
        eval notable 42 --clear
        eval notable 42 --remote
    """
    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            campaign = await db.get_campaign(campaign_id)
            if campaign is None:
                console.print(f"[red]Error: Campaign {campaign_id} not found[/red]")
                raise typer.Exit(1)
            notable = not clear
            await db.update_campaign_notable(campaign_id, notable)
            if notable:
                console.print(f"Campaign {campaign_id} marked as notable")
            else:
                console.print(f"Campaign {campaign_id} unmarked")
        finally:
            if hasattr(db, 'close'):
                await db.close()

    asyncio.run(run())


@app.command("note")
def note_cmd(
    campaign_id: int = typer.Argument(..., help="Campaign ID to annotate"),
    text: Optional[str] = typer.Argument(None, help="Note text (omit to view current note)"),
    clear: bool = typer.Option(False, "--clear", help="Clear the note"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
) -> None:
    """Set, view, or clear a campaign note.

    Notes are free-text annotations for capturing context — what was
    interesting, what the baseline was for, observations about agent behavior.

    Examples:
        eval note 42 "Reference baseline for TiKV node_kill"
        eval note 42                # View current note
        eval note 42 --clear        # Clear the note
    """
    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            campaign = await db.get_campaign(campaign_id)
            if campaign is None:
                console.print(f"[red]Error: Campaign {campaign_id} not found[/red]")
                raise typer.Exit(1)

            if clear:
                await db.update_campaign_notes(campaign_id, "")
                console.print(f"Campaign {campaign_id} note cleared")
            elif text is not None:
                await db.update_campaign_notes(campaign_id, text)
                console.print(f"Campaign {campaign_id} note updated")
            else:
                # View current note
                if campaign.notes:
                    console.print(campaign.notes)
                else:
                    console.print(f"[dim]Campaign {campaign_id} has no note[/dim]")
        finally:
            if hasattr(db, 'close'):
                await db.close()

    asyncio.run(run())


@app.command("list")
def list_campaigns(
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of campaigns to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N campaigns"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
    notable: bool = typer.Option(False, "--notable", help="Show only notable campaigns"),
) -> None:
    """List all campaigns in the database."""
    async def run():
        db = await _get_db_or_exit(remote, db_path)
        try:
            campaigns = await db.get_all_campaigns(limit=limit, offset=offset)
            total = await db.count_campaigns()
            return campaigns, total
        finally:
            if hasattr(db, 'close'):
                await db.close()

    campaigns, total = asyncio.run(run())

    # Filter to notable only if requested
    if notable:
        campaigns = [c for c in campaigns if c.notable]

    if json_output:
        data = [
            {
                "id": c.id,
                "subject_name": c.subject_name,
                "name": c.name,
                "trial_count": c.trial_count,
                "baseline": c.baseline,
                "notable": c.notable,
                "notes": c.notes,
                "variant_name": getattr(c, 'variant_name', 'default'),
                "git_commit_hash": c.git_commit_hash,
                "created_at": c.created_at,
            }
            for c in campaigns
        ]
        print(json.dumps(data, indent=2))
        return

    # Plain text table with fixed column widths (no Rich tables)
    # Handle empty database case
    if not campaigns:
        if notable:
            print("No notable campaigns found.")
        else:
            print("No campaigns found.")
            print(f"Database: {db_path}")
        return

    # Header row with fixed widths: ID(6), Date(12), Name(30), Variant(12), Trials(8), Baseline(8), Commit(10)
    print(f"{'ID':<6} {'Date':<12} {'Name':<30} {'Variant':<12} {'Trials':<8} {'Baseline':<8} {'Commit':<10}")
    print("-" * 88)
    for c in campaigns:
        date_str = c.created_at[:10] if c.created_at else "N/A"
        baseline_str = "Yes" if c.baseline else "No"
        variant_str = getattr(c, 'variant_name', 'default')[:10]
        name_display = c.name[:28] if c.name else "N/A"
        if c.notable:
            name_display = f"\u25c6 {name_display}"[:30]
        name_str = name_display
        commit_str = c.git_commit_hash[:8] if c.git_commit_hash else ""
        print(f"{c.id:<6} {date_str:<12} {name_str:<30} {variant_str:<12} {c.trial_count:<8} {baseline_str:<8} {commit_str:<10}")

    # Show pagination info
    showing_end = min(offset + limit, total)
    print(f"\nShowing {offset + 1}-{showing_end} of {total} campaigns")


@app.command()
def viewer(
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    operator_db: Optional[Path] = typer.Option(None, "--operator-db", help="Path to operator.db for reasoning"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
    remote: bool = typer.Option(False, "--remote", help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)"),
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

    if remote:
        db_url = os.environ.get("EVAL_DATABASE_URL")
        if not db_url:
            console.print("[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]")
            raise typer.Exit(1)
        app_instance = create_app(db_url, operator_db, remote=True)
        console.print(f"Starting viewer at http://{host}:{port} (remote database)")
    else:
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


# --- Worker commands ---

@worker_app.command("start")
def worker_start(
    cloud: str = typer.Option(
        "gcp",
        "--cloud",
        help="Cloud provider (gcp)",
    ),
    worker_id: Optional[str] = typer.Option(
        None,
        "--id",
        help="Worker ID (auto-generated if not provided)",
    ),
    poll_interval: float = typer.Option(
        5.0,
        "--poll-interval",
        help="Seconds between queue polls",
    ),
    operator_image: Optional[str] = typer.Option(
        None,
        "--operator-image",
        help="Docker image for operator (enables operator on VMs)",
    ),
) -> None:
    """Start a distributed worker process.

    Workers poll the PostgreSQL queue for pending work items, execute
    trials on cloud VMs, and report results back to the database.

    Use --operator-image to run the full operator (monitor + agent) on
    each VM, enabling time-to-detect, time-to-resolve, and command
    history metrics.

    Requires EVAL_DATABASE_URL environment variable.

    Examples:
        eval worker start --cloud=gcp
        eval worker start --cloud=gcp --id=worker-1
        eval worker start --cloud=gcp --operator-image=us-central1-docker.pkg.dev/PROJECT/eval/operator:latest
    """
    import os
    from eval.runner.worker import run_worker

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL environment variable required[/red]"
        )
        raise typer.Exit(1)

    console.log(f"[bold cyan]Starting worker...[/bold cyan]")
    console.log(f"Cloud: {cloud}")
    console.log(f"Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    if operator_image:
        console.log(f"Operator: {operator_image}")

    asyncio.run(
        run_worker(
            db_url=db_url,
            worker_id=worker_id,
            mode=f"cloud-{cloud}",
            operator_image=operator_image or "",
        )
    )


@worker_app.command("status")
def worker_status(
    campaign_id: Optional[int] = typer.Option(
        None,
        "--campaign",
        "-c",
        help="Campaign ID to check (default: show all active)",
    ),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Check campaign and work queue status.

    Without --campaign: shows all campaigns with work items and their progress.
    With --campaign N: shows detailed per-item status for that campaign.

    Examples:
        eval worker status --remote
        eval worker status --remote --campaign 59
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from datetime import datetime, timezone
        from eval.runner.db_postgres import PostgresDB
        from rich.table import Table

        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        if campaign_id:
            # Detailed view for a specific campaign
            campaign = await db.get_campaign(campaign_id)
            if not campaign:
                console.print(f"[red]Campaign {campaign_id} not found[/red]")
                return

            console.print(f"\n[bold]Campaign {campaign_id}: {campaign.name}[/bold]")

            # Status summary
            counts = await queue.get_campaign_status(campaign_id)
            total = sum(counts.values())
            completed = counts.get("completed", 0)
            failed = counts.get("failed", 0)
            running = counts.get("running", 0)
            pending = counts.get("pending", 0)

            pct = int(completed / total * 100) if total else 0
            bar_filled = pct // 5
            bar = f"[green]{'█' * bar_filled}[/green][dim]{'░' * (20 - bar_filled)}[/dim]"
            console.print(f"  Progress: {bar} {completed}/{total} ({pct}%)")
            if running:
                console.print(f"  [cyan]Running: {running}[/cyan]")
            if pending:
                console.print(f"  [yellow]Pending: {pending}[/yellow]")
            if failed:
                console.print(f"  [red]Failed: {failed}[/red]")

            # Per-item detail table
            items = await queue.get_campaign_detail(campaign_id)
            if items:
                console.print()
                table = Table(show_header=True, header_style="bold")
                table.add_column("#", style="dim", width=4)
                table.add_column("Chaos Type", min_width=16)
                table.add_column("Status", min_width=10)
                table.add_column("Worker", style="dim", min_width=12)
                table.add_column("Duration", min_width=10)
                table.add_column("Trial", style="dim", min_width=6)
                table.add_column("Error", style="red", max_width=40)

                for item in items:
                    status = item["status"]
                    color = {"pending": "yellow", "running": "cyan",
                             "completed": "green", "failed": "red"}.get(status, "white")

                    # Calculate duration
                    duration = ""
                    if item["claimed_at"]:
                        end = item["completed_at"] or datetime.now(timezone.utc)
                        delta = end - item["claimed_at"]
                        mins = int(delta.total_seconds() // 60)
                        secs = int(delta.total_seconds() % 60)
                        duration = f"{mins}m{secs:02d}s"

                    chaos_label = item["chaos_type"]
                    if item["baseline"]:
                        chaos_label += " [dim](baseline)[/dim]"

                    worker = (item["worker_id"] or "")[:16]
                    trial = str(item["trial_id"]) if item["trial_id"] else ""
                    error = (item["error"] or "")[:40]

                    table.add_row(
                        str(item["id"]),
                        chaos_label,
                        f"[{color}]{status}[/{color}]",
                        worker,
                        duration,
                        trial,
                        error,
                    )

                console.print(table)

            # Show completed trials with outcomes
            trials = await db.get_trials(campaign_id)
            if trials:
                console.print(f"\n[bold]Completed Trials:[/bold]")
                from eval.analysis.scoring import score_trial
                subject_name = campaign.subject_name
                for t in trials:
                    score = score_trial(t, subject_name)
                    outcome_color = "green" if score.resolved else "red"
                    detect = f"{score.time_to_detect_sec:.0f}s" if score.time_to_detect_sec else "—"
                    resolve = f"{score.time_to_resolve_sec:.0f}s" if score.time_to_resolve_sec else "—"
                    console.print(
                        f"  Trial {t.id}: [{outcome_color}]{score.outcome.value}[/{outcome_color}]"
                        f"  detect={detect}  resolve={resolve}"
                        f"  commands={score.command_count}"
                    )
        else:
            # Overview of all campaigns
            campaigns = await queue.get_active_campaigns()
            if not campaigns:
                console.print("[dim]No campaigns in work queue[/dim]")
                return

            console.print(f"\n[bold]Campaign Status[/bold]\n")
            table = Table(show_header=True, header_style="bold")
            table.add_column("ID", style="dim", width=4)
            table.add_column("Name", min_width=20)
            table.add_column("Progress", min_width=24)
            table.add_column("Pending", style="yellow", justify="right", width=7)
            table.add_column("Running", style="cyan", justify="right", width=7)
            table.add_column("Done", style="green", justify="right", width=7)
            table.add_column("Failed", style="red", justify="right", width=7)

            for c in campaigns:
                total = c["total"]
                completed = c["completed"]
                pct = int(completed / total * 100) if total else 0
                bar_filled = pct // 5
                bar = f"{'█' * bar_filled}{'░' * (20 - bar_filled)} {pct}%"

                table.add_row(
                    str(c["campaign_id"]),
                    c["name"],
                    bar,
                    str(c["pending"]),
                    str(c["running"]),
                    str(c["completed"]),
                    str(c["failed"]),
                )

            console.print(table)

        await db.close()

    asyncio.run(run())


@worker_app.command("workers")
def worker_list(
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
    hours: Optional[float] = typer.Option(
        24.0,
        "--hours",
        help="Only show workers active within this many hours (0 = all)",
    ),
) -> None:
    """Show status of all workers.

    Displays each worker's current task, completed/failed counts, and last activity.
    By default only shows workers active in the last 24 hours.

    Examples:
        eval worker workers --remote
        eval worker workers --remote --hours 0    # show all
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from datetime import datetime, timezone
        from eval.runner.db_postgres import PostgresDB
        from rich.table import Table

        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        max_age = hours if hours else None
        workers = await queue.get_worker_status(max_age_hours=max_age)
        if not workers:
            console.print("[dim]No workers found in work queue[/dim]")
            await db.close()
            return

        console.print(f"\n[bold]Worker Status[/bold]\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Worker ID", min_width=18)
        table.add_column("State", min_width=10)
        table.add_column("Current Task", min_width=22)
        table.add_column("Duration", min_width=10)
        table.add_column("Done", style="green", justify="right", width=5)
        table.add_column("Failed", style="red", justify="right", width=6)
        table.add_column("Last Active", style="dim", min_width=16)

        now = datetime.now(timezone.utc)
        for w in workers:
            worker_id = w["worker_id"]
            running = w["running_count"]

            if running > 0:
                state = "[cyan]working[/cyan]"
                task = f"{w['current_chaos_type']} (c{w['current_campaign_id']})"
                if w["current_claimed_at"]:
                    delta = now - w["current_claimed_at"]
                    mins = int(delta.total_seconds() // 60)
                    secs = int(delta.total_seconds() % 60)
                    duration = f"{mins}m{secs:02d}s"
                else:
                    duration = ""
            else:
                state = "[dim]idle[/dim]"
                task = ""
                duration = ""

            last_active = ""
            if w["last_active"]:
                delta = now - w["last_active"]
                if delta.total_seconds() < 60:
                    last_active = "just now"
                elif delta.total_seconds() < 3600:
                    last_active = f"{int(delta.total_seconds() // 60)}m ago"
                else:
                    last_active = f"{delta.total_seconds() / 3600:.1f}h ago"

            table.add_row(
                worker_id,
                state,
                task,
                duration,
                str(w["completed_count"]),
                str(w["failed_count"]),
                last_active,
            )

        console.print(table)
        await db.close()

    asyncio.run(run())


@worker_app.command("release-stale")
def worker_release_stale(
    timeout: int = typer.Option(
        3600,
        "--timeout",
        "-t",
        help="Seconds before considering a claim stale",
    ),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Release stale work items back to pending.

    Used to recover from worker crashes. Items running longer than
    timeout are reset to pending for other workers to claim.
    The work queue only exists in cloud PostgreSQL, so --remote is required.

    Examples:
        eval worker release-stale --remote
        eval worker release-stale --remote --timeout 1800
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        released = await queue.release_stale(timeout_seconds=timeout)
        console.print(f"[green]Released {released} stale work item(s)[/green]")

        await db.close()

    asyncio.run(run())


@worker_app.command("retry-failed")
def worker_retry_failed(
    campaign: Optional[int] = typer.Option(
        None,
        "--campaign",
        "-c",
        help="Campaign ID to retry (default: all campaigns)",
    ),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Reset failed work items back to pending for retry.

    Workers will automatically pick up the retried items.

    Examples:
        eval worker retry-failed --remote --campaign 59
        eval worker retry-failed --remote
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        retried = await queue.retry_failed(campaign_id=campaign)
        if retried:
            console.print(f"[green]Reset {retried} failed item(s) to pending[/green]")
        else:
            console.print("[dim]No failed items to retry[/dim]")

        await db.close()

    asyncio.run(run())


@worker_app.command("cancel")
def worker_cancel(
    campaign: Optional[int] = typer.Option(
        None,
        "--campaign",
        "-c",
        help="Campaign ID to cancel (default: all campaigns)",
    ),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Cancel pending work items in the queue.

    Marks pending items as failed with 'Cancelled by user'. Running items
    are not affected — use release-stale to reclaim those.

    Examples:
        eval worker cancel --remote --campaign 59
        eval worker cancel --remote
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        cancelled = await queue.cancel_pending(campaign_id=campaign)
        if cancelled:
            console.print(f"[green]Cancelled {cancelled} pending item(s)[/green]")
        else:
            console.print("[dim]No pending items to cancel[/dim]")

        await db.close()

    asyncio.run(run())


@worker_app.command("kill")
def worker_kill(
    campaign: int = typer.Argument(..., help="Campaign ID to kill"),
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Query cloud PostgreSQL (uses EVAL_DATABASE_URL)",
    ),
) -> None:
    """Kill a campaign: cancel all pending and running work items.

    Marks both pending and running items as failed. Running workers will
    see their item was killed and move on to the next one.

    Examples:
        eval worker kill 62 --remote
    """
    if not remote:
        console.print("[red]Error: work queue requires --remote (cloud PostgreSQL)[/red]")
        raise typer.Exit(1)

    from eval.runner.queue import WorkQueue

    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        console.print(
            "[red]Error: EVAL_DATABASE_URL not found (check .env)[/red]"
        )
        raise typer.Exit(1)

    async def run():
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(db_url)
        await db.ensure_schema()
        queue = WorkQueue(db)

        result = await queue.kill_campaign(campaign)
        total = result["pending_cancelled"] + result["running_cancelled"]
        if total:
            console.print(
                f"[green]Killed campaign {campaign}: "
                f"{result['pending_cancelled']} pending + "
                f"{result['running_cancelled']} running items cancelled[/green]"
            )
        else:
            console.print(f"[dim]No active items for campaign {campaign}[/dim]")

        await db.close()

    asyncio.run(run())


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
