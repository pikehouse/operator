"""Campaign and trial runner harness."""

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from eval.types import Campaign, EvalSubject, Trial, VariantConfig
from eval.runner.db import EvalDB
from eval.runner.campaign import CampaignConfig, expand_campaign_matrix
from eval.variants import get_variant


console = Console()


@dataclass
class TrialStats:
    """Thread-safe trial statistics counter."""

    completed: int = 0
    failed: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def record_complete(self) -> None:
        """Record a completed trial (thread-safe)."""
        async with self._lock:
            self.completed += 1

    async def record_failure(self) -> None:
        """Record a failed trial (thread-safe)."""
        async with self._lock:
            self.failed += 1


def now() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


async def get_max_ticket_id(operator_db_path: Path) -> int:
    """Get the maximum ticket ID in operator.db, or 0 if no tickets exist.

    Used to filter out tickets created during cluster startup.
    """
    if not operator_db_path.exists():
        return 0

    def query():
        conn = sqlite3.connect(operator_db_path)
        try:
            cursor = conn.execute("SELECT MAX(id) FROM tickets")
            result = cursor.fetchone()[0]
            return result if result else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    return await asyncio.to_thread(query)


async def force_resolve_all_tickets(operator_db_path: Path) -> int:
    """Force-resolve all open tickets before injecting chaos.

    This ensures that chaos-induced violations create NEW tickets instead of
    updating existing open tickets from cluster startup.

    For eval purposes, we don't want transient startup tickets to interfere
    with chaos detection.

    Args:
        operator_db_path: Path to operator.db

    Returns:
        Number of tickets resolved
    """
    if not operator_db_path.exists():
        return 0

    def resolve_all():
        conn = sqlite3.connect(operator_db_path)
        try:
            cursor = conn.execute(
                """
                UPDATE tickets
                SET status = 'resolved', resolved_at = datetime('now'), held = 0
                WHERE status != 'resolved'
                """
            )
            conn.commit()
            return cursor.rowcount
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    count = await asyncio.to_thread(resolve_all)
    if count > 0:
        console.print(f"[dim]Force-resolved {count} startup ticket(s)[/dim]")
    return count


