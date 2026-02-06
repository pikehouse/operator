"""Worker process for distributed eval execution.

Workers poll the work queue for pending items, execute trials,
and report results back to the shared database.
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
    ):
        """Initialize worker.

        Args:
            db_url: PostgreSQL connection URL
            worker_id: Unique worker identifier (auto-generated if not provided)
            mode: Subject execution mode (e.g., "cloud-gcp")
            poll_interval: Seconds between queue polls
        """
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.mode = mode
        self.poll_interval = poll_interval
        self.db = PostgresDB(db_url)
        self.queue = WorkQueue(self.db)
        self._running = False
        self._current_subject = None

    async def start(self) -> None:
        """Start the worker loop.

        Polls queue for work, executes trials, and reports results.
        Runs until stop() is called or SIGINT/SIGTERM received.
        """
        self._running = True
        console.print(f"[bold green]Worker {self.worker_id} starting[/bold green]")
        console.print(f"Mode: {self.mode}")

        # Ensure schema exists
        await self.db.ensure_schema()

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        while self._running:
            try:
                # Try to claim work
                work_item = await self.queue.claim_next(self.worker_id)

                if work_item:
                    console.print(
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

        console.print(f"[bold yellow]Worker {self.worker_id} stopped[/bold yellow]")
        await self.db.close()

    async def stop(self) -> None:
        """Stop the worker loop gracefully."""
        console.print("[yellow]Shutting down worker...[/yellow]")
        self._running = False

        # Clean up current subject if any
        if self._current_subject:
            try:
                await self._cleanup_subject(self._current_subject)
            except Exception as e:
                logger.warning(f"Error cleaning up subject: {e}")

    async def _execute_work(self, work_item: WorkItem) -> None:
        """Execute a single work item.

        Args:
            work_item: Work item to execute
        """
        trial_id = None
        error = None

        try:
            # Create subject for this work item
            subject = SubjectRegistry.create(
                work_item.subject_type,
                instance_id=0,  # Cloud subjects don't need instance isolation
                mode=self.mode,
            )
            self._current_subject = subject

            # Get campaign for variant info
            campaign = await self.db.get_campaign(work_item.campaign_id)
            variant_config = None
            if campaign and campaign.variant_name:
                try:
                    variant_config = get_variant(campaign.variant_name)
                except ValueError:
                    logger.warning(f"Variant not found: {campaign.variant_name}")

            # Run the trial
            trial = await self._run_trial(
                subject=subject,
                chaos_type=work_item.chaos_type,
                campaign_id=work_item.campaign_id,
                baseline=work_item.baseline,
                chaos_params=work_item.chaos_params,
                variant_config=variant_config,
            )

            # Store trial result
            trial_id = await self.db.insert_trial(trial)
            console.print(f"[green]Work item {work_item.id} completed -> Trial {trial_id}[/green]")

        except Exception as e:
            error = str(e)
            logger.exception(f"Work item {work_item.id} failed: {e}")
            console.print(f"[red]Work item {work_item.id} failed: {e}[/red]")

        finally:
            self._current_subject = None

            # Mark work item complete (or failed)
            await self.queue.complete(
                work_id=work_item.id,
                trial_id=trial_id,
                error=error,
            )

    async def _run_trial(
        self,
        subject,
        chaos_type: str,
        campaign_id: int,
        baseline: bool,
        chaos_params: dict[str, Any],
        variant_config: VariantConfig | None,
    ) -> Trial:
        """Run a single trial.

        This is a simplified version of run_trial from harness.py,
        adapted for cloud execution without operator.db dependency.

        Args:
            subject: EvalSubject instance
            chaos_type: Chaos type to inject
            campaign_id: Campaign ID
            baseline: Whether this is a baseline trial
            chaos_params: Parameters for chaos injection
            variant_config: Optional variant configuration

        Returns:
            Trial record
        """
        from datetime import datetime, timezone
        import json

        def now() -> str:
            return datetime.now(timezone.utc).isoformat()

        started_at = now()

        # Reset subject
        console.print("[blue]Resetting subject...[/blue]")
        await subject.reset()

        # Wait for healthy
        console.print("[blue]Waiting for healthy state...[/blue]")
        healthy = await subject.wait_healthy(timeout_sec=120.0)
        if not healthy:
            raise RuntimeError("Subject failed to become healthy")

        # Capture initial state
        initial_state = await subject.capture_state()

        # Inject chaos (unless baseline)
        chaos_metadata = {}
        if not baseline and chaos_type != "none":
            console.print(f"[yellow]Injecting chaos: {chaos_type}[/yellow]")
            chaos_injected_at = now()
            chaos_metadata = await subject.inject_chaos(chaos_type, **chaos_params)
        else:
            chaos_injected_at = now()

        try:
            # Wait for resolution
            # In cloud mode without operator.db, we just wait for subject to recover
            # Full agent integration would require operator subprocess management
            console.print("[cyan]Waiting for recovery...[/cyan]")
            resolved = await subject.wait_healthy(timeout_sec=300.0)
            resolved_at = now() if resolved else None

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

        return Trial(
            campaign_id=campaign_id,
            started_at=started_at,
            chaos_injected_at=chaos_injected_at,
            ticket_created_at=None,  # No ticket tracking in cloud worker mode
            resolved_at=resolved_at,
            ended_at=ended_at,
            initial_state=json.dumps(initial_state),
            final_state=json.dumps(final_state),
            chaos_metadata=json.dumps(chaos_metadata),
            commands_json="[]",  # No command extraction in cloud worker mode
        )

    async def _cleanup_subject(self, subject) -> None:
        """Clean up a subject (e.g., delete cloud VM)."""
        if hasattr(subject, "cleanup"):
            await subject.cleanup()


async def run_worker(
    db_url: str,
    worker_id: str | None = None,
    mode: str = "cloud-gcp",
) -> None:
    """Run a worker process.

    Convenience function for starting a worker from CLI.

    Args:
        db_url: PostgreSQL connection URL
        worker_id: Optional worker ID
        mode: Subject execution mode
    """
    worker = Worker(db_url=db_url, worker_id=worker_id, mode=mode)
    await worker.start()
