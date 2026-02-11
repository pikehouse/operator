"""Async SQLite persistence for evaluation data.

This module provides the default SQLite backend for local eval execution.
For distributed cloud execution, see db_postgres.py.

Both backends implement the same interface (EvalDBProtocol) for compatibility.
"""

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import aiosqlite

from eval.types import Campaign, Trial


@runtime_checkable
class EvalDBProtocol(Protocol):
    """Protocol for eval database backends.

    Both SQLite (EvalDB) and PostgreSQL (PostgresDB) implement this interface,
    allowing code to work with either backend transparently.
    """

    async def ensure_schema(self) -> None:
        """Create tables if not exist and run migrations."""
        ...

    async def insert_campaign(self, campaign: Campaign) -> int:
        """Insert campaign record, return campaign_id."""
        ...

    async def insert_trial(self, trial: Trial) -> int:
        """Insert trial record, return trial_id."""
        ...

    async def get_campaign(self, campaign_id: int) -> Campaign | None:
        """Get campaign by ID."""
        ...

    async def get_trials(self, campaign_id: int) -> list[Trial]:
        """Get all trials for a campaign."""
        ...

    async def get_trial(self, trial_id: int) -> Trial | None:
        """Get trial by ID."""
        ...

    async def get_all_campaigns(self, limit: int = 100, offset: int = 0) -> list[Campaign]:
        """Get all campaigns with pagination."""
        ...

    async def update_trial_behavior(self, trial_id: int, behavior_json: str) -> None:
        """Update a trial's behavior classification JSON."""
        ...

    async def update_campaign_notable(self, campaign_id: int, notable: bool) -> None:
        """Update a campaign's notable flag."""
        ...

    async def count_campaigns(self) -> int:
        """Count total number of campaigns."""
        ...


async def get_db(
    remote: bool = False,
    db_path: Path | None = None,
    db_url: str | None = None,
) -> EvalDBProtocol:
    """Get the appropriate database backend.

    Args:
        remote: If True, use PostgresDB
        db_path: Local SQLite path (used when remote=False, defaults to eval.db)
        db_url: PostgreSQL URL (used when remote=True, falls back to EVAL_DATABASE_URL)

    Returns:
        Initialized database backend

    Raises:
        RuntimeError: If remote=True but no database URL available
    """
    if remote:
        url = db_url or os.environ.get("EVAL_DATABASE_URL")
        if not url:
            raise RuntimeError("EVAL_DATABASE_URL not found (check .env)")
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(url)
        await db.ensure_schema()
        return db
    else:
        db = EvalDB(db_path or Path("eval.db"))
        await db.ensure_schema()
        return db


SCHEMA_SQL = """
-- Campaign table
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT NOT NULL,
    chaos_type TEXT NOT NULL DEFAULT '',
    name TEXT DEFAULT '',
    trial_count INTEGER NOT NULL,
    baseline INTEGER NOT NULL DEFAULT 0,
    continuous INTEGER NOT NULL DEFAULT 0,
    notable INTEGER NOT NULL DEFAULT 0,
    variant_name TEXT DEFAULT 'default',
    topology_json TEXT DEFAULT '',
    git_commit_hash TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

-- Trial table with timing fields (RUN-02)
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    chaos_injected_at TEXT NOT NULL,
    ticket_created_at TEXT,
    resolved_at TEXT,
    ended_at TEXT NOT NULL,
    initial_state TEXT NOT NULL,
    final_state TEXT NOT NULL,
    chaos_metadata TEXT NOT NULL,
    commands_json TEXT NOT NULL DEFAULT '[]',
    operator_data_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trials_campaign ON trials(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_variant ON campaigns(variant_name);
"""


