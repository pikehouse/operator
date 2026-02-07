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
                        chaos_params, baseline, status
                    )
                    VALUES ($1, $2, $3, $4::jsonb, $5, 'pending')
                    RETURNING id
                    """,
                    campaign_id,
                    item.get("subject_type", "tikv"),
                    item.get("chaos_type", "node_kill"),
                    json.dumps(chaos_params),
                    item.get("baseline", False),
                )
                work_ids.append(row["id"])

        return work_ids

    async def claim_next(self, worker_id: str) -> WorkItem | None:
        """Atomically claim the next pending work item.

        Uses FOR UPDATE SKIP LOCKED to prevent multiple workers from
        claiming the same item. This is the key to safe distributed execution.

        Args:
            worker_id: Unique identifier for this worker

        Returns:
            WorkItem if one was claimed, None if queue is empty
        """
        pool = await self.db._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE work_queue
                SET status = 'running',
                    worker_id = $1,
                    claimed_at = NOW()
                WHERE id = (
                    SELECT id FROM work_queue
                    WHERE status = 'pending'
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """,
                worker_id,
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
                )
            return None

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
                  AND claimed_at < NOW() - INTERVAL '%s seconds'
                """,
                timeout_seconds,
            )
            # Extract count from "UPDATE N"
            return int(result.split()[1]) if result else 0


# Type alias for the database interface used by WorkQueue
AsyncpgDB = Any  # Actually PostgresDB, but avoids circular import
