"""Campaign and trial runner harness."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from eval.types import Campaign, EvalSubject, Trial, VariantConfig
from eval.runner.db import EvalDB
from eval.runner.campaign import CampaignConfig, expand_campaign_matrix
from eval.variants import get_variant


console = Console()


def now() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


async def extract_commands_from_operator_db(
    operator_db_path: Path,
    started_after: str,
) -> list[dict[str, Any]]:
    """Extract agent commands from operator.db after a timestamp.

    This implements RUN-04: Commands extracted from agent session for post-hoc analysis.

    Args:
        operator_db_path: Path to operator.db
        started_after: ISO8601 timestamp to filter entries

    Returns:
        List of command dicts with tool_name, tool_params, exit_code
    """
    if not operator_db_path.exists():
        return []

    # Use sync sqlite3 in thread pool (operator.db is sync)
    def query_commands():
        conn = sqlite3.connect(operator_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT tool_name, tool_params, exit_code, timestamp
            FROM agent_log_entries
            WHERE entry_type = 'tool_call'
              AND timestamp > ?
            ORDER BY timestamp
            """,
            (started_after,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "tool_name": row["tool_name"],
                "tool_params": row["tool_params"],
                "exit_code": row["exit_code"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    return await asyncio.to_thread(query_commands)


async def wait_for_ticket_resolution(
    operator_db_path: Path,
    timeout_sec: float = 300.0,
) -> tuple[str | None, str | None]:
    """Wait for ticket to be created and resolved in operator.db.

    Args:
        operator_db_path: Path to operator.db
        timeout_sec: Maximum time to wait

    Returns:
        Tuple of (ticket_created_at, resolved_at) or (None, None) if timeout
    """
    if not operator_db_path.exists():
        return None, None

    start = asyncio.get_running_loop().time()

    while (asyncio.get_running_loop().time() - start) < timeout_sec:
        def query_ticket():
            conn = sqlite3.connect(operator_db_path)
            conn.row_factory = sqlite3.Row
            # Get most recent open or resolved ticket
            cursor = conn.execute(
                """
                SELECT first_seen_at, resolved_at, status
                FROM tickets
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return row["first_seen_at"], row["resolved_at"], row["status"]
            return None, None, None

        created, resolved, status = await asyncio.to_thread(query_ticket)

        if created:
            # Ticket exists
            if status == "resolved" and resolved:
                return created, resolved
            # Ticket not yet resolved, keep waiting

        await asyncio.sleep(2.0)

    # Timeout - return what we have
    return None, None


async def run_trial(
    subject: EvalSubject,
    chaos_type: str,
    campaign_id: int,
    baseline: bool = False,
    operator_db_path: Path | None = None,
    chaos_params: dict[str, Any] | None = None,
) -> Trial:
    """Execute single trial with precise timing capture.

    Implements RUN-01 sequence: reset -> inject -> wait -> record

    Args:
        subject: EvalSubject to test
        chaos_type: Chaos type to inject
        campaign_id: Parent campaign ID
        baseline: If True, skip agent wait (RUN-05)
        operator_db_path: Path to operator.db for command extraction
        chaos_params: Optional parameters for chaos injection (e.g., min_ms, max_ms)

    Returns:
        Completed Trial record
    """
    started_at = now()

    # Reset subject to clean state
    console.print("[bold blue]Resetting subject...[/bold blue]")
    await subject.reset()

    # Wait for healthy state
    console.print("[bold blue]Waiting for healthy state...[/bold blue]")
    healthy = await subject.wait_healthy(timeout_sec=120.0)
    if not healthy:
        console.print("[bold red]Subject failed to become healthy[/bold red]")

    # Capture initial state (RUN-03)
    console.print("[bold blue]Capturing initial state...[/bold blue]")
    initial_state = await subject.capture_state()

    # Inject chaos (with params if provided)
    console.print(f"[bold yellow]Injecting chaos: {chaos_type}[/bold yellow]")
    chaos_injected_at = now()
    chaos_metadata = await subject.inject_chaos(chaos_type, **(chaos_params or {}))
    console.print(f"[dim]Chaos metadata: {chaos_metadata}[/dim]")

    # Wait for resolution (unless baseline)
    ticket_created_at = None
    resolved_at = None
    commands: list[dict[str, Any]] = []

    if baseline:
        # RUN-05: Baseline trials run without agent
        console.print("[bold cyan]Baseline mode: waiting for self-healing...[/bold cyan]")
        # Just wait for subject to recover on its own
        await subject.wait_healthy(timeout_sec=300.0)
    else:
        # Normal trial: wait for agent to resolve
        console.print("[bold cyan]Waiting for agent resolution...[/bold cyan]")
        if operator_db_path:
            ticket_created_at, resolved_at = await wait_for_ticket_resolution(
                operator_db_path, timeout_sec=300.0
            )

            # Extract commands (RUN-04)
            if ticket_created_at:
                commands = await extract_commands_from_operator_db(
                    operator_db_path, started_at
                )
                console.print(f"[dim]Extracted {len(commands)} commands[/dim]")

    # Capture final state (RUN-03)
    console.print("[bold blue]Capturing final state...[/bold blue]")
    final_state = await subject.capture_state()

    ended_at = now()

    # Cleanup chaos AFTER final_state capture, BEFORE building Trial
    # This ensures we capture the "during chaos" state before reverting
    try:
        await subject.cleanup_chaos(chaos_metadata)
    except Exception as e:
        # Handle gracefully - container may have been killed/restarted
        # This is expected for node_kill chaos type
        console.print(f"[dim]Cleanup note: {e}[/dim]")

    return Trial(
        campaign_id=campaign_id,
        started_at=started_at,
        chaos_injected_at=chaos_injected_at,
        ticket_created_at=ticket_created_at,
        resolved_at=resolved_at,
        ended_at=ended_at,
        initial_state=json.dumps(initial_state),
        final_state=json.dumps(final_state),
        chaos_metadata=json.dumps(chaos_metadata),
        commands_json=json.dumps(commands),
    )


async def run_campaign(
    subject: EvalSubject,
    subject_name: str,
    chaos_type: str,
    trial_count: int,
    db: EvalDB,
    baseline: bool = False,
    operator_db_path: Path | None = None,
) -> int:
    """Run campaign of N trials sequentially.

    Args:
        subject: EvalSubject to test
        subject_name: Name for reporting (e.g., "TiKVEvalSubject")
        chaos_type: Chaos type to inject
        trial_count: Number of trials
        db: EvalDB for persistence
        baseline: If True, skip agent wait
        operator_db_path: Path to operator.db for command extraction

    Returns:
        campaign_id for later analysis
    """
    # Create campaign record
    campaign = Campaign(
        subject_name=subject_name,
        chaos_type=chaos_type,
        trial_count=trial_count,
        baseline=baseline,
        created_at=now(),
    )
    campaign_id = await db.insert_campaign(campaign)
    console.print(f"[bold green]Campaign {campaign_id} started[/bold green]")

    # Run trials sequentially (avoid SQLite write contention)
    for trial_num in range(trial_count):
        console.print(f"\n[bold]Trial {trial_num + 1}/{trial_count}[/bold]")

        trial = await run_trial(
            subject=subject,
            chaos_type=chaos_type,
            campaign_id=campaign_id,
            baseline=baseline,
            operator_db_path=operator_db_path,
        )

        trial_id = await db.insert_trial(trial)
        console.print(f"[green]Trial {trial_id} completed at {trial.ended_at}[/green]")

    console.print(f"\n[bold green]Campaign {campaign_id} complete[/bold green]")
    return campaign_id


async def run_campaign_from_config(
    config: CampaignConfig,
    db: EvalDB,
    operator_db_path: Path | None = None,
) -> int:
    """Run campaign from YAML config with parallel execution.

    This is a NEW function for YAML-based campaigns.
    The existing run_campaign() function remains unchanged for backward compatibility.

    Uses asyncio.Semaphore to limit concurrent trials.
    Continues campaign even if individual trials fail.

    Args:
        config: Loaded CampaignConfig
        db: EvalDB for persistence
        operator_db_path: Path to operator.db for command extraction

    Returns:
        campaign_id for later analysis
    """
    from eval.subjects.tikv import TiKVEvalSubject

    # Expand matrix to trial specs
    trial_specs = expand_campaign_matrix(config)
    total_trials = len(trial_specs)

    # Load variant configuration
    try:
        variant_config = get_variant(config.variant)
        console.print(f"[dim]Using variant: {variant_config.name} (model: {variant_config.model})[/dim]")
    except ValueError as e:
        console.print(f"[red]Error loading variant: {e}[/red]")
        raise

    # Create campaign record
    campaign = Campaign(
        subject_name=",".join(config.subjects),
        chaos_type=",".join(c.type for c in config.chaos_types),
        trial_count=total_trials,
        baseline=config.include_baseline,
        variant_name=config.variant,
        created_at=now(),
    )
    campaign_id = await db.insert_campaign(campaign)
    console.print(f"[bold green]Campaign {campaign_id} started ({total_trials} trials)[/bold green]")

    # Semaphore for parallelism control
    semaphore = asyncio.Semaphore(config.parallel)
    completed = 0
    failed = 0

    async def run_single_trial(spec: dict, trial_num: int) -> Trial | None:
        nonlocal completed, failed
        async with semaphore:
            try:
                console.print(f"\n[bold]Trial {trial_num}/{total_trials}: {spec['subject']}/{spec['chaos_type']}[/bold]")

                # Get subject instance (fresh for each trial)
                if spec["subject"] == "tikv":
                    subject = TiKVEvalSubject()
                else:
                    raise ValueError(f"Unknown subject: {spec['subject']}")

                trial = await run_trial(
                    subject=subject,
                    chaos_type=spec["chaos_type"] if not spec["baseline"] else "none",
                    campaign_id=campaign_id,
                    baseline=spec["baseline"],
                    operator_db_path=operator_db_path,
                    chaos_params=spec["chaos_params"],
                )

                trial_id = await db.insert_trial(trial)
                console.print(f"[green]Trial {trial_id} completed[/green]")
                completed += 1

                # Cooldown between trials
                if config.cooldown_seconds > 0:
                    await asyncio.sleep(config.cooldown_seconds)

                return trial

            except Exception as e:
                console.print(f"[red]Trial failed: {e}[/red]")
                failed += 1
                return None

    # Run trials (semaphore limits concurrency)
    tasks = [
        run_single_trial(spec, i + 1)
        for i, spec in enumerate(trial_specs)
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    console.print(f"\n[bold green]Campaign {campaign_id} complete[/bold green]")
    console.print(f"Completed: {completed}, Failed: {failed}")

    return campaign_id
