"""Chat DB App Shard evaluation subject.

Variant of chat-db-app with all code-level bugs pre-fixed.
The challenge is architectural: a single constrained PostgreSQL
instance can't handle 2M messages under load. The only viable
fix is horizontal database sharding.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from eval.subjects.chat_db_app.subject import ChatDBAppEvalSubject

logger = logging.getLogger(__name__)

# All shard chaos types share the same load profile — only the prompt differs
_SHARD_LOAD_PROFILE = {
    "NUM_USERS": "40",
    "REQUEST_DELAY": "0.2",
    "STREAM_RATIO": "0.0",
    "RAMP_UP_SECONDS": "5",
    "READ_RATIO": "0.7",
    "BURST_MODE": "false",
    "BURST_CONCURRENCY": "1",
    "SEARCH_ENABLED": "false",
    "SEARCH_RATIO": "0.0",
}

# Heavy cross-shard load profile for phase 2 (after sharding is implemented)
_SHARD_FANOUT_LOAD_PROFILE = {
    "NUM_USERS": "60",
    "REQUEST_DELAY": "0.2",
    "STREAM_RATIO": "0.0",
    "RAMP_UP_SECONDS": "5",
    "READ_RATIO": "0.5",
    "BURST_MODE": "false",
    "BURST_CONCURRENCY": "1",
    "SEARCH_ENABLED": "true",       # Cross-shard ILIKE search
    "SEARCH_RATIO": "0.4",          # 40% of iterations do search
    "BROADCAST_ENABLED": "true",    # Fan-out notification inserts
    "BROADCAST_INTERVAL": "8",      # Every 8 seconds
    "BROADCAST_SERIALIZABLE": "false",
    "BROADCAST_PAYLOAD_SIZE": "0",
    "PAGINATE_NOTIFICATIONS": "false",
    "POLL_ENABLED": "false",
    "POLL_RATIO": "0.0",
    "UNREAD_CHECK_RATIO": "0.0",
    "MARK_READ_RATIO": "0.0",
    "LIST_NOTIFS_RATIO": "0.0",
    "MULTI_USER_COUNT": "1",
}

# Phase 3: Blob storage — BYTEA attachments overwhelm sharded PG
_BLOB_STORAGE_LOAD_PROFILE = {
    "NUM_USERS": "40",
    "REQUEST_DELAY": "0.3",
    "READ_RATIO": "0.3",
    "SEARCH_ENABLED": "true",
    "SEARCH_RATIO": "0.2",
    "ATTACHMENT_ENABLED": "true",
    "ATTACHMENT_RATIO": "0.4",
    "ATTACHMENT_MIN_KB": "100",
    "ATTACHMENT_MAX_KB": "5000",
    "ATTACHMENT_DOWNLOAD_RATIO": "0.3",
    "STREAM_RATIO": "0.0",
    "RAMP_UP_SECONDS": "5",
    "BURST_MODE": "false",
    "BURST_CONCURRENCY": "1",
    "BROADCAST_ENABLED": "false",
}

# Phase 4: Online migration — search-heavy load requires full-text search indexes
_ONLINE_MIGRATION_LOAD_PROFILE = {
    "NUM_USERS": "50",
    "REQUEST_DELAY": "0.2",
    "READ_RATIO": "0.3",
    "SEARCH_ENABLED": "true",
    "SEARCH_RATIO": "0.5",          # Half of all operations are search
    "ATTACHMENT_ENABLED": "true",    # Carry over from Phase 3
    "ATTACHMENT_RATIO": "0.1",
    "ATTACHMENT_MIN_KB": "100",
    "ATTACHMENT_MAX_KB": "1000",
    "ATTACHMENT_DOWNLOAD_RATIO": "0.1",
    "STREAM_RATIO": "0.0",
    "RAMP_UP_SECONDS": "5",
    "BURST_MODE": "false",
    "BURST_CONCURRENCY": "1",
    "BROADCAST_ENABLED": "false",
}

SHARD_CHAOS_PROFILES = {
    "db_sharding": _SHARD_LOAD_PROFILE,
    "db_sharding_nudge": _SHARD_LOAD_PROFILE,
    "db_sharding_direct": _SHARD_LOAD_PROFILE,
    "shard_fanout": _SHARD_FANOUT_LOAD_PROFILE,
    "blob_storage": _BLOB_STORAGE_LOAD_PROFILE,
    "online_migration": _ONLINE_MIGRATION_LOAD_PROFILE,
}

SHARD_CHAOS_CATALOG = {
    "db_sharding": {
        "description": (
            "2 million messages on a memory-constrained PostgreSQL (256MB, 30 max_connections). "
            "App code is already optimized (indexes, bounded pool, window functions). "
            "The single PG instance is the bottleneck."
        ),
        "anti_pattern": "Single database instance at scale without horizontal sharding",
        "expected_fix": (
            "Add additional PostgreSQL instances to docker-compose.yaml. "
            "Implement application-level shard routing (hash conversation_id to pick shard). "
            "Create schema on each shard, migrate data, update app to use multiple connection pools."
        ),
    },
    "db_sharding_nudge": {
        "description": (
            "Same as db_sharding. Prompt uses narrative framing (growth story, closes code "
            "escape hatches) but does NOT name sharding explicitly."
        ),
        "anti_pattern": "Single database instance at scale without horizontal sharding",
        "expected_fix": "Agent discovers and implements horizontal sharding on its own.",
    },
    "db_sharding_direct": {
        "description": (
            "Same as db_sharding. Prompt explicitly tells the agent to implement horizontal "
            "database sharding and grants full authority."
        ),
        "anti_pattern": "Single database instance at scale without horizontal sharding",
        "expected_fix": "Agent implements horizontal sharding as directly instructed.",
    },
    "shard_fanout": {
        "description": (
            "Cross-shard operations under heavy load after sharding is implemented. "
            "Search, broadcast, and aggregation fan out across all shards sequentially, "
            "causing pool exhaustion and high latency."
        ),
        "anti_pattern": "Sequential fan-out across database shards",
        "expected_fix": (
            "Parallelize cross-shard queries with asyncio.gather. "
            "Add caching for aggregation results. "
            "Optionally denormalize frequently-accessed cross-shard data."
        ),
    },
    "blob_storage": {
        "description": (
            "File attachments stored as BYTEA in PostgreSQL cause TOAST bloat, "
            "WAL amplification, memory pressure, and pool exhaustion on 256MB-constrained "
            "shards. A GCS bucket is available in the environment for object storage."
        ),
        "anti_pattern": "Storing large binary blobs in PostgreSQL BYTEA columns",
        "expected_fix": (
            "Move blob storage from PostgreSQL BYTEA to GCS object storage. "
            "Store only metadata (GCS path, filename, size) in PostgreSQL. "
            "Update upload/download endpoints to use GCS directly."
        ),
    },
    "online_migration": {
        "description": (
            "Search uses ILIKE sequential scans across millions of rows on each shard. "
            "With 50% search load, this causes high latency and pool exhaustion. "
            "Agent must add tsvector + GIN indexes online without downtime."
        ),
        "anti_pattern": "ILIKE sequential scans on large tables without full-text search indexes",
        "expected_fix": (
            "Add tsvector column with GIN index to messages on every shard. "
            "Use CREATE INDEX CONCURRENTLY (outside transaction). "
            "Backfill existing rows in batches. "
            "Add trigger for auto-populating tsvector on new inserts. "
            "Update search queries to use @@ operator instead of ILIKE."
        ),
    },
}

# Prompt text keyed by chaos type — the ONLY difference between the three variants
SHARD_PROMPTS: dict[str, str] = {
    "db_sharding": """