async def extract_commands_from_operator_db(
    operator_db_path: Path,
) -> list[dict[str, Any]]:
    """Extract agent commands from operator.db for the most recent session.

    This implements RUN-04: Commands extracted from agent session for post-hoc analysis.

    Args:
        operator_db_path: Path to operator.db

    Returns:
        List of command dicts with tool_name, tool_params, exit_code
    """
    if not operator_db_path.exists():
        return []

    # Use sync sqlite3 in thread pool (operator.db is sync)
    def query_commands():
        conn = sqlite3.connect(operator_db_path)
        conn.row_factory = sqlite3.Row
        # Get commands from the most recent session (handles fresh databases in managed mode)
        cursor = conn.execute(
            """
            SELECT tool_name, tool_params, exit_code, timestamp
            FROM agent_log_entries
            WHERE entry_type = 'tool_call'
              AND session_id = (
                  SELECT session_id FROM agent_sessions ORDER BY started_at DESC LIMIT 1
              )
            ORDER BY timestamp
            """
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


async def update_ticket_variant(
    operator_db_path: Path,
    variant_config: VariantConfig,
    timeout_sec: float = 30.0,
) -> bool:
    """Update most recent ticket with variant config.

    Waits for a ticket to exist before updating. Returns True if update succeeded.
    """
    start = asyncio.get_running_loop().time()

    while (asyncio.get_running_loop().time() - start) < timeout_sec:
        def update():
            if not operator_db_path.exists():
                return False
            try:
                conn = sqlite3.connect(operator_db_path)
                # Check if ticket exists
                cursor = conn.execute("SELECT MAX(id) FROM tickets")
                row = cursor.fetchone()
                if row[0] is None:
                    conn.close()
                    return False  # No ticket yet

                conn.execute(
                    """
                    UPDATE tickets
                    SET variant_model = ?, variant_system_prompt = ?, variant_tools_config = ?
                    WHERE id = (SELECT MAX(id) FROM tickets)
                    """,
                    (
                        variant_config.model,
                        variant_config.system_prompt,
                        json.dumps(variant_config.tools_config),
                    ),
                )
                conn.commit()
                conn.close()
                return True
            except sqlite3.OperationalError:
                # Table doesn't exist yet
                return False

        if await asyncio.to_thread(update):
            return True
        await asyncio.sleep(1.0)

    console.print("[yellow]Warning: Could not update ticket variant (no ticket created)[/yellow]")
    return False


async def wait_for_ticket_resolution(
    operator_db_path: Path,
    timeout_sec: float = 300.0,
    min_ticket_id: int = 0,
) -> tuple[str | None, str | None]:
    """Wait for ticket to be created and resolved in operator.db.

    Args:
        operator_db_path: Path to operator.db
        timeout_sec: Maximum time to wait
        min_ticket_id: Only consider tickets with ID > this value (filters pre-chaos tickets)

    Returns:
        Tuple of (ticket_created_at, resolved_at) or (None, None) if timeout
    """
    start = asyncio.get_running_loop().time()
    ticket_created_at: str | None = None

    console.print(f"[dim]Waiting up to {timeout_sec}s for ticket resolution...[/dim]")
    if min_ticket_id > 0:
        console.print(f"[dim]Looking for tickets with ID > {min_ticket_id}[/dim]")

    while (asyncio.get_running_loop().time() - start) < timeout_sec:
        # Wait for database to exist (monitor creates it)
        if not operator_db_path.exists():
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed > 60:
                console.print("[yellow]Warning: operator.db not created after 60s[/yellow]")
            await asyncio.sleep(2.0)
            continue

        def query_ticket():
            conn = sqlite3.connect(operator_db_path)
            conn.row_factory = sqlite3.Row
            try:
                # Get most recent ticket (optionally filtered by ID)
                cursor = conn.execute(
                    """
                    SELECT first_seen_at, resolved_at, status
                    FROM tickets
                    WHERE id > ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (min_ticket_id,),
                )
                row = cursor.fetchone()
                if row:
                    return row["first_seen_at"], row["resolved_at"], row["status"]
                return None, None, None
            except sqlite3.OperationalError:
                # Table doesn't exist yet (monitor still initializing)
                return None, None, None
            finally:
                conn.close()

        created, resolved, status = await asyncio.to_thread(query_ticket)

        if created:
            # Ticket exists - save creation time for time-to-detect metric
            if ticket_created_at is None:
                ticket_created_at = created
                console.print(f"[cyan]Ticket detected (status: {status})[/cyan]")

            if status == "resolved" and resolved:
                elapsed = asyncio.get_running_loop().time() - start
                console.print(f"[green]Ticket resolved after {elapsed:.1f}s[/green]")
                return created, resolved
            # Ticket not yet resolved, keep waiting

        await asyncio.sleep(2.0)

    # Timeout - return ticket creation time if detected (for time-to-detect metric)
    elapsed = asyncio.get_running_loop().time() - start
    console.print(f"[yellow]Timeout after {elapsed:.1f}s (ticket_found={ticket_created_at is not None})[/yellow]")
    return ticket_created_at, None


async def run_trial(
    subject: EvalSubject,
    chaos_type: str,
    campaign_id: int,
    baseline: bool = False,
    operator_db_path: Path | None = None,
    chaos_params: dict[str, Any] | None = None,
    variant_config: VariantConfig | None = None,
    skip_reset: bool = False,
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
        variant_config: Optional variant config for A/B testing
        skip_reset: If True, skip reset (already done by OperatorProcesses)

    Returns:
        Completed Trial record
    """
    started_at = now()

    # Reset subject to clean state (unless already done)
    if skip_reset:
        console.print("[dim]Skipping reset (already done)[/dim]")
    else:
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

    # Force-resolve any startup tickets before injecting chaos
    # This prevents the chaos violation from updating a pre-existing ticket
    if operator_db_path:
        await force_resolve_all_tickets(operator_db_path)

    # Get max ticket ID before chaos (to filter out startup tickets)
    pre_chaos_max_ticket_id = 0
    if operator_db_path:
        pre_chaos_max_ticket_id = await get_max_ticket_id(operator_db_path)
        if pre_chaos_max_ticket_id > 0:
            console.print(f"[dim]Pre-chaos max ticket ID: {pre_chaos_max_ticket_id}[/dim]")

    # Inject chaos (with params if provided)
    console.print(f"[bold yellow]Injecting chaos: {chaos_type}[/bold yellow]")
    chaos_injected_at = now()
    console.print(f"[dim]chaos_injected_at: {chaos_injected_at}[/dim]")
    chaos_metadata = await subject.inject_chaos(chaos_type, **(chaos_params or {}))
    console.print(f"[dim]Chaos metadata: {chaos_metadata}[/dim]")

    # Everything after injection is wrapped in try/finally to ensure cleanup
    # This is critical for disk_pressure which creates files on the host
    try:
        # Write variant config to ticket (if variant and operator_db provided)
        # Do this early so the agent picks it up when it polls
        if variant_config and operator_db_path and not baseline:
            updated = await update_ticket_variant(operator_db_path, variant_config)
            if updated:
                console.print(f"[dim]Variant config written to ticket: {variant_config.model}[/dim]")

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
                    operator_db_path,
                    timeout_sec=300.0,
                    min_ticket_id=pre_chaos_max_ticket_id,  # Filter to tickets after chaos
                )

                # Extract commands (RUN-04)
                if ticket_created_at:
                    commands = await extract_commands_from_operator_db(operator_db_path)
                    console.print(f"[dim]Extracted {len(commands)} commands[/dim]")

        # Capture final state (RUN-03)
        console.print("[bold blue]Capturing final state...[/bold blue]")
        final_state = await subject.capture_state()

        ended_at = now()

    finally:
        # ALWAYS cleanup chaos, even on failure
        # This is critical for disk_pressure which creates files on host storage
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


class SubjectPool:
    """Pool of EvalSubject instances for parallel trial execution.

    Each instance has its own isolated cluster (different Docker Compose project,
    different host ports) to enable true parallel execution without conflicts.
    """

    def __init__(self, pool_size: int, subject_type: str = "tikv", mode: str = "local"):
        """Initialize pool with N subject instances.

        Args:
            pool_size: Number of parallel instances (each gets unique ports)
            subject_type: Subject type to create (e.g., "tikv")
            mode: Execution mode ("local" or "cloud-gcp")
        """
        from eval.subjects.factory import SubjectRegistry

        self.pool_size = pool_size
        self.subject_type = subject_type
        self.mode = mode

        # Create instances with unique instance_ids using factory
        self._instances: list[EvalSubject] = []
        for i in range(pool_size):
            self._instances.append(
                SubjectRegistry.create(subject_type, instance_id=i, mode=mode)
            )

        # Track which instances are available
        self._available: asyncio.Queue[int] = asyncio.Queue()
        for i in range(pool_size):
            self._available.put_nowait(i)

        console.print(f"[dim]Created pool of {pool_size} {subject_type} instances[/dim]")
        for i, inst in enumerate(self._instances):
            if hasattr(inst, 'pd_port'):
                console.print(f"[dim]  Instance {i}: project={inst.project_name}, pd_port={inst.pd_port}[/dim]")

    async def acquire(self) -> tuple[int, EvalSubject]:
        """Acquire an available instance from the pool.

        Returns:
            Tuple of (instance_id, subject_instance)
        """
        instance_id = await self._available.get()
        return instance_id, self._instances[instance_id]

    def release(self, instance_id: int) -> None:
        """Release instance back to the pool."""
        self._available.put_nowait(instance_id)

    async def shutdown(self) -> None:
        """Shutdown all instances in the pool."""
        console.print("[dim]Shutting down subject pool...[/dim]")
        for i, instance in enumerate(self._instances):
            try:
                # Down the compose project
                await asyncio.to_thread(
                    instance.docker.compose.down,
                    volumes=True,
                    remove_orphans=True,
                )
                console.print(f"[dim]  Instance {i} shut down[/dim]")
            except Exception as e:
                console.print(f"[yellow]  Instance {i} shutdown warning: {e}[/yellow]")


async def run_campaign_from_config(
    config: CampaignConfig,
    db: EvalDB,
    operator_db_path: Path | None = None,
    model_override: str | None = None,
) -> int:
    """Run campaign from YAML config with parallel execution.

    This is a NEW function for YAML-based campaigns.
    The existing run_campaign() function remains unchanged for backward compatibility.

    Uses a pool of isolated subject instances for TRUE parallel execution.
    Each parallel slot has its own Docker Compose project with unique ports.

    Args:
        config: Loaded CampaignConfig
        db: EvalDB for persistence
        operator_db_path: Path to operator.db for command extraction
        model_override: Override model from CLI (e.g., 'claude-sonnet-4-20250514')

    Returns:
        campaign_id for later analysis
    """
    # Expand matrix to trial specs
    trial_specs = expand_campaign_matrix(config)
    total_trials = len(trial_specs)

    # Load variant configuration
    try:
        variant_config = get_variant(config.variant)
        # Apply model override from CLI if provided
        if model_override:
            variant_config = VariantConfig(
                name=variant_config.name,
                model=model_override,
                system_prompt=variant_config.system_prompt,
                tools_config=variant_config.tools_config,
            )
            console.print(f"[dim]Using variant: {variant_config.name} (model override: {variant_config.model})[/dim]")
        else:
            console.print(f"[dim]Using variant: {variant_config.name} (model: {variant_config.model})[/dim]")
    except ValueError as e:
        console.print(f"[red]Error loading variant: {e}[/red]")
        raise

    # Create campaign record
    # Store first subject/chaos only for baseline matching compatibility
    # (campaigns typically test one subject, multi-subject stored as first only)
    campaign = Campaign(
        subject_name=config.subjects[0] if config.subjects else "unknown",
        chaos_type=config.chaos_types[0].type if config.chaos_types else "unknown",
        trial_count=total_trials,
        baseline=config.include_baseline,
        variant_name=config.variant,
        created_at=now(),
    )
    campaign_id = await db.insert_campaign(campaign)
    console.print(f"[bold green]Campaign {campaign_id} started ({total_trials} trials)[/bold green]")

    # Determine subject type (all subjects in config should be same type for now)
    subject_type = config.subjects[0] if config.subjects else "tikv"

    # Create pool of isolated subject instances
    pool = SubjectPool(pool_size=config.parallel, subject_type=subject_type)

    # Thread-safe trial statistics
    stats = TrialStats()

    async def run_single_trial(spec: dict, trial_num: int) -> Trial | None:
        # Acquire instance from pool (blocks until one is available)
        instance_id, subject = await pool.acquire()
        try:
            console.print(
                f"\n[bold]Trial {trial_num}/{total_trials}: "
                f"{spec['subject']}/{spec['chaos_type']} "
                f"(instance {instance_id})[/bold]"
            )

            trial = await run_trial(
                subject=subject,
                chaos_type=spec["chaos_type"] if not spec["baseline"] else "none",
                campaign_id=campaign_id,
                baseline=spec["baseline"],
                operator_db_path=operator_db_path,
                chaos_params=spec["chaos_params"],
                variant_config=variant_config,
            )

            trial_id = await db.insert_trial(trial)
            console.print(f"[green]Trial {trial_id} completed (instance {instance_id})[/green]")
            await stats.record_complete()

            # Cooldown between trials
            if config.cooldown_seconds > 0:
                await asyncio.sleep(config.cooldown_seconds)

            return trial

        except Exception as e:
            console.print(f"[red]Trial failed (instance {instance_id}): {e}[/red]")
            await stats.record_failure()
            return None

        finally:
            # Always release instance back to pool
            pool.release(instance_id)

    # Run all trials - pool manages parallelism
    tasks = [
        run_single_trial(spec, i + 1)
        for i, spec in enumerate(trial_specs)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Check for unexpected exceptions (not caught in run_single_trial)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            console.print(f"[red]Unexpected error in trial {i + 1}: {result}[/red]")
            await stats.record_failure()

    # Shutdown pool (optional - leaves clusters running for inspection)
    # await pool.shutdown()

    console.print(f"\n[bold green]Campaign {campaign_id} complete[/bold green]")
    console.print(f"Completed: {stats.completed}, Failed: {stats.failed}")

    return campaign_id
