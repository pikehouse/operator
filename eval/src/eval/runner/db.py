"""Async SQLite persistence for evaluation data."""

import aiosqlite
from pathlib import Path

from eval.types import Campaign, Trial


SCHEMA_SQL = """
-- Campaign table
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT NOT NULL,
    chaos_type TEXT NOT NULL,
    trial_count INTEGER NOT NULL,
    baseline INTEGER NOT NULL DEFAULT 0,
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
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trials_campaign ON trials(campaign_id);
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
        """Create tables if not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def insert_campaign(self, campaign: Campaign) -> int:
        """Insert campaign record, return campaign_id."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO campaigns (subject_name, chaos_type, trial_count, baseline, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    campaign.subject_name,
                    campaign.chaos_type,
                    campaign.trial_count,
                    1 if campaign.baseline else 0,
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
                    initial_state, final_state, chaos_metadata, commands_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                return Campaign(
                    id=row["id"],
                    subject_name=row["subject_name"],
                    chaos_type=row["chaos_type"],
                    trial_count=row["trial_count"],
                    baseline=bool(row["baseline"]),
                    created_at=row["created_at"],
                )
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
            return [
                Trial(
                    id=row["id"],
                    campaign_id=row["campaign_id"],
                    started_at=row["started_at"],
                    chaos_injected_at=row["chaos_injected_at"],
                    ticket_created_at=row["ticket_created_at"],
                    resolved_at=row["resolved_at"],
                    ended_at=row["ended_at"],
                    initial_state=row["initial_state"],
                    final_state=row["final_state"],
                    chaos_metadata=row["chaos_metadata"],
                    commands_json=row["commands_json"],
                )
                for row in rows
            ]

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
            return [
                Campaign(
                    id=row["id"],
                    subject_name=row["subject_name"],
                    chaos_type=row["chaos_type"],
                    trial_count=row["trial_count"],
                    baseline=bool(row["baseline"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

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
                return Trial(
                    id=row["id"],
                    campaign_id=row["campaign_id"],
                    started_at=row["started_at"],
                    chaos_injected_at=row["chaos_injected_at"],
                    ticket_created_at=row["ticket_created_at"],
                    resolved_at=row["resolved_at"],
                    ended_at=row["ended_at"],
                    initial_state=row["initial_state"],
                    final_state=row["final_state"],
                    chaos_metadata=row["chaos_metadata"],
                    commands_json=row["commands_json"],
                )
            return None

    async def count_campaigns(self) -> int:
        """Count total number of campaigns.

        Returns:
            Total campaign count
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM campaigns")
            row = await cursor.fetchone()
            return row[0] if row else 0