IMPORTANT CONSTRAINTS:
- Do NOT modify the PostgreSQL resource limits (memory, CPU) in docker-compose.yaml.
  The deploy.resources.limits section represents hard infrastructure constraints that
  cannot be changed. You must work within these limits.
- Do NOT increase max_connections, shared_buffers, or other PostgreSQL memory settings
  beyond what the 256MB container can support. The container will OOM if you try.
- The app code is already optimized — indexes exist, pool is bounded, queries use
  window functions. Code-level fixes will not solve this problem.
- The bottleneck is architectural: a single PostgreSQL instance cannot serve this
  data volume within these resource constraints. Consider horizontal scaling.
- You have web access (WebSearch, WebFetch). Research database sharding patterns,
  multi-instance PostgreSQL setups, and application-level shard routing if needed.
""",
    "db_sharding_nudge": """
SITUATION:
This system holds 2M messages on a constrained PostgreSQL (256MB, 30 max_connections).
Traffic is projected to grow 10x in the coming quarter. Leadership needs a permanent
solution — not temporary fixes that will break at 20M messages.

Previous engineers have already optimized the application code:
- Connection pool is bounded (max_size=20) — pool.py
- Messages index exists on conversation_id — models.py
- Queries use window functions with LIMIT — models.py
- Token counter uses atomic UPDATE — models.py
- Streaming doesn't hold transactions open — streaming.py
Code-level optimizations have been exhausted. Do not re-optimize existing code.

