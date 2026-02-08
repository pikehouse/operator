"""
PostgreSQL diagnostic client for the chat-db-app observer.

Uses a small dedicated asyncpg pool (1-2 connections) separate from the app's
pool. Queries pg_stat_activity and pg_stat_database for observability.
"""

from __future__ import annotations

import asyncpg

from chat_db_app_observer.types import (
    LongRunningQuery,
    PgDatabaseStats,
    PgSessionStats,
)


class PgClient:
    """
    PostgreSQL diagnostic client.

    Queries system views for connection and query health.
    Uses its own connection pool (separate from the app).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str) -> PgClient:
        """Create a PgClient with a small diagnostic pool."""
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, command_timeout=10)
        return cls(pool)

    async def close(self) -> None:
        """Close the diagnostic pool."""
        await self._pool.close()

    async def is_reachable(self) -> bool:
        """Check basic connectivity to PostgreSQL."""
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def get_max_connections(self) -> int:
        """Get the max_connections setting from PostgreSQL."""
        try:
            async with self._pool.acquire() as conn:
                val = await conn.fetchval("SHOW max_connections")
                return int(val)
        except Exception:
            return 100  # sensible default

    async def get_session_stats(self) -> PgSessionStats:
        """
        Get session statistics from pg_stat_activity.

        Counts connections by state: active, idle, idle in transaction,
        and waiting on locks.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    state,
                    count(*) as cnt,
                    count(*) FILTER (WHERE wait_event_type = 'Lock') as lock_waiters
                FROM pg_stat_activity
                WHERE backend_type = 'client backend'
                  AND pid != pg_backend_pid()
                GROUP BY state
            """)

        active = 0
        idle = 0
        idle_in_tx = 0
        waiting_on_lock = 0

        for row in rows:
            state = row["state"]
            cnt = row["cnt"]
            lock_wait = row["lock_waiters"]

            if state == "active":
                active += cnt
            elif state == "idle":
                idle += cnt
            elif state in ("idle in transaction", "idle in transaction (aborted)"):
                idle_in_tx += cnt

            waiting_on_lock += lock_wait

        return PgSessionStats(
            active_connections=active + idle + idle_in_tx,
            idle_connections=idle,
            idle_in_transaction=idle_in_tx,
            waiting_on_lock=waiting_on_lock,
        )

    async def get_long_running_queries(
        self, threshold_sec: float = 10.0
    ) -> list[LongRunningQuery]:
        """
        Get queries running longer than the threshold.

        Returns active queries from pg_stat_activity that have been
        running for more than threshold_sec seconds.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    pid,
                    EXTRACT(EPOCH FROM (now() - query_start)) AS duration_sec,
                    state,
                    LEFT(query, 200) AS query_preview
                FROM pg_stat_activity
                WHERE backend_type = 'client backend'
                  AND pid != pg_backend_pid()
                  AND state = 'active'
                  AND query_start IS NOT NULL
                  AND EXTRACT(EPOCH FROM (now() - query_start)) > $1
                ORDER BY duration_sec DESC
                LIMIT 20
            """, threshold_sec)

        return [
            LongRunningQuery(
                pid=row["pid"],
                duration_sec=round(row["duration_sec"], 1),
                state=row["state"],
                query_preview=row["query_preview"],
            )
            for row in rows
        ]

    async def get_deadlock_count(self) -> int:
        """Get total deadlock count from pg_stat_database."""
        async with self._pool.acquire() as conn:
            val = await conn.fetchval("""
                SELECT COALESCE(SUM(deadlocks), 0)
                FROM pg_stat_database
            """)
            return int(val)
