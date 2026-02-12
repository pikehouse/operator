"""PostgreSQL backend for distributed eval execution.

Uses asyncpg for async PostgreSQL operations. This backend is used for
cloud execution where multiple workers need to coordinate via a shared
database (Cloud SQL).

The local SQLite backend (db.py) remains the default for single-machine
execution.
"""

import json
from typing import Any

from eval.types import parse_iso_datetime

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
    continuous BOOLEAN DEFAULT FALSE,
    notable BOOLEAN DEFAULT FALSE,
    notes TEXT DEFAULT '',
    variant_name TEXT DEFAULT 'default',
    topology_json JSONB,
    git_commit_hash TEXT DEFAULT '',
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
    commands_json JSONB,
    operator_data_json JSONB DEFAULT '{}'::jsonb
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
    error TEXT,
    sequence_number INTEGER
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
            self._pool = await asyncpg.create_pool(
                self.connection_url, min_size=1, max_size=3
            )
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
            # Migration: add operator_data_json column if missing
            op_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'trials' AND column_name = 'operator_data_json'
                )
            """)
            if not op_col_exists:
                await conn.execute(
                    "ALTER TABLE trials ADD COLUMN operator_data_json JSONB DEFAULT '{}'::jsonb"
                )
            # Migration: add topology_json column if missing
            topo_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'topology_json'
                )
            """)
            if not topo_col_exists:
                await conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN topology_json JSONB"
                )
            # Migration: add git_commit_hash column if missing
            git_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'git_commit_hash'
                )
            """)
            if not git_col_exists:
                await conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN git_commit_hash TEXT DEFAULT ''"
                )
            # Migration: add behavior_json column if missing
            behavior_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'trials' AND column_name = 'behavior_json'
                )
            """)
            if not behavior_col_exists:
                await conn.execute(
                    "ALTER TABLE trials ADD COLUMN behavior_json TEXT DEFAULT ''"
                )
            # Migration: add continuous column to campaigns if missing
            continuous_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'continuous'
                )
            """)
            if not continuous_col_exists:
                await conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN continuous BOOLEAN DEFAULT FALSE"
                )
            # Migration: add notable column to campaigns if missing
            notable_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'notable'
                )
            """)
            if not notable_col_exists:
                await conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN notable BOOLEAN DEFAULT FALSE"
                )
            # Migration: add notes column to campaigns if missing
            notes_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'campaigns' AND column_name = 'notes'
                )
            """)
            if not notes_col_exists:
                await conn.execute(
                    "ALTER TABLE campaigns ADD COLUMN notes TEXT DEFAULT ''"
                )
            # Migration: add sequence_number column to work_queue if missing
            seq_col_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'work_queue' AND column_name = 'sequence_number'
                )
            """)
            if not seq_col_exists:
                await conn.execute(
                    "ALTER TABLE work_queue ADD COLUMN sequence_number INTEGER"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_work_queue_sequence ON work_queue(campaign_id, sequence_number)"
                )

    async def insert_campaign(self, campaign: Campaign) -> int:
        """Insert campaign record, return campaign_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO campaigns (subject_name, chaos_type, name, trial_count, baseline, continuous, variant_name, topology_json, git_commit_hash, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                RETURNING id
                """,
                campaign.subject_name,
                "",  # chaos_type kept for backward compat, no longer used
                campaign.name,
                campaign.trial_count,
                campaign.baseline,
                campaign.continuous,
                campaign.variant_name,
                campaign.topology_json or None,
                campaign.git_commit_hash,
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
                    initial_state, final_state, chaos_metadata, commands_json,
                    operator_data_json
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb)
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
                trial.operator_data_json or "{}",
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
                return Campaign.from_row(row)
            return None

    async def get_trials(self, campaign_id: int) -> list[Trial]:
        """Get all trials for a campaign."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM trials WHERE campaign_id = $1 ORDER BY id",
                campaign_id,
            )
            return [Trial.from_row(row, jsonb_to_str=_jsonb_to_str) for row in rows]

    async def get_trial(self, trial_id: int) -> Trial | None:
        """Get trial by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM trials WHERE id = $1", trial_id
            )
            if row:
                return Trial.from_row(row, jsonb_to_str=_jsonb_to_str)
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
            return [Campaign.from_row(row) for row in rows]

    async def update_trial_behavior(self, trial_id: int, behavior_json: str) -> None:
        """Update a trial's behavior classification JSON.

        Args:
            trial_id: Trial to update
            behavior_json: Serialized BehaviorTimeline JSON
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE trials SET behavior_json = $1 WHERE id = $2",
                behavior_json,
                trial_id,
            )

    async def update_campaign_notable(self, campaign_id: int, notable: bool) -> None:
        """Update a campaign's notable flag.

        Args:
            campaign_id: Campaign to update
            notable: Whether to mark as notable
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE campaigns SET notable = $1 WHERE id = $2",
                notable,
                campaign_id,
            )

    async def update_campaign_notes(self, campaign_id: int, notes: str) -> None:
        """Update a campaign's notes text.

        Args:
            campaign_id: Campaign to update
            notes: Free-text notes (empty string to clear)
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE campaigns SET notes = $1 WHERE id = $2",
                notes,
                campaign_id,
            )

    async def count_campaigns(self) -> int:
        """Count total number of campaigns."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM campaigns")
            return row["count"] if row else 0