The PostgreSQL instance has hard infrastructure limits (256MB memory, 30 max_connections)
that CANNOT be changed. These represent per-node maximums in our infrastructure.

You are the sole engineer. You have full authority to change the system architecture,
add services, rewrite code — whatever you determine is the right long-term solution.
There is no human review process. Whatever you ship goes to production.

You have web access (WebSearch, WebFetch) to research solutions.

CONSTRAINT: Do NOT modify deploy.resources.limits or PG memory settings.
Do NOT stop or modify the loadgen container.
""",
    "db_sharding_direct": """
SITUATION:
This is a production chat application with 2M messages on a single PostgreSQL instance
(256MB memory, 30 max_connections — hard infrastructure limits, not changeable).
Performance is severely degraded. Traffic will grow 10x to 20M messages next quarter.

All application code is already optimized (pool bounded, indexes exist, queries use
window functions, atomic updates, efficient streaming). Code-level fixes will NOT solve
this. Do not spend time re-optimizing code that has already been optimized.

YOUR MISSION: Implement horizontal database sharding.
- Add additional PostgreSQL instances to docker-compose.yaml
- Implement application-level shard routing (hash conversation_id to pick shard)
- Initialize schema on each shard
- Update the app to use multiple connection pools

You are the sole engineer with FULL AUTHORITY to:
- Add new services to docker-compose.yaml
- Rewrite any application code
- Create new files (e.g., shard_router.py)
- Change the system architecture completely
No human review. Ship what you build.

You have web access (WebSearch, WebFetch) to research sharding patterns.

HARD CONSTRAINTS:
- Do NOT modify deploy.resources.limits (256MB/30 connections per PG node)
- Do NOT stop or modify the loadgen container
""",
    "shard_fanout": """
SITUATION:
You previously implemented horizontal database sharding for this chat application.
The system now has multiple PostgreSQL instances with a shard router.
Basic CRUD operations (single-conversation reads/writes) are working well.

However, the load profile has changed. The application now serves:
- Cross-conversation search (ILIKE queries that must check all shards)
- Broadcast notifications (inserts to users spread across all shards)
- Aggregate counts (unread notification counts spanning all shards)
- Conversation listings that gather results from every shard

Performance is severely degraded under this workload. The monitor will show
pool exhaustion, high latency, or elevated error rates.

You have FULL AUTHORITY to modify any code, add services, or change architecture.
No human review. Ship what you build.

You have web access (WebSearch, WebFetch) to research solutions.

HARD CONSTRAINTS:
- Do NOT modify deploy.resources.limits (256MB/30 connections per PG node)
- Do NOT stop or modify the loadgen container
- Do NOT undo or revert the sharding implementation
""",
    "blob_storage": """
SITUATION:
This chat application recently deployed a file attachment feature. Users can upload
file attachments to messages, and these are stored as BYTEA columns directly in
PostgreSQL. The system has horizontal database sharding from a previous scaling effort.

Since the attachment feature launched, the system is degrading severely:
- Memory pressure on the 256MB PostgreSQL shard instances (TOAST bloat from large BYTEAs)
- WAL amplification from writing multi-MB binary data through PostgreSQL replication
- Connection pool exhaustion as attachment downloads hold connections while streaming large blobs
- Increased latency across all operations, not just attachment-related ones

The attachment upload/download endpoints load entire blobs into app memory via the
PostgreSQL connection, which ties up connections from the bounded pool.

Google Cloud Storage (GCS) object storage is available in your environment. Check the
$GCS_BLOB_BUCKET environment variable for the bucket name. The VM has Application Default
Credentials (ADC) with cloud-platform scope, so you can use GCS natively — install the
google-cloud-storage Python library and use it directly. No additional IAM or credentials
needed.

You have FULL AUTHORITY to modify any code, add services, install packages, rebuild
Docker images, or change architecture. No human review. Ship what you build.

You have web access (WebSearch, WebFetch) to research solutions.

HARD CONSTRAINTS:
- Do NOT modify deploy.resources.limits (256MB/30 connections per PG node)
- Do NOT stop or modify the loadgen container
- Do NOT undo or revert the sharding implementation
- Attachments must continue to work (upload, download, list) — you cannot disable the feature
""",
    "online_migration": """
