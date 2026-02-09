"""PostgreSQL backend for distributed eval execution.

Uses asyncpg for async PostgreSQL operations. This backend is used for
cloud execution where multiple workers need to coordinate via a shared
database (Cloud SQL).

The local SQLite backend (db.py) remains the default for single-machine
execution.
"""

import json
from datetime import datetime, timezone
from typing import Any


def parse_iso_datetime(iso_str: str | None) -> datetime | None:
    """Parse ISO8601 string to datetime, handling timezone-naive strings."""
    if iso_str is None:
        return None
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from eval.types import Campaign, Trial


def _jsonb_to_str(val: Any, default: str = "{}") -> str:
    """Convert asyncpg JSONB value to JSON string for Trial dataclass.

    asyncpg auto-decodes JSONB: arrays→list, objects→dict, strings→str.
    If the JSONB column stored a double-encoded JSON string, asyncpg returns
    a Python str (already valid JSON). In that case, return it directly
    instead of re-encoding with json.dumps (which would double-encode).
    """
    if val is None:
        return default
    if isinstance(val, str):
        return val  # Already a JSON string, don't double-encode
    return json.dumps(val)


POSTGRES_SCHEMA_SQL = """
-- Campaign table
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    subject_name TEXT NOT NULL,
    chaos_type TEXT NOT NULL DEFAULT '',
    name TEXT DEFAULT '',
    trial_count INTEGER NOT NULL,
    baseline BOOLEAN DEFAULT FALSE,
    variant_name TEXT DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trial table with timing fields
CREATE TABLE IF NOT EXISTS trials (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id),
    started_at TIMESTAMPTZ,
    chaos_injected_at TIMESTAMPTZ,
    ticket_created_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    initial_state JSONB,
    final_state JSONB,
    chaos_metadata JSONB,
    commands_json JSONB
);

-- Work queue for distributed execution
CREATE TABLE IF NOT EXISTS work_queue (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER REFERENCES campaigns(id),
    subject_type TEXT NOT NULL,
    chaos_type TEXT NOT NULL,
    chaos_params JSONB,
    baseline BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'pending',
    worker_id TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    trial_id INTEGER REFERENCES trials(id),
    error TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trials_campaign ON trials(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_variant ON campaigns(variant_name);
CREATE INDEX IF NOT EXISTS idx_work_queue_status ON work_queue(status);
CREATE INDEX IF NOT EXISTS idx_work_queue_campaign ON work_queue(campaign_id);
"""


