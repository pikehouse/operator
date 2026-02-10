"""Worker process for distributed eval execution.

Workers poll the work queue for pending items, execute trials,
and report results back to the shared database.

When operator is enabled (via campaign config), the worker runs the full
operator stack (monitor + agent) on the GCP VM alongside TiKV, producing
real time-to-detect, time-to-resolve, and command history metrics.
"""

import asyncio
import logging
import os
import signal
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console

from eval.runner.db_postgres import PostgresDB
from eval.runner.queue import WorkQueue, WorkItem
from eval.subjects.factory import SubjectRegistry
from eval.types import Campaign, Trial, VariantConfig
from eval.variants import get_variant

logger = logging.getLogger(__name__)
console = Console()


class Worker:
    """Distributed worker that processes eval work items.

    Polls the work queue for pending items, executes trials using
    cloud or local subjects, and reports results back to the database.
    """

    def __init__(
        self,
        db_url: str,
        worker_id: str | None = None,
        mode: str = "cloud-gcp",
        poll_interval: float = 5.0,
        operator_image: str = "",
    ):
        """Initialize worker.

        Args:
            db_url: PostgreSQL connection URL
            worker_id: Unique worker identifier (auto-generated if not provided)
            mode: Subject execution mode (e.g., "cloud-gcp")
            poll_interval: Seconds between queue polls
            operator_image: Docker image URL for operator (empty = disabled)
        """
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.mode = mode
        self.poll_interval = poll_interval
        self.db = PostgresDB(db_url)
        self.queue = WorkQueue(self.db)
        self._running = False
        self._current_subject = None
        self._operator_image = operator_image

        # VM pooling: reuse a single subject (and its VM) across trials
        self._pooled_subject = None
        self._pooled_subject_type: str | None = None

    async def start(self) -> None:
        """Start the worker loop.

        Polls queue for work, executes trials, and reports results.
        Runs until stop() is called or SIGINT/SIGTERM received.
        """
        self._running = True
        console.log(f"[bold green]Worker {self.worker_id} starting[/bold green]")
        console.log(f"Mode: {self.mode}")

        # Ensure schema exists
        await self.db.ensure_schema()

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            while self._running:
                try:
                    # Try to claim work
                    work_item = await self.queue.claim_next(self.worker_id)

                    if work_item:
                        console.log(
                            f"[cyan]Claimed work item {work_item.id}: "
                            f"{work_item.subject_type}/{work_item.chaos_type}[/cyan]"
                        )
                        await self._execute_work(work_item)
                    else:
                        # No work available, wait before polling again
                        await asyncio.sleep(self.poll_interval)

                except Exception as e:
                    logger.exception(f"Worker error: {e}")
                    await asyncio.sleep(self.poll_interval)
        finally:
            # Ensure the pooled VM is destroyed on exit
            await self._cleanup_pooled_subject()

        console.log(f"[bold yellow]Worker {self.worker_id} stopped[/bold yellow]")
        await self.db.close()

    async def stop(self) -> None:
        """Stop the worker loop gracefully."""
        console.log("[yellow]Shutting down worker...[/yellow]")
        self._running = False

        # Clean up pooled subject (deletes the VM)
        await self._cleanup_pooled_subject()

    async def _execute_work(self, work_item: WorkItem) -> None:
        """Execute a single work item.

        Reuses a pooled subject (and its VM) across trials of the same
        subject type. The VM is only created for the first trial and
        destroyed when the worker shuts down or the subject type changes.

        Args:
            work_item: Work item to execute
        """
        trial_id = None
        error = None

        try:
            subject = await self._get_or_create_subject(work_item)
            self._current_subject = subject

            # Get campaign for variant info
            campaign = await self.db.get_campaign(work_item.campaign_id)
            variant_config = None
            if campaign and campaign.variant_name:
                try:
                    variant_config = get_variant(campaign.variant_name)
                except ValueError:
                    logger.warning(f"Variant not found: {campaign.variant_name}")

            # Determine operator config
            enable_operator = False
            operator_image = ""
            anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

            if self._operator_image:
                enable_operator = True
                operator_image = self._operator_image

            # Run the trial
            trial = await self._run_trial(
                subject=subject,
                chaos_type=work_item.chaos_type,
                campaign_id=work_item.campaign_id,
                baseline=work_item.baseline,
                chaos_params=work_item.chaos_params,
                variant_config=variant_config,
                enable_operator=enable_operator,
                operator_image=operator_image,
                anthropic_api_key=anthropic_api_key,
                subject_name=work_item.subject_type,
            )

            # Store trial result
            trial_id = await self.db.insert_trial(trial)
            console.log(f"[green]Work item {work_item.id} completed -> Trial {trial_id}[/green]")

        except Exception as e:
            error = str(e)
            logger.exception(f"Work item {work_item.id} failed: {e}")
            console.log(f"[red]Work item {work_item.id} failed:[/red] {e!s}")

            # If the error looks like a VM-level failure, destroy the
            # pooled subject so the next trial gets a fresh VM.
            if self._is_vm_failure(e):
                console.log("[yellow]VM failure detected, destroying pooled subject[/yellow]")
                await self._cleanup_pooled_subject()

        finally:
            self._current_subject = None

            # Mark work item complete (or failed)
            await self.queue.complete(
                work_id=work_item.id,
                trial_id=trial_id,
                error=error,
            )

    async def _get_or_create_subject(self, work_item: WorkItem):
        """Return a pooled subject, creating one if needed.

        Reuses the existing VM when the subject type hasn't changed.
        For ChatDB subjects, updates the trial database name so each
        trial gets an isolated Cloud SQL database.

        Args:
            work_item: Current work item (provides subject_type and id).

        Returns:
            EvalSubject instance (pooled or freshly created).
        """
        # If subject type changed, tear down the old one first
        if (
            self._pooled_subject is not None
            and self._pooled_subject_type != work_item.subject_type
        ):
            console.log(
                f"[yellow]Subject type changed "
                f"({self._pooled_subject_type} -> {work_item.subject_type}), "
                f"recreating VM[/yellow]"
            )
            await self._cleanup_pooled_subject()

        # Create a new subject if we don't have one
        if self._pooled_subject is None:
            # Use instance_id=0 — the VM name already has a UUID suffix
            # from the worker_id, so there's no collision risk.
            self._pooled_subject = SubjectRegistry.create(
                work_item.subject_type,
                instance_id=0,
                mode=self.mode,
            )
            self._pooled_subject_type = work_item.subject_type
            console.log(
                f"[blue]Created pooled {work_item.subject_type} subject[/blue]"
            )

        # For ChatDB subjects, point the subject at this trial's database
        if hasattr(self._pooled_subject, "set_trial_id"):
            self._pooled_subject.set_trial_id(work_item.id)

        return self._pooled_subject

    async def _cleanup_pooled_subject(self) -> None:
        """Destroy the pooled subject (deletes the VM) and clear state."""
        if self._pooled_subject is not None:
            try:
                await self._cleanup_subject(self._pooled_subject)
            except Exception as e:
                logger.warning(f"Error cleaning up pooled subject: {e}")
            self._pooled_subject = None
            self._pooled_subject_type = None

    @staticmethod
    def _is_vm_failure(exc: Exception) -> bool:
        """Check if an exception looks like a VM-level failure.

        These errors indicate the VM itself is unreachable, so the pooled
        subject should be destroyed and a fresh VM created for the next trial.
        """
        msg = str(exc).lower()
        vm_failure_signals = [
            "ssh",
            "connection refused",
            "connection reset",
            "timed out",
            "timeout",
            "unreachable",
            "no route to host",
        ]
        return any(signal in msg for signal in vm_failure_signals)

    async def _run_trial(
        self,
        subject,
        chaos_type: str,
        campaign_id: int,
        baseline: bool,
        chaos_params: dict[str, Any],
        variant_config: VariantConfig | None,
        enable_operator: bool = False,
        operator_image: str = "",
        anthropic_api_key: str = "",
        subject_name: str = "tikv",
    ) -> Trial:
        """Run a single trial.

        When enable_operator=True, runs the full operator stack on the VM
        and captures time-to-detect, time-to-resolve, and command history.
        Otherwise, runs in simplified mode without operator metrics.

        Args:
            subject: EvalSubject instance
            chaos_type: Chaos type to inject
            campaign_id: Campaign ID
            baseline: Whether this is a baseline trial
            chaos_params: Parameters for chaos injection
            variant_config: Optional variant configuration
            enable_operator: Whether to run operator on the VM
            operator_image: Docker image URL for operator
            anthropic_api_key: API key for operator agent

        Returns:
            Trial record with populated metrics
        """
        from datetime import datetime, timezone
        import json

        def now() -> str:
            return datetime.now(timezone.utc).isoformat()

        started_at = now()

        # Reset subject
        console.log("[blue]Resetting subject...[/blue]")
        await subject.reset()

        # Wait for healthy
        console.log("[blue]Waiting for healthy state...[/blue]")
        healthy = await subject.wait_healthy(timeout_sec=120.0)
        if not healthy:
            raise RuntimeError("Subject failed to become healthy")

        # Capture initial state
        initial_state = await subject.capture_state()

        # Set up operator if enabled
        remote_op = None
        if enable_operator and not baseline and hasattr(subject, "vm"):
            from eval.runner.remote_operator import RemoteOperatorProcesses

            # Get subject-specific env vars for operator (e.g., DATABASE_URL)
            extra_env = {}
            if hasattr(subject, "get_operator_env"):
                extra_env = subject.get_operator_env()

            # Get optional agent context and workspace mount
            subject_context_extra = ""
            if hasattr(subject, "get_agent_context"):
                subject_context_extra = subject.get_agent_context()

            workspace_volume_mount = ""
            if hasattr(subject, "workspace_volume_mount"):
                workspace_volume_mount = subject.workspace_volume_mount

            extra_volume_mounts = []
            if hasattr(subject, "extra_volume_mounts"):
                extra_volume_mounts = subject.extra_volume_mounts

            remote_op = RemoteOperatorProcesses(
                vm=subject.vm,
                operator_image=operator_image,
                anthropic_api_key=anthropic_api_key,
                subject_name=subject_name,
                extra_env=extra_env,
                subject_context_extra=subject_context_extra,
                workspace_volume_mount=workspace_volume_mount,
                extra_volume_mounts=extra_volume_mounts,
            )

        # Initialize variables used in finally/return before try block
        chaos_metadata: dict[str, Any] = {}
        chaos_injected_at = now()
        ticket_created_at = None
        resolved_at = None
        commands: list[dict[str, Any]] = []
        operator_data: dict[str, Any] = {}
        ended_at = now()

        try:
            # Capture topology before chaos (subject is healthy at this point)
            try:
                from eval.runner.harness import capture_deployment_topology_async
                topology_json = await capture_deployment_topology_async(subject, mode=self.mode)
                if topology_json:
                    pool = await self.db._get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE campaigns SET topology_json = $1::jsonb WHERE id = $2 AND (topology_json IS NULL)",
                            topology_json, campaign_id,
                        )
            except Exception as e:
                logger.debug(f"Topology capture skipped: {e}")

            # Start operator on VM (if enabled)
            if remote_op:
                await remote_op.start()
                # Wait for monitor to initialize and do first check
                await asyncio.sleep(5.0)
                # Clear any startup tickets
                await remote_op.force_resolve_all_tickets()
                # Record baseline ticket ID
                pre_chaos_max_ticket_id = await remote_op.get_max_ticket_id()
                if pre_chaos_max_ticket_id > 0:
                    console.log(
                        f"[dim]Pre-chaos max ticket ID: {pre_chaos_max_ticket_id}[/dim]"
                    )
            # Inject chaos (unless baseline)
            if not baseline and chaos_type != "none":
                console.log(f"[yellow]Injecting chaos: {chaos_type}[/yellow]")
                chaos_injected_at = now()
                chaos_metadata = await subject.inject_chaos(chaos_type, **chaos_params)

                # For debug_code_edit, inject a synthetic ticket via the operator DB
                if chaos_type == "debug_code_edit" and remote_op:
                    agent_context = ""
                    if hasattr(subject, "get_agent_context"):
                        agent_context = subject.get_agent_context()
                    await remote_op.inject_ticket(
                        invariant_name="operator_override",
                        message=(
                            "Add a comment '# AGENT_WAS_HERE' to the top of app/main.py, "
                            "then rebuild and restart the app."
                        ),
                        subject_context=agent_context,
                    )

            if remote_op:
                # Operator mode: write variant config, wait for ticket resolution
                if variant_config:
                    updated = await remote_op.update_ticket_variant(variant_config)
                    if updated:
                        console.log(
                            f"[dim]Variant config written: {variant_config.model}[/dim]"
                        )

                console.log("[cyan]Waiting for agent resolution...[/cyan]")
                ticket_created_at, resolved_at = (
                    await remote_op.wait_for_ticket_resolution(
                        timeout_sec=300.0,
                        min_ticket_id=pre_chaos_max_ticket_id,
                    )
                )

                # Download operator.db and extract commands + operator data
                if ticket_created_at:
                    try:
                        from eval.runner.harness import (
                            extract_commands_from_operator_db,
                            extract_operator_data,
                        )

                        local_db = Path(f"/tmp/operator-{uuid.uuid4().hex[:8]}.db")
                        await remote_op.download_operator_db(local_db)
                        commands = await extract_commands_from_operator_db(local_db)
                        console.log(f"[dim]Extracted {len(commands)} commands[/dim]")
                        operator_data = await extract_operator_data(local_db)
                        console.log(f"[dim]Extracted operator data keys: {list(operator_data.keys())}[/dim]")
                        # Clean up temp file
                        local_db.unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning(f"Failed to extract commands: {e}")
            else:
                # No operator: just wait for subject self-recovery
                console.log("[cyan]Waiting for recovery...[/cyan]")
                recovered = await subject.wait_healthy(timeout_sec=300.0)
                resolved_at = now() if recovered else None

            # Capture final state
            final_state = await subject.capture_state()
            ended_at = now()

        finally:
            # Always cleanup chaos
            if chaos_metadata:
                try:
                    await subject.cleanup_chaos(chaos_metadata)
                except Exception as e:
                    logger.debug(f"Cleanup note: {e}")

            # Stop operator
            if remote_op:
                try:
                    await remote_op.stop()
                except Exception as e:
                    logger.debug(f"Operator stop note: {e}")

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
            operator_data_json=json.dumps(operator_data),
        )

    async def _cleanup_subject(self, subject) -> None:
        """Clean up a subject (e.g., delete cloud VM)."""
        if hasattr(subject, "cleanup"):
            await subject.cleanup()


async def run_worker(
    db_url: str,
    worker_id: str | None = None,
    mode: str = "cloud-gcp",
    operator_image: str = "",
) -> None:
    """Run a worker process.

    Convenience function for starting a worker from CLI.

    Args:
        db_url: PostgreSQL connection URL
        worker_id: Optional worker ID
        mode: Subject execution mode
        operator_image: Docker image URL for operator (empty = disabled)
    """
    worker = Worker(
        db_url=db_url,
        worker_id=worker_id,
        mode=mode,
        operator_image=operator_image,
    )
    await worker.start()