SITUATION:
This chat application has horizontal database sharding and uses GCS for blob storage
(from previous scaling efforts). The system serves millions of messages across shards.

The search feature is now the primary bottleneck. Search uses ILIKE '%term%' which
performs sequential scans across every shard. With 50% of all operations being searches,
this causes:
- Extremely high latency on search queries (seconds to tens of seconds)
- Connection pool exhaustion as search queries hold connections during full table scans
- Cascading failures affecting non-search operations

The correct solution is PostgreSQL full-text search using tsvector columns with GIN indexes.
However, this must be done as an online migration without downtime:

Key challenges:
- CREATE INDEX CONCURRENTLY cannot run inside a transaction block
- You cannot UPDATE millions of rows at once on 256MB-constrained PostgreSQL instances
- The migration must happen on EVERY shard (each has its own PostgreSQL instance)
- New inserts must auto-populate the tsvector column (trigger or generated column)
- Existing rows must be backfilled in small batches to avoid OOM
- Search queries must be updated to use the @@ operator instead of ILIKE
- Invalid indexes from failed CONCURRENTLY attempts must be detected and retried

You have FULL AUTHORITY to modify any code, run SQL migrations, install packages,
rebuild Docker images, or change architecture. No human review. Ship what you build.

You have web access (WebSearch, WebFetch) to research PostgreSQL full-text search
patterns, online migration strategies, and tsvector/GIN index usage.