class EvalDB:
    """Async database for evaluation persistence.

    Uses aiosqlite for non-blocking database operations.
    IMPORTANT: Always call await db.commit() explicitly.
    """

    def __init__(self, db_path: Path):
        """Initialize with database path.

        Args:
            db_path: Path to eval.db file
        """
        self.db_path = db_path

    async def ensure_schema(self) -> None:
        """Create tables if not exist and run migrations."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
        await self.migrate_schema()

    async def migrate_schema(self) -> None:
        """Run schema migrations for new columns.

        Safe to call multiple times - checks if columns exist before adding.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Check if variant_name column exists
            cursor = await db.execute("PRAGMA table_info(campaigns)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]

            if "variant_name" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN variant_name TEXT DEFAULT 'default'"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_campaigns_variant ON campaigns(variant_name)"
                )
                await db.commit()

            if "name" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN name TEXT DEFAULT ''"
                )
                # Backfill: name = subject_name/chaos_type for old rows
                await db.execute(
                    "UPDATE campaigns SET name = subject_name || '/' || chaos_type WHERE name = '' OR name IS NULL"
                )
                await db.commit()

            if "topology_json" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN topology_json TEXT DEFAULT ''"
                )
                await db.commit()

            if "git_commit_hash" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN git_commit_hash TEXT DEFAULT ''"
                )
                await db.commit()

            if "continuous" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN continuous INTEGER NOT NULL DEFAULT 0"
                )
                await db.commit()

            if "notable" not in column_names:
                await db.execute(
                    "ALTER TABLE campaigns ADD COLUMN notable INTEGER NOT NULL DEFAULT 0"
                )
                await db.commit()

            # Check if operator_data_json column exists on trials
            cursor = await db.execute("PRAGMA table_info(trials)")
            trial_columns = await cursor.fetchall()
            trial_column_names = [col[1] for col in trial_columns]

            if "operator_data_json" not in trial_column_names:
                await db.execute(
                    "ALTER TABLE trials ADD COLUMN operator_data_json TEXT NOT NULL DEFAULT '{}'"
                )
                await db.commit()

            if "behavior_json" not in trial_column_names:
                await db.execute(
                    "ALTER TABLE trials ADD COLUMN behavior_json TEXT DEFAULT ''"
                )
                await db.commit()

    async def insert_campaign(self, campaign: Campaign) -> int:
        """Insert campaign record, return campaign_id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO campaigns (subject_name, chaos_type, name, trial_count, baseline, continuous, variant_name, topology_json, git_commit_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.subject_name,
                    "",  # chaos_type kept for backward compat, no longer used
                    campaign.name,
                    campaign.trial_count,
                    1 if campaign.baseline else 0,
                    1 if campaign.continuous else 0,
                    campaign.variant_name,
                    campaign.topology_json,
                    campaign.git_commit_hash,
                    campaign.created_at,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def insert_trial(self, trial: Trial) -> int:
        """Insert trial record, return trial_id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO trials (
                    campaign_id, started_at, chaos_injected_at,
                    ticket_created_at, resolved_at, ended_at,
                    initial_state, final_state, chaos_metadata, commands_json,
                    operator_data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial.campaign_id,
                    trial.started_at,
                    trial.chaos_injected_at,
                    trial.ticket_created_at,
                    trial.resolved_at,
                    trial.ended_at,
                    trial.initial_state,
                    trial.final_state,
                    trial.chaos_metadata,
                    trial.commands_json,
                    trial.operator_data_json,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_campaign(self, campaign_id: int) -> Campaign | None:
        """Get campaign by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            )
            row = await cursor.fetchone()
            if row:
                return Campaign.from_row(row)
            return None

    async def get_trials(self, campaign_id: int) -> list[Trial]:
        """Get all trials for a campaign."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trials WHERE campaign_id = ? ORDER BY id",
                (campaign_id,),
            )
            rows = await cursor.fetchall()
            return [Trial.from_row(row) for row in rows]

    async def get_all_campaigns(self, limit: int = 100, offset: int = 0) -> list[Campaign]:
        """Get all campaigns with pagination.

        Args:
            limit: Maximum number of campaigns to return
            offset: Number of campaigns to skip

        Returns:
            List of Campaign objects ordered by created_at DESC
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [Campaign.from_row(row) for row in rows]

    async def get_trial(self, trial_id: int) -> Trial | None:
        """Get trial by ID.

        Args:
            trial_id: Trial ID to fetch

        Returns:
            Trial object if found, None otherwise
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trials WHERE id = ?", (trial_id,)
            )
            row = await cursor.fetchone()
            if row:
                return Trial.from_row(row)
            return None

    async def update_trial_behavior(self, trial_id: int, behavior_json: str) -> None:
        """Update a trial's behavior classification JSON.

        Args:
            trial_id: Trial to update
            behavior_json: Serialized BehaviorTimeline JSON
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trials SET behavior_json = ? WHERE id = ?",
                (behavior_json, trial_id),
            )
            await db.commit()

    async def update_campaign_notable(self, campaign_id: int, notable: bool) -> None:
        """Update a campaign's notable flag.

        Args:
            campaign_id: Campaign to update
            notable: Whether to mark as notable
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE campaigns SET notable = ? WHERE id = ?",
                (1 if notable else 0, campaign_id),
            )
            await db.commit()

    async def count_campaigns(self) -> int:
        """Count total number of campaigns.

        Returns:
            Total campaign count
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM campaigns")
            row = await cursor.fetchone()
            return row[0] if row else 0
