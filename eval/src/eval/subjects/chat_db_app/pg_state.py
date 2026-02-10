"""Capture PostgreSQL configuration state (schema, indexes, settings).

Two entry points with identical return structures:
- capture_pg_state_asyncpg(dsn) — for local subject (direct asyncpg connection)
- capture_pg_state_psql(run_command, database_url) — for cloud subject (psql via SSH)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Curated list of performance/safety-relevant PG settings (~11 items).
# Avoids dumping ~350 settings from SHOW ALL.
CURATED_SETTINGS = [
    "max_connections",
    "shared_buffers",
    "work_mem",
    "maintenance_work_mem",
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
    "effective_cache_size",
    "random_page_cost",
    "log_min_duration_statement",
    "deadlock_timeout",
]

# SQL fragments shared by both implementations
SCHEMA_SQL = """
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

INDEXES_SQL = """
SELECT indexname, tablename, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname
"""

SETTINGS_SQL = """
SELECT name, setting
FROM pg_settings
WHERE name = ANY($1)
ORDER BY name
"""

# For psql (no $1 param support), we inline the list
SETTINGS_SQL_PSQL = """
SELECT name, setting
FROM pg_settings
WHERE name IN ({placeholders})
ORDER BY name
"""


def _build_state_dict(
    schema_rows: list[dict],
    index_rows: list[dict],
    settings_rows: list[dict],
) -> dict[str, Any]:
    """Build the canonical pg_state dict from raw query results."""
    # Tables: group columns by table_name
    tables: dict[str, dict] = {}
    for row in schema_rows:
        tbl = row["table_name"]
        if tbl not in tables:
            tables[tbl] = {"columns": []}
        tables[tbl]["columns"].append({
            "name": row["column_name"],
            "type": row["data_type"],
            "nullable": row["is_nullable"],
            "default": row.get("column_default"),
        })

    # Indexes: flat list
    indexes = [
        {
            "name": row["indexname"],
            "table": row["tablename"],
            "definition": row["indexdef"],
        }
        for row in index_rows
    ]

    # Settings: flat dict
    settings = {row["name"]: row["setting"] for row in settings_rows}

    return {
        "tables": tables,
        "indexes": indexes,
        "settings": settings,
    }


async def capture_pg_state_asyncpg(dsn: str) -> dict[str, Any]:
    """Capture PG state using a fresh asyncpg connection (local subject).

    Uses a dedicated connection (not the app's pool) so the capture is
    independent of the app's connection state.
    """
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        # Ensure agent-set statement_timeout doesn't kill our queries
        await conn.execute("SET LOCAL statement_timeout = '10000'")

        schema_rows = [dict(r) for r in await conn.fetch(SCHEMA_SQL)]
        index_rows = [dict(r) for r in await conn.fetch(INDEXES_SQL)]
        settings_rows = [
            dict(r) for r in await conn.fetch(SETTINGS_SQL, CURATED_SETTINGS)
        ]
    finally:
        await conn.close()

    return _build_state_dict(schema_rows, index_rows, settings_rows)


async def capture_pg_state_psql(
    run_command: Callable[..., Awaitable[tuple[int, str, str]]],
    database_url: str,
) -> dict[str, Any]:
    """Capture PG state via psql in a docker container (cloud subject).

    Combines all 3 queries into a single json_build_object() call for
    one SSH round-trip. Uses ``docker run --rm postgres:16 psql``.
    """
    # Build the settings IN-list for raw SQL
    settings_in = ", ".join(f"'{s}'" for s in CURATED_SETTINGS)

    # Single compound query that returns one JSON object
    compound_sql = f"""
SELECT json_build_object(
    'schema', (
        SELECT json_agg(row_to_json(s))
        FROM (
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        ) s
    ),
    'indexes', (
        SELECT json_agg(row_to_json(i))
        FROM (
            SELECT indexname, tablename, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
        ) i
    ),
    'settings', (
        SELECT json_agg(row_to_json(g))
        FROM (
            SELECT name, setting
            FROM pg_settings
            WHERE name IN ({settings_in})
            ORDER BY name
        ) g
    )
)
"""

    # Use psql -t -A to get raw JSON without headers/formatting
    # Escape single quotes in the SQL for the shell command
    psql_cmd = (
        f"docker run --rm --network=host postgres:16 psql '{database_url}' -t -A "
        f"-c \"SET LOCAL statement_timeout = '10000'\" "
        f"-c \"{compound_sql.strip()}\""
    )

    exit_code, stdout, stderr = await run_command(psql_cmd, timeout_sec=30.0)
    if exit_code != 0:
        raise RuntimeError(f"psql failed (exit {exit_code}): {stderr}")

    # psql -t -A returns the JSON on its own line; strip the SET output
    # The compound query result is the last non-empty line
    lines = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("psql returned empty output")

    raw = json.loads(lines[-1])

    schema_rows = raw.get("schema") or []
    index_rows = raw.get("indexes") or []
    settings_rows = raw.get("settings") or []

    return _build_state_dict(schema_rows, index_rows, settings_rows)