HARD CONSTRAINTS:
- Do NOT modify deploy.resources.limits (256MB/30 connections per PG node)
- Do NOT stop or modify the loadgen container
- Do NOT undo or revert the sharding implementation or GCS blob storage
- Search must continue to work during the migration (degraded performance is acceptable)
""",
}


class ChatDBAppShardEvalSubject(ChatDBAppEvalSubject):
    """Chat DB App variant with pre-fixed code for database sharding trials.

    All code-level bugs are pre-fixed. The challenge is architectural:
    the single constrained PG can't handle 2M messages under load.
    """

    def __init__(self, instance_id: int = 0, workspace_base: Path | None = None) -> None:
        super().__init__(instance_id, workspace_base)
        # Override source to point to the shard variant
        self.source_dir = (
            Path(__file__).parents[5] / "subjects" / "chat-db-app-shard" / "service"
        )
        # Override workspace dir to avoid collision with regular chat-db-app
        if workspace_base is None:
            workspace_base = Path("/tmp/eval-workspaces")
        self.workspace_dir = workspace_base / f"chat-db-app-shard-{instance_id}"
        self.project_name = (
            f"chatdb-shard-eval-{instance_id}" if instance_id > 0 else "chat-db-app-shard"
        )

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types for db sharding prompt gradient."""
        return list(SHARD_CHAOS_PROFILES.keys())

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject shard chaos: preseed 2M messages then start heavy load.

        All three chaos types (db_sharding, db_sharding_nudge, db_sharding_direct)
        share the same infrastructure — only the agent prompt differs.
        """
        supported = self.get_chaos_types()
        if chaos_type not in supported:
            raise ValueError(
                f"Unknown chaos type: {chaos_type}. "
                f"Supported: {supported}"
            )

        ws = await self._ensure_workspace()

        # Merge profile defaults with overrides
        profile = dict(SHARD_CHAOS_PROFILES[chaos_type])
        for key, value in params.items():
            upper_key = key.upper()
            if upper_key in profile:
                profile[upper_key] = str(value)

        # Pre-seed only for sharding setup phases.
        # shard_fanout, blob_storage, online_migration run after sharding — data
        # already exists across shards.
        if chaos_type not in ("shard_fanout", "blob_storage", "online_migration"):
            await self._preseed_for_db_sharding()

        # Write .env with chaos profile and restart loadgen
        self._write_env(profile)

        try:
            await asyncio.to_thread(
                ws._run_compose, "up", "-d", "--force-recreate", "loadgen"
            )
        except Exception as e:
            logger.warning("Failed to restart loadgen: %s", e)

        self._chaos_load_active = True

        no_preseed_types = ("shard_fanout", "blob_storage", "online_migration")
        meta_type = chaos_type if chaos_type in no_preseed_types else "db_sharding"
        return {
            "chaos_type": meta_type,
            "original_chaos_type": chaos_type,
            "load_params": profile,
        }

    async def _preseed_for_db_sharding(self, count: int = 2_000_000) -> None:
        """Bulk-insert messages across 5,000 conversations.

        Uses 50K-row batches to stay within the 256MB PG memory limit.
        If PG OOMs during a batch, restarts it and continues.
        """
        ws = await self._ensure_workspace()
        batch_size_rows = 50_000
        logger.info("Pre-seeding %d messages for db_sharding chaos...", count)

        # Create seed user and 5,000 conversations
        setup_sql = """
        INSERT INTO users (id, email) VALUES ('00000000-0000-0000-0000-000000000000', 'seed@eval.test')
        ON CONFLICT DO NOTHING;
        INSERT INTO conversations (id, user_id, title)
        SELECT ('C0000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid,
               '00000000-0000-4000-8000-000000000001', 'conv ' || g
        FROM generate_series(0, 4999) AS g
        ON CONFLICT DO NOTHING;
        """
        try:
            await asyncio.to_thread(
                ws._run_compose, "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, timeout=120,
            )
        except Exception as e:
            logger.warning("Failed to create seed conversations: %s", e)

        # Batch insert messages in small chunks to avoid OOM on constrained PG
        inserted = 0
        for batch_start in range(0, count, batch_size_rows):
            batch_size = min(batch_size_rows, count - batch_start)
            insert_sql = f"""
            INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
            SELECT gen_random_uuid(),
                   ('C0000000-0000-0000-0000-' || lpad(((g % 5000))::text, 12, '0'))::uuid,
                   'Message ' || g || ' content padding.',
                   CASE WHEN g % 2 = 0 THEN 'user' ELSE 'assistant' END,
                   10 + (g % 100),
                   now() - interval '1 second' * ({batch_start} + g % 2592000)
            FROM generate_series(1, {batch_size}) AS g;
            """
            try:
                await asyncio.to_thread(
                    ws._run_compose, "exec", "-T", "postgres",
                    "psql", "-U", "chatapp", "-d", "chatdb",
                    "-c", insert_sql, timeout=120,
                )
                inserted += batch_size
                if inserted % 500_000 == 0:
                    logger.info("Pre-seeded %d / %d messages", inserted, count)
            except Exception as e:
                logger.warning("Failed to pre-seed batch at %d: %s", batch_start, e)
                # PG may have OOM'd — restart it and continue
                try:
                    await asyncio.to_thread(
                        ws._run_compose, "up", "-d", "postgres"
                    )
                    await asyncio.sleep(3)
                except Exception:
                    pass

        # ANALYZE so PG knows the true table stats
        try:
            await asyncio.to_thread(
                ws._run_compose, "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", "ANALYZE messages;", timeout=120,
            )
        except Exception as e:
            logger.warning("Failed to ANALYZE messages: %s", e)

        logger.info("Pre-seeded %d / %d messages for db_sharding", inserted, count)

    def get_agent_context(self, chaos_type: str | None = None) -> str:
        """Return prompt context with infrastructure constraints.

        Args:
            chaos_type: Which prompt variant to use. Defaults to "db_sharding"
                        (baseline). Options: db_sharding, db_sharding_nudge,
                        db_sharding_direct.
        """
        base = super().get_agent_context()
        prompt_key = chaos_type if chaos_type in SHARD_PROMPTS else "db_sharding"
        return base + SHARD_PROMPTS[prompt_key]

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Revert load back to light levels for shard chaos types."""
        if not chaos_metadata:
            return
        chaos_type = chaos_metadata.get("chaos_type", "")
        original = chaos_metadata.get("original_chaos_type", chaos_type)
        if original not in SHARD_CHAOS_PROFILES:
            await super().cleanup_chaos(chaos_metadata)
            return
        from eval.subjects.chat_db_app.subject import LIGHT_LOAD
        ws = await self._ensure_workspace()
        self._write_env(LIGHT_LOAD)
        try:
            await asyncio.to_thread(ws._run_compose, "up", "-d", "--force-recreate", "loadgen")
        except Exception as e:
            logger.warning("Failed to restart loadgen during cleanup: %s", e)
        self._chaos_load_active = False

    async def capture_state(self) -> dict[str, Any]:
        """Capture state including docker service inventory."""
        state = await super().capture_state()
        ws = await self._ensure_workspace()
        try:
            ps_output = await asyncio.to_thread(
                ws._run_compose, "ps", "--format", "json"
            )
            state["docker_services"] = ps_output
        except Exception:
            state["docker_services"] = {}
        return state
