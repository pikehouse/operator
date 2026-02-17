"""Work queue for distributed eval execution.

Provides atomic work item claim/complete operations using PostgreSQL
FOR UPDATE SKIP LOCKED for safe concurrent access from multiple workers.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore


@dataclass
class WorkItem:
    """A single unit of work from the queue."""

    id: int
    campaign_id: int
    subject_type: str
    chaos_type: str
    chaos_params: dict[str, Any]
    baseline: bool
    status: str
    worker_id: str | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    trial_id: int | None = None
    error: str | None = None
    sequence_number: int | None = None
    resolution_timeout: int | None = None


class WorkQueue:
    """Distributed work queue backed by PostgreSQL.

    Uses FOR UPDATE SKIP LOCKED for atomic work claiming, ensuring
    each work item is processed exactly once even with multiple workers.
    """

    def __init__(self, db: "AsyncpgDB"):
        """Initialize work queue with database connection.

        Args:
            db: PostgresDB instance for database operations
        """
        self.db = db

    async def enqueue(
        self,
        campaign_id: int,
        work_items: list[dict[str, Any]],
    ) -> list[int]:
        """Add work items to the queue.

        Args:
            campaign_id: Campaign these items belong to
            work_items: List of work item specs with:
                - subject_type: Subject type (e.g., "tikv")
                - chaos_type: Chaos type to inject
                - chaos_params: Optional params for chaos injection
                - baseline: Whether this is a baseline trial
                - sequence_number: Optional ordering for continuous mode

        Returns:
            List of work item IDs
        """
        pool = await self.db._get_pool()
        work_ids = []

        async with pool.acquire() as conn:
            for item in work_items:
                # Note: chaos_params is stored as TEXT not JSONB due to asyncpg behavior
                # We store as JSON string and parse on retrieval
                chaos_params = item.get("chaos_params", {})
                row = await conn.fetchrow(
                    """
                    INSERT INTO work_queue (
                        campaign_id, subject_type, chaos_type,
                        chaos_params, baseline, status, sequence_number,
                        resolution_timeout
                    )
                    VALUES ($1, $2, $3, $4::jsonb, $5, 'pending', $6, $7)
                    RETURNING id
                    """,
                    campaign_id,
                    item.get("subject_type", "tikv"),
                    item.get("chaos_type", "node_kill"),
                    json.dumps(chaos_params),
                    item.get("baseline", False),
                    item.get("sequence_number"),
                    item.get("resolution_timeout"),
                )
                work_ids.append(row["id"])

        return work_ids

    async def claim_next(
        self, worker_id: str, campaign_id: int | None = None
    ) -> WorkItem | None:
        """Atomically claim the next pending work item.

        Uses FOR UPDATE SKIP LOCKED to prevent multiple workers from
        claiming the same item. This is the key to safe distributed execution.

        For continuous campaigns (sequence_number is not NULL):
        - sequence_number=0: any worker can claim (first in sequence)
        - sequence_number>0: only claimable if the previous item (same campaign,
          sequence_number-1) was completed by the same worker. This enforces
          both ordering and same-worker affinity so state persists across trials.

        Args:
            worker_id: Unique identifier for this worker
            campaign_id: If provided, only claim items from this campaign

        Returns:
            WorkItem if one was claimed, None if queue is empty
        """
        pool = await self.db._get_pool()

        # Build campaign filter and parameter list
        if campaign_id is not None:
            campaign_filter = "AND w.campaign_id = $2"
            params = [worker_id, campaign_id]
        else:
            campaign_filter = ""
            params = [worker_id]

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE work_queue
                SET status = 'running',
                    worker_id = $1,
                    claimed_at = NOW()
                WHERE id = (
                    SELECT w.id FROM work_queue w
                    WHERE w.status = 'pending'
                      {campaign_filter}
                      AND (
                        w.sequence_number IS NULL
                        OR w.sequence_number = 0
                        OR (w.sequence_number > 0 AND EXISTS (
                          SELECT 1 FROM work_queue prev
                          WHERE prev.campaign_id = w.campaign_id
                            AND prev.sequence_number = w.sequence_number - 1
                            AND prev.status = 'completed'
                            AND prev.worker_id = $1
                        ))
                      )
                    ORDER BY w.id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                *params,
            )

            if row:
                # Parse chaos_params if it's a string (asyncpg may not auto-decode JSONB)
                chaos_params = row["chaos_params"]
                if isinstance(chaos_params, str):
                    chaos_params = json.loads(chaos_params) if chaos_params else {}
                elif chaos_params is None:
                    chaos_params = {}

                return WorkItem(
                    id=row["id"],
                    campaign_id=row["campaign_id"],
                    subject_type=row["subject_type"],
                    chaos_type=row["chaos_type"],
                    chaos_params=chaos_params,
                    baseline=row["baseline"],
                    status=row["status"],
                    worker_id=row["worker_id"],
                    claimed_at=row["claimed_at"],
                    trial_id=row["trial_id"],
                    sequence_number=row["sequence_number"],
                    resolution_timeout=row["resolution_timeout"],
                )
            return None

    async def update_vm_name(self, work_id: int, vm_name: str) -> None:
        """Record the VM name for a running work item.

        Args:
            work_id: Work item ID
            vm_name: GCP VM instance name
        """
        pool = await self.db._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE work_queue SET vm_name = $1 WHERE id = $2",
                vm_name,
                work_id,
            )

    async def complete(
        self,
        work_id: int,
        trial_id: int | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a work item as completed.

        Args:
            work_id: Work item ID to complete
            trial_id: Optional trial ID if trial was created
            error: Optional error message if work failed
        """
        pool = await self.db._get_pool()
        status = "failed" if error else "completed"

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE work_queue
                SET status = $1,
                    completed_at = NOW(),
                    trial_id = $2,
                    error = $3
                WHERE id = $4
                """,
                status,
                trial_id,
                error,
                work_id,
            )

    async def get_campaign_status(self, campaign_id: int) -> dict[str, int]:
        """Get status counts for a campaign's work items.

        Args:
            campaign_id: Campaign ID to check

        Returns:
            Dict with counts: pending, running, completed, failed
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM work_queue
                WHERE campaign_id = $1
                GROUP BY status
                """,
                campaign_id,
            )

            counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
            for row in rows:
                counts[row["status"]] = row["count"]
            return counts

    async def get_pending_count(self, campaign_id: int | None = None) -> int:
        """Get count of pending work items.

        Args:
            campaign_id: Optional campaign to filter by

        Returns:
            Number of pending items
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            if campaign_id:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as count FROM work_queue WHERE status = 'pending' AND campaign_id = $1",
                    campaign_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as count FROM work_queue WHERE status = 'pending'"
                )
            return row["count"] if row else 0

    async def get_campaign_detail(self, campaign_id: int) -> list[dict]:
        """Get detailed work item info for a campaign.

        Returns list of dicts with work item fields including chaos_type,
        status, worker_id, claimed_at, completed_at, trial_id, error.
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, subject_type, chaos_type, baseline, status,
                       worker_id, claimed_at, completed_at, trial_id, error, vm_name
                FROM work_queue
                WHERE campaign_id = $1
                ORDER BY id
                """,
                campaign_id,
            )
            return [dict(row) for row in rows]

    async def get_active_campaigns(self, include_finished: bool = False) -> list[dict]:
        """Get campaigns with work items.

        Args:
            include_finished: If False, only show campaigns with pending/running items
                or completed within the last 24 hours.

        Returns list of dicts with campaign_id, name, and status counts.
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            if include_finished:
                where_clause = ""
            else:
                # Show campaigns that are active or recently completed
                where_clause = """
                HAVING COUNT(*) FILTER (WHERE w.status IN ('pending', 'running')) > 0
                    OR (COUNT(*) FILTER (WHERE w.status = 'completed') > 0
                        AND MAX(w.completed_at) > NOW() - INTERVAL '4 hours')
                """

            rows = await conn.fetch(
                f"""
                SELECT w.campaign_id, c.name,
                       COUNT(*) FILTER (WHERE w.status = 'pending') as pending,
                       COUNT(*) FILTER (WHERE w.status = 'running') as running,
                       COUNT(*) FILTER (WHERE w.status = 'completed') as completed,
                       COUNT(*) FILTER (WHERE w.status = 'failed') as failed,
                       COUNT(*) as total
                FROM work_queue w
                JOIN campaigns c ON c.id = w.campaign_id
                GROUP BY w.campaign_id, c.name
                {where_clause}
                ORDER BY w.campaign_id DESC
                """
            )
            return [dict(row) for row in rows]

    async def get_worker_status(self, max_age_hours: float | None = None) -> list[dict]:
        """Get status of all known workers.

        Args:
            max_age_hours: Only show workers active within this many hours.
                If None, show all workers.

        Returns a list of dicts with worker_id, current task info,
        and history stats (completed count, failed count, last active time).
        """
        pool = await self.db._get_pool()

        age_filter = ""
        if max_age_hours is not None:
            age_filter = f"HAVING MAX(COALESCE(completed_at, claimed_at)) > NOW() - INTERVAL '{max_age_hours} hours'"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    worker_id,
                    COUNT(*) FILTER (WHERE status = 'running') as running_count,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
                    MAX(COALESCE(completed_at, claimed_at)) as last_active,
                    -- Current task info (if running)
                    (SELECT chaos_type FROM work_queue w2
                     WHERE w2.worker_id = work_queue.worker_id AND w2.status = 'running'
                     ORDER BY w2.claimed_at DESC LIMIT 1) as current_chaos_type,
                    (SELECT campaign_id FROM work_queue w3
                     WHERE w3.worker_id = work_queue.worker_id AND w3.status = 'running'
                     ORDER BY w3.claimed_at DESC LIMIT 1) as current_campaign_id,
                    (SELECT claimed_at FROM work_queue w4
                     WHERE w4.worker_id = work_queue.worker_id AND w4.status = 'running'
                     ORDER BY w4.claimed_at DESC LIMIT 1) as current_claimed_at,
                    -- VM name from most recent work item
                    (SELECT vm_name FROM work_queue w5
                     WHERE w5.worker_id = work_queue.worker_id AND w5.vm_name IS NOT NULL
                     ORDER BY w5.claimed_at DESC LIMIT 1) as vm_name
                FROM work_queue
                WHERE worker_id IS NOT NULL
                GROUP BY worker_id
                {age_filter}
                ORDER BY last_active DESC
                """
            )
            return [dict(row) for row in rows]

    async def cancel_pending(self, campaign_id: int | None = None) -> int:
        """Cancel pending work items by marking them as failed.

        Args:
            campaign_id: Optional campaign to filter by. If None, cancels all.

        Returns:
            Number of items cancelled.
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            if campaign_id:
                result = await conn.execute(
                    """
                    UPDATE work_queue
                    SET status = 'failed',
                        completed_at = NOW(),
                        error = 'Cancelled by user'
                    WHERE status = 'pending'
                      AND campaign_id = $1
                    """,
                    campaign_id,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE work_queue
                    SET status = 'failed',
                        completed_at = NOW(),
                        error = 'Cancelled by user'
                    WHERE status = 'pending'
                    """
                )
            return int(result.split()[1]) if result else 0

    async def kill_campaign(self, campaign_id: int) -> dict[str, int]:
        """Kill a campaign: cancel pending and running items in one shot.

        Args:
            campaign_id: Campaign ID to kill

        Returns:
            Dict with counts: pending_cancelled, running_cancelled
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            # Cancel pending items
            r1 = await conn.execute(
                """
                UPDATE work_queue
                SET status = 'failed',
                    completed_at = NOW(),
                    error = 'Killed by user'
                WHERE status = 'pending'
                  AND campaign_id = $1
                """,
                campaign_id,
            )
            pending = int(r1.split()[1]) if r1 else 0

            # Cancel running items
            r2 = await conn.execute(
                """
                UPDATE work_queue
                SET status = 'failed',
                    completed_at = NOW(),
                    error = 'Killed by user'
                WHERE status = 'running'
                  AND campaign_id = $1
                """,
                campaign_id,
            )
            running = int(r2.split()[1]) if r2 else 0

        return {"pending_cancelled": pending, "running_cancelled": running}

    async def retry_failed(
        self, campaign_id: int | None = None, chaos_type: str | None = None
    ) -> int:
        """Reset failed work items back to pending for retry.

        Args:
            campaign_id: Optional campaign to filter by. If None, retries all.
            chaos_type: Optional chaos type to filter by (e.g., "pd_leader_kill").

        Returns:
            Number of items reset.
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            # Build query dynamically based on filters
            conditions = ["status = 'failed'"]
            params: list[Any] = []

            if campaign_id is not None:
                params.append(campaign_id)
                conditions.append(f"campaign_id = ${len(params)}")

            if chaos_type is not None:
                params.append(chaos_type)
                conditions.append(f"chaos_type = ${len(params)}")

            where = " AND ".join(conditions)
            result = await conn.execute(
                f"""
                UPDATE work_queue
                SET status = 'pending',
                    worker_id = NULL,
                    claimed_at = NULL,
                    completed_at = NULL,
                    error = NULL
                WHERE {where}
                """,
                *params,
            )
            return int(result.split()[1]) if result else 0

    async def release_stale(self, timeout_seconds: int = 3600) -> int:
        """Release work items that have been running too long.

        Used to recover from worker crashes. Items running longer than
        timeout_seconds are reset to pending.

        Args:
            timeout_seconds: Time after which to consider a claim stale

        Returns:
            Number of items released
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE work_queue
                SET status = 'pending',
                    worker_id = NULL,
                    claimed_at = NULL
                WHERE status = 'running'
                  AND claimed_at < NOW() - make_interval(secs => $1)
                """,
                timeout_seconds,
            )
            # Extract count from "UPDATE N"
            return int(result.split()[1]) if result else 0


# Type alias for the database interface used by WorkQueue
AsyncpgDB = Any  # Actually PostgresDB, but avoids circular import