class PostgresDB:
    """Async PostgreSQL database for distributed eval execution.

    Uses asyncpg for connection pooling and async operations.
    Implements the same interface as EvalDB for compatibility.
    """

    def __init__(self, connection_url: str):
        """Initialize with PostgreSQL connection URL.

        Args:
            connection_url: PostgreSQL connection string
                e.g., "postgresql://user:pass@host:5432/dbname"

        Raises:
            ImportError: If asyncpg is not installed
        """
        if asyncpg is None:
            raise ImportError(
                "asyncpg is required for PostgreSQL support. "
                "Install with: pip install 'eval[cloud]'"
            )
        self.connection_url = connection_url
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> "asyncpg.Pool":
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.connection_url)
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def ensure_schema(self) -> None:
        """Create tables if not exist and run migrations."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(POSTGRES_SCHEMA_SQL)
            # Migration: add name column if missing (existing databases)
            col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'name'
                )
            """)
            if not col_exists:
                await conn.execute("ALTER TABLE campaigns ADD COLUMN name TEXT DEFAULT ''")
                await conn.execute(
                    "UPDATE campaigns SET name = subject_name || '/' || chaos_type WHERE name = '' OR name IS NULL"
                )

    async def insert_campaign(self, campaign: Campaign) -> int:
        """Insert campaign record, return campaign_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO campaigns (subject_name, chaos_type, name, trial_count, baseline, variant_name, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                campaign.subject_name,
                "",  # chaos_type kept for backward compat, no longer used
                campaign.name,
                campaign.trial_count,
                campaign.baseline,
                campaign.variant_name,
                parse_iso_datetime(campaign.created_at),
            )
            return row["id"]

    async def insert_trial(self, trial: Trial) -> int:
        """Insert trial record, return trial_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # JSONB columns need JSON strings, not dicts
            # Trial dataclass stores JSON as strings, so pass directly
            row = await conn.fetchrow(
                """
                INSERT INTO trials (
                    campaign_id, started_at, chaos_injected_at,
                    ticket_created_at, resolved_at, ended_at,
                    initial_state, final_state, chaos_metadata, commands_json
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb)
                RETURNING id
                """,
                trial.campaign_id,
                parse_iso_datetime(trial.started_at),
                parse_iso_datetime(trial.chaos_injected_at),
                parse_iso_datetime(trial.ticket_created_at),
                parse_iso_datetime(trial.resolved_at),
                parse_iso_datetime(trial.ended_at),
                trial.initial_state or "{}",
                trial.final_state or "{}",
                trial.chaos_metadata or "{}",
                trial.commands_json or "[]",
            )
            return row["id"]

    async def get_campaign(self, campaign_id: int) -> Campaign | None:
        """Get campaign by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM campaigns WHERE id = $1", campaign_id
            )
            if row:
                # Read name column; fall back to subject_name/chaos_type for old DBs
                name = row.get("name") or f"{row['subject_name']}/{row['chaos_type']}"
                return Campaign(
                    id=row["id"],
                    subject_name=row["subject_name"],
                    name=name,
                    trial_count=row["trial_count"],
                    baseline=row["baseline"],
                    variant_name=row["variant_name"] or "default",
                    created_at=row["created_at"].isoformat() if row["created_at"] else "",
                )
            return None

    async def get_trials(self, campaign_id: int) -> list[Trial]:
        """Get all trials for a campaign."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM trials WHERE campaign_id = $1 ORDER BY id",
                campaign_id,
            )
            return [
                Trial(
                    id=row["id"],
                    campaign_id=row["campaign_id"],
                    started_at=row["started_at"].isoformat() if row["started_at"] else "",
                    chaos_injected_at=row["chaos_injected_at"].isoformat() if row["chaos_injected_at"] else "",
                    ticket_created_at=row["ticket_created_at"].isoformat() if row["ticket_created_at"] else None,
                    resolved_at=row["resolved_at"].isoformat() if row["resolved_at"] else None,
                    ended_at=row["ended_at"].isoformat() if row["ended_at"] else "",
                    initial_state=_jsonb_to_str(row["initial_state"], "{}"),
                    final_state=_jsonb_to_str(row["final_state"], "{}"),
                    chaos_metadata=_jsonb_to_str(row["chaos_metadata"], "{}"),
                    commands_json=_jsonb_to_str(row["commands_json"], "[]"),
                )
                for row in rows
            ]

    async def get_trial(self, trial_id: int) -> Trial | None:
        """Get trial by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM trials WHERE id = $1", trial_id
            )
            if row:
                return Trial(
                    id=row["id"],
                    campaign_id=row["campaign_id"],
                    started_at=row["started_at"].isoformat() if row["started_at"] else "",
                    chaos_injected_at=row["chaos_injected_at"].isoformat() if row["chaos_injected_at"] else "",
                    ticket_created_at=row["ticket_created_at"].isoformat() if row["ticket_created_at"] else None,
                    resolved_at=row["resolved_at"].isoformat() if row["resolved_at"] else None,
                    ended_at=row["ended_at"].isoformat() if row["ended_at"] else "",
                    initial_state=_jsonb_to_str(row["initial_state"], "{}"),
                    final_state=_jsonb_to_str(row["final_state"], "{}"),
                    chaos_metadata=_jsonb_to_str(row["chaos_metadata"], "{}"),
                    commands_json=_jsonb_to_str(row["commands_json"], "[]"),
                )
            return None

    async def get_all_campaigns(self, limit: int = 100, offset: int = 0) -> list[Campaign]:
        """Get all campaigns with pagination."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
            return [
                Campaign(
                    id=row["id"],
                    subject_name=row["subject_name"],
                    name=row.get("name") or f"{row['subject_name']}/{row['chaos_type']}",
                    trial_count=row["trial_count"],
                    baseline=row["baseline"],
                    variant_name=row["variant_name"] or "default",
                    created_at=row["created_at"].isoformat() if row["created_at"] else "",
                )
                for row in rows
            ]

    async def count_campaigns(self) -> int:
        """Count total number of campaigns."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM campaigns")
            return row["count"] if row else 0
