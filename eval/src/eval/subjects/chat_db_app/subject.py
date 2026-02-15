"""Chat DB App evaluation subject implementing EvalSubject protocol.

Uses CodeWorkspace for all Docker operations and git tracking.
The app has intentional bugs that manifest under load — chaos injection
is simply increasing load intensity.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import httpx

from eval.workspace import CodeWorkspace

logger = logging.getLogger(__name__)

# Port allocation for parallel instances
BASE_APP_PORT = 8000
BASE_PG_PORT = 5432
BASE_PROM_PORT = 9090
PORT_INCREMENT = 10000

# Load profiles
LIGHT_LOAD = {
    "NUM_USERS": "3",
    "REQUEST_DELAY": "2.0",
    "STREAM_RATIO": "0.3",
    "RAMP_UP_SECONDS": "10",
    "READ_RATIO": "0.3",
    "BURST_MODE": "false",
    "BURST_CONCURRENCY": "1",
    "SEARCH_ENABLED": "false",
    "SEARCH_RATIO": "0.0",
    "BROADCAST_ENABLED": "false",
    "BROADCAST_INTERVAL": "30.0",
    "BROADCAST_SERIALIZABLE": "false",
    "POLL_ENABLED": "false",
    "POLL_RATIO": "0.0",
    "UNREAD_CHECK_RATIO": "0.0",
    "MARK_READ_RATIO": "0.0",
    "LIST_NOTIFS_RATIO": "0.0",
    "MULTI_USER_COUNT": "1",
}

# Per-defect chaos profiles — each targets a specific app bug
CHAOS_PROFILES: dict[str, dict[str, str]] = {
    # Hammers sequential scans on messages table (no index on conversation_id)
    "missing_index": {
        "NUM_USERS": "15",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.1",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.8",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Overwhelms unbounded connection pool
    "pool_exhaustion": {
        "NUM_USERS": "40",
        "REQUEST_DELAY": "0.2",
        "STREAM_RATIO": "0.2",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.3",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Holds connections in long transactions via streaming responses
    "streaming_txn": {
        "NUM_USERS": "15",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.8",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.3",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Concurrent writes to same row trigger read-modify-write race on counter
    "counter_race": {
        "NUM_USERS": "15",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.3",
        "BURST_MODE": "true",
        "BURST_CONCURRENCY": "10",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Heavy fulltext search load — ILIKE '%term%' sequential scans
    "fulltext_search": {
        "NUM_USERS": "20",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.1",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.2",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "true",
        "SEARCH_RATIO": "0.5",
    },
    # High read volume to overwhelm single PG → needs caching
    "read_scale": {
        "NUM_USERS": "60",
        "REQUEST_DELAY": "0.2",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "10",
        "READ_RATIO": "0.9",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # No LIMIT on get_messages() — 50K rows per read crushes the app
    "unbounded_results": {
        "NUM_USERS": "20",
        "REQUEST_DELAY": "0.3",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.9",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Hot row contention — burst writes on same user row create lock convoy
    "write_contention": {
        "NUM_USERS": "30",
        "REQUEST_DELAY": "0.2",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "3",
        "READ_RATIO": "0.0",
        "BURST_MODE": "true",
        "BURST_CONCURRENCY": "15",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Sustained writes accumulate MVCC dead tuples faster than autovacuum
    "write_amplification": {
        "NUM_USERS": "25",
        "REQUEST_DELAY": "0.3",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.1",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # O(N^2) correlated subquery in get_messages running_total computation
    "correlated_subquery": {
        "NUM_USERS": "15",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.8",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Broadcast notification fanout — synchronous INSERT loop can't keep up
    "notification_fanout": {
        "NUM_USERS": "10",
        "REQUEST_DELAY": "2.0",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "BROADCAST_ENABLED": "true",
        "BROADCAST_INTERVAL": "10",
        "MULTI_USER_COUNT": "1000",
    },
    # Unread count middleware — SELECT COUNT(*) on every request with 500K notifications
    "notification_counter": {
        "NUM_USERS": "25",
        "REQUEST_DELAY": "0.3",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.3",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
    },
    # Poll endpoint holds DB connections for 30s — starves regular requests
    "notification_realtime": {
        "NUM_USERS": "100",
        "REQUEST_DELAY": "2.0",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "POLL_ENABLED": "true",
        "POLL_RATIO": "0.9",
        "MULTI_USER_COUNT": "100",
    },
    # Poll holds transactions open for 30s — blocks autovacuum
    "notification_poll_idle": {
        "NUM_USERS": "30",
        "REQUEST_DELAY": "1.0",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "POLL_ENABLED": "true",
        "POLL_RATIO": "0.5",
        "MULTI_USER_COUNT": "30",
    },
    # Mark-all-read fires N individual UPDATEs with 50K unread per user
    "notification_mark_read": {
        "NUM_USERS": "20",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "MARK_READ_RATIO": "0.3",
        "MULTI_USER_COUNT": "20",
    },
    # N+1 query: list_notifications fires 1 SELECT per notification for conversation title
    "notification_n_plus_one": {
        "NUM_USERS": "20",
        "REQUEST_DELAY": "0.5",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "LIST_NOTIFS_RATIO": "0.7",
        "MULTI_USER_COUNT": "20",
    },
    # Large JSONB payloads — SELECT * transfers 50KB per notification
    "notification_payload": {
        "NUM_USERS": "20",
        "REQUEST_DELAY": "0.3",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "LIST_NOTIFS_RATIO": "0.8",
        "BROADCAST_ENABLED": "true",
        "BROADCAST_INTERVAL": "10",
        "BROADCAST_PAYLOAD_SIZE": "50000",
        "PAGINATE_NOTIFICATIONS": "true",
        "MULTI_USER_COUNT": "20",
    },
    # Notifications accumulate forever — dead tuples from mark-read outpace autovacuum
    "notification_cleanup": {
        "NUM_USERS": "25",
        "REQUEST_DELAY": "0.3",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "BROADCAST_ENABLED": "true",
        "BROADCAST_INTERVAL": "10",
        "MARK_READ_RATIO": "0.2",
        "MULTI_USER_COUNT": "200",
    },
    # Concurrent SERIALIZABLE broadcasts cause serialization failures
    "notification_serialize": {
        "NUM_USERS": "10",
        "REQUEST_DELAY": "2.0",
        "STREAM_RATIO": "0.0",
        "RAMP_UP_SECONDS": "5",
        "READ_RATIO": "0.0",
        "BURST_MODE": "false",
        "BURST_CONCURRENCY": "1",
        "SEARCH_ENABLED": "false",
        "SEARCH_RATIO": "0.0",
        "BROADCAST_ENABLED": "true",
        "BROADCAST_INTERVAL": "3",
        "BROADCAST_SERIALIZABLE": "true",
        "MULTI_USER_COUNT": "500",
    },
}

# Backward compatibility: load_pressure maps to pool_exhaustion
CHAOS_PROFILE_ALIASES: dict[str, str] = {
    "load_pressure": "pool_exhaustion",
}

CHAOS_CATALOG: dict[str, dict[str, str]] = {
    "missing_index": {
        "description": "No index on messages.conversation_id. Sequential scans on every message lookup.",
        "anti_pattern": "Missing index on high-cardinality foreign key column",
        "expected_fix": "CREATE INDEX idx_messages_conversation_id ON messages(conversation_id)",
        "reference": "https://www.postgresql.org/docs/current/indexes.html",
    },
    "pool_exhaustion": {
        "description": "asyncpg pool created with no max_size. Under load, opens unlimited connections until PostgreSQL hits max_connections.",
        "anti_pattern": "Unbounded connection pool",
        "expected_fix": "Set max_size on create_pool() (e.g., max_size=20)",
        "reference": "https://magicstack.github.io/asyncpg/current/api/#connection-pools",
    },
    "streaming_txn": {
        "description": "Streaming response holds a database transaction open for the entire simulated generation time (1-10s). Connections stuck idle-in-transaction.",
        "anti_pattern": "Long-held transactions during I/O-bound operations",
        "expected_fix": "Split into two transactions: one for the user message insert, one for the assistant response after generation completes",
        "reference": "https://www.postgresql.org/docs/current/mvcc.html",
    },
    "counter_race": {
        "description": "Token counter uses read-modify-write (SELECT then UPDATE) instead of atomic increment. Concurrent writes lose increments.",
        "anti_pattern": "Read-modify-write race condition on counters",
        "expected_fix": "Use UPDATE users SET token_usage = token_usage + $1 (atomic increment)",
        "reference": "https://www.postgresql.org/docs/current/transaction-iso.html",
    },
    "fulltext_search": {
        "description": "Search uses ILIKE '%term%' which forces sequential scan on every query. Cannot use B-tree indexes.",
        "anti_pattern": "ILIKE pattern matching for fulltext search",
        "expected_fix": "Use to_tsvector/to_tsquery with GIN index for PostgreSQL full-text search",
        "reference": "https://www.postgresql.org/docs/current/textsearch.html",
    },
    "read_scale": {
        "description": "60+ concurrent users doing 90% reads on conversations with 10K+ messages each. Single PostgreSQL can't serve this read volume.",
        "anti_pattern": "No caching layer for read-heavy workloads",
        "expected_fix": "Add Redis cache-aside pattern: cache message lists, invalidate on write",
        "reference": "https://redis.io/docs/latest/develop/data-types/strings/",
    },
    "unbounded_results": {
        "description": "get_messages() returns ALL messages with no LIMIT clause. Conversations with 50K+ messages return multi-MB responses, exhausting memory and bandwidth.",
        "anti_pattern": "No pagination on unbounded result sets",
        "expected_fix": "Add LIMIT/OFFSET or cursor-based pagination to get_messages()",
        "reference": "https://www.postgresql.org/docs/current/queries-limit.html",
    },
    "write_contention": {
        "description": "Every message insert UPDATEs conversations.message_count and users.token_usage. Under high burst concurrency, all writers contend on the same user row, creating lock convoy.",
        "anti_pattern": "Hot row updates on shared counters under concurrent writes",
        "expected_fix": "Use atomic increments (SET x = x + 1), decouple counting from writes, or batch counter updates asynchronously",
        "reference": "https://www.postgresql.org/docs/current/explicit-locking.html",
    },
    "write_amplification": {
        "description": "PostgreSQL MVCC creates a dead tuple on every UPDATE. The read-modify-write pattern on users.token_usage (1 row, updated on every message) generates dead tuples faster than autovacuum can clean them. Table bloat degrades scan performance.",
        "anti_pattern": "Frequent UPDATEs to hot rows causing MVCC dead tuple accumulation",
        "expected_fix": "Tune autovacuum (lower thresholds, more workers), use atomic increments to reduce update frequency, or batch counter updates",
        "reference": "https://www.postgresql.org/docs/current/routine-vacuuming.html",
    },
    "correlated_subquery": {
        "description": "get_messages() uses a correlated subquery to compute running token total per message. Each row triggers a SUM over all preceding rows — O(N^2) for N messages.",
        "anti_pattern": "Correlated subquery for running aggregates",
        "expected_fix": "Use window function: SUM(token_count) OVER (ORDER BY created_at)",
        "reference": "https://www.postgresql.org/docs/current/tutorial-window.html",
    },
    "notification_fanout": {
        "description": "Broadcast endpoint inserts one notification per user in a synchronous loop. At 1000+ users with broadcasts every 10s, each broadcast takes 30+ seconds, blocking the connection.",
        "anti_pattern": "Synchronous fan-out writes in the request path",
        "expected_fix": "Accept broadcast immediately (202 Accepted), add a Redis queue + background worker service to process broadcasts asynchronously with batch INSERTs",
        "reference": "https://redis.io/docs/latest/develop/interact/pubsub/",
    },
    "notification_counter": {
        "description": "Middleware runs SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND NOT read on every /api/ request. With 500K+ unread notifications, each count takes ~200ms.",
        "anti_pattern": "COUNT(*) on large table in hot path (middleware)",
        "expected_fix": "Maintain a materialized unread counter: add unread_count column to users table maintained by a trigger, or use Redis INCR/DECR",
        "reference": "https://www.postgresql.org/docs/current/sql-createtrigger.html",
    },
    "notification_realtime": {
        "description": "Poll endpoint holds a DB connection for 30 seconds waiting for new notifications. With 90 concurrent pollers, the pool is consumed — regular API requests starve.",
        "anti_pattern": "Database connection held during long-poll",
        "expected_fix": "Replace DB polling with Redis pub/sub. Add Redis to docker-compose.yaml. Publish on broadcast, subscribe with timeout in poll endpoint.",
        "reference": "https://redis.io/docs/latest/develop/interact/pubsub/",
    },
    "notification_poll_idle": {
        "description": "Poll endpoint holds a database TRANSACTION open for 30 seconds. Idle-in-transaction sessions prevent autovacuum and hold MVCC snapshots.",
        "anti_pattern": "Long-held transactions during polling",
        "expected_fix": "Remove the transaction wrapper from poll, or use PostgreSQL LISTEN/NOTIFY instead of polling the DB",
        "reference": "https://www.postgresql.org/docs/current/sql-listen.html",
    },
    "notification_mark_read": {
        "description": "mark_all_read() fires one UPDATE per notification. With 50K+ unread per user, each call fires 50K individual UPDATEs in sequence, taking 30+ seconds.",
        "anti_pattern": "Row-by-row UPDATE instead of batch",
        "expected_fix": "Replace the loop with a single batch statement: UPDATE notifications SET read = true WHERE user_id = $1 AND NOT read",
        "reference": "https://www.postgresql.org/docs/current/sql-update.html",
    },
    "notification_n_plus_one": {
        "description": "list_notifications() fetches each notification's conversation title with a separate SELECT. With 1000 notifications per user, each listing fires 1001 queries.",
        "anti_pattern": "N+1 query pattern for related data",
        "expected_fix": "Rewrite as a single query with LEFT JOIN: SELECT n.*, c.title FROM notifications n LEFT JOIN conversations c ON c.id = (n.payload->>'conversation_id')::uuid",
        "reference": "https://www.postgresql.org/docs/current/queries-table-expressions.html",
    },
    "notification_payload": {
        "description": "Broadcast stores ~50KB JSONB payload per notification. list_notifications does SELECT *, transferring all payload data including TOAST-compressed blobs. Pagination walks all rows. Each page of 50 decompresses 2.5MB of JSONB.",
        "anti_pattern": "SELECT * with large JSONB columns",
        "expected_fix": "Use explicit column list excluding payload: SELECT id, user_id, type, read, created_at. Add separate detail endpoint for individual payloads.",
        "reference": "https://www.postgresql.org/docs/current/datatype-json.html",
    },
    "notification_cleanup": {
        "description": "Notifications accumulate forever. Ongoing broadcasts add rows, mark-read creates dead tuples. Autovacuum can't keep pace with the dead tuple rate, causing table bloat.",
        "anti_pattern": "Unbounded data accumulation without retention policy",
        "expected_fix": "Add retention policy: DELETE notifications WHERE read AND created_at < now() - interval '7 days'. Or add a cron service to docker-compose, or implement table partitioning.",
        "reference": "https://www.postgresql.org/docs/current/ddl-partitioning.html",
    },
    "notification_serialize": {
        "description": "Broadcast uses SERIALIZABLE isolation. Under concurrent broadcasts, PostgreSQL detects serialization conflicts and aborts with error 40001. The app doesn't catch SerializationError, causing 500s.",
        "anti_pattern": "SERIALIZABLE isolation without retry logic",
        "expected_fix": "Catch asyncpg.SerializationError and retry with exponential backoff, or downgrade to READ COMMITTED isolation",
        "reference": "https://www.postgresql.org/docs/current/transaction-iso.html",
    },
}

# Number of messages to pre-seed for missing_index chaos
PRESEED_MESSAGE_COUNT = 500_000


class ChatDBAppEvalSubject:
    """Chat DB App evaluation subject.

    Implements EvalSubject protocol for the naive chat application.
    Uses CodeWorkspace to manage a git-tracked copy of the service
    source that the agent can read, edit, and rebuild.
    """

    def __init__(
        self,
        instance_id: int = 0,
        workspace_base: Path | None = None,
    ) -> None:
        self.instance_id = instance_id

        # Port allocation for parallel isolation
        port_offset = instance_id * PORT_INCREMENT
        self.app_port = BASE_APP_PORT + port_offset
        self.pg_port = BASE_PG_PORT + port_offset
        self.prom_port = BASE_PROM_PORT + port_offset

        # Project name for Docker Compose isolation
        self.project_name = (
            f"chat-db-eval-{instance_id}" if instance_id > 0 else "chat-db-app"
        )

        # Workspace paths
        if workspace_base is None:
            workspace_base = Path("/tmp/eval-workspaces")
        self.workspace_base = workspace_base
        self.workspace_dir = workspace_base / f"chat-db-app-{instance_id}"

        # Source directory (subjects/chat-db-app/service/)
        # __file__ = eval/src/eval/subjects/chat_db_app/subject.py
        # parents[5] = repo root
        self.source_dir = (
            Path(__file__).parents[5]
            / "subjects"
            / "chat-db-app"
            / "service"
        )

        self.workspace: CodeWorkspace | None = None
        self._chaos_load_active = False

    def _write_env(self, profile: dict[str, str]) -> None:
        """Write .env file with port allocation and load profile."""
        env_file = self.workspace_dir / ".env"
        lines = [
            f"PG_HOST_PORT={self.pg_port}",
            f"APP_HOST_PORT={self.app_port}",
            f"PROM_HOST_PORT={self.prom_port}",
        ]
        for key in (
            "NUM_USERS", "REQUEST_DELAY", "STREAM_RATIO", "RAMP_UP_SECONDS",
            "READ_RATIO", "BURST_MODE", "BURST_CONCURRENCY",
            "SEARCH_ENABLED", "SEARCH_RATIO",
            "BROADCAST_ENABLED", "BROADCAST_INTERVAL", "BROADCAST_SERIALIZABLE",
            "BROADCAST_PAYLOAD_SIZE", "PAGINATE_NOTIFICATIONS",
            "POLL_ENABLED", "POLL_RATIO",
            "UNREAD_CHECK_RATIO", "MARK_READ_RATIO", "LIST_NOTIFS_RATIO",
            "MULTI_USER_COUNT",
        ):
            if key in profile:
                lines.append(f"{key}={profile[key]}")
        env_file.write_text("\n".join(lines) + "\n")

    async def _ensure_workspace(self) -> CodeWorkspace:
        """Create workspace if it doesn't exist yet."""
        if self.workspace is not None:
            return self.workspace

        self.workspace = await asyncio.to_thread(
            CodeWorkspace.create_from,
            self.source_dir,
            self.workspace_dir,
            self.project_name,
        )

        # Add .env to .gitignore so it doesn't dirty the workspace
        # (.env changes between light/heavy load across trials)
        gitignore = self.workspace_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".env\n")
            await asyncio.to_thread(self.workspace._run_git, "add", ".gitignore")
            await asyncio.to_thread(
                self.workspace._run_git, "commit", "-m", "add .gitignore"
            )
            # Update initial_commit to include .gitignore so reset() restores
            # to this clean baseline rather than the bare initial commit
            self.workspace.initial_commit = (
                await asyncio.to_thread(self.workspace._run_git, "rev-parse", "HEAD")
            ).strip()

        # Start with light load
        self._write_env(LIGHT_LOAD)

        return self.workspace

    async def reset(self) -> None:
        """Reset to initial code and rebuild all containers."""
        ws = await self._ensure_workspace()

        # Stop running containers
        try:
            await asyncio.to_thread(ws.stop)
        except Exception as e:
            logger.debug("Stop during reset: %s", e)

        # If workspace already existed from a previous trial, restore code
        if ws.initial_commit:
            try:
                # Reset HEAD, index, and working tree to initial state
                await asyncio.to_thread(
                    ws._run_git, "reset", "--hard", ws.initial_commit
                )
                await asyncio.to_thread(ws._run_git, "clean", "-fd")
            except Exception as e:
                logger.debug("Git reset: %s", e)

        # Rewrite .env with light load (reset chaos)
        self._write_env(LIGHT_LOAD)

        self._chaos_load_active = False

        # Build and start everything (loadgen source needed for image build)
        await asyncio.to_thread(ws.build_and_start)

        # Remove loadgen source so the agent can't read or modify it.
        # The image is already built; inject_chaos/cleanup_chaos only
        # --force-recreate the container (no rebuild).
        # Also remove from git index so the deletion doesn't show as dirty.
        # (git reset --hard in the next reset() will restore it for rebuilds.)
        loadgen_dir = self.workspace_dir / "loadgen"
        if loadgen_dir.exists():
            shutil.rmtree(loadgen_dir)
            try:
                await asyncio.to_thread(
                    ws._run_git, "rm", "-r", "--cached", "--quiet", "loadgen"
                )
                await asyncio.to_thread(
                    ws._run_git, "commit", "-m", "remove loadgen from agent workspace"
                )
            except Exception:
                pass

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for the app to respond to /health."""
        start = asyncio.get_running_loop().time()
        url = f"http://localhost:{self.app_port}/health"

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("status") == "healthy":
                            logger.debug("App healthy after %.1fs", asyncio.get_running_loop().time() - start)
                            return True
            except Exception:
                pass
            await asyncio.sleep(2.0)

        logger.warning("Health check timeout after %.0fs", timeout_sec)
        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture app health, metrics, and code workspace state."""
        state: dict[str, Any] = {}

        # App health
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"http://localhost:{self.app_port}/health"
                )
                state["app"] = resp.json()
        except Exception as e:
            state["app"] = {"error": str(e)}

        # PostgreSQL config state
        try:
            from eval.subjects.chat_db_app.pg_state import capture_pg_state_asyncpg

            dsn = f"postgresql://chatapp:chatapp@localhost:{self.pg_port}/chatdb"
            state["db_config"] = await capture_pg_state_asyncpg(dsn)
        except Exception as e:
            state["db_config"] = {"error": str(e)}

        # Code workspace snapshot
        if self.workspace:
            try:
                snapshot = await asyncio.to_thread(self.workspace.snapshot)
                state["code_workspace"] = snapshot
                state["code_diff"] = await asyncio.to_thread(
                    self.workspace.full_diff
                )
            except Exception as e:
                state["code_workspace"] = {"error": str(e)}

        return state

    def _resolve_chaos_type(self, chaos_type: str) -> str:
        """Resolve a chaos type name, following aliases."""
        return CHAOS_PROFILE_ALIASES.get(chaos_type, chaos_type)

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types.

        For chat-db-app, the bugs are already in the code. Each chaos
        type targets a specific defect by shaping load accordingly.
        """
        return list(CHAOS_PROFILES.keys())

    async def _preseed_messages(self, count: int = PRESEED_MESSAGE_COUNT) -> None:
        """Bulk-insert rows into the messages table to make missing-index scans expensive."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d messages for missing_index chaos...", count)

        # Create seed user and conversations to satisfy FK constraints,
        # then bulk-insert messages spread across those conversations.
        setup_sql = (
            "INSERT INTO users (id, email) "
            "VALUES ('00000000-0000-0000-0000-000000000000', 'seed@eval.test') "
            "ON CONFLICT DO NOTHING; "
            "INSERT INTO conversations (id, user_id, title) "
            "SELECT "
            "('00000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            "'00000000-0000-0000-0000-000000000000', "
            "'seed conversation ' || g "
            "FROM generate_series(0, 999) AS g "
            "ON CONFLICT DO NOTHING;"
        )
        insert_sql = f"""
INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
SELECT
    gen_random_uuid(),
    ('00000000-0000-0000-0000-' || lpad(((g % 1000))::text, 12, '0'))::uuid,
    'seed message ' || g,
    'user',
    10,
    now() - interval '1 second' * (g % 3600)
FROM generate_series(1, {count}) AS g;
"""
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, "-c", insert_sql,
            )
            logger.info("Pre-seeded %d messages", count)
        except Exception as e:
            logger.warning("Failed to pre-seed messages: %s", e)

    async def _preseed_for_search(self, count: int = 500_000) -> None:
        """Bulk-insert messages with diverse content for fulltext search chaos."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d messages for fulltext_search chaos...", count)

        # Use the default user so searches hit these rows
        default_user = "00000000-0000-4000-8000-000000000001"

        setup_sql = (
            f"INSERT INTO conversations (id, user_id, title) "
            f"SELECT "
            f"('10000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'{default_user}', "
            f"'search seed ' || g "
            f"FROM generate_series(0, 999) AS g "
            f"ON CONFLICT DO NOTHING;"
        )

        # Templates covering SEARCH_TERMS words for realistic fulltext hits
        templates_sql = """
(ARRAY[
    'What is the capital of France? Paris is the capital and largest city.',
    'Explain quantum computing in simple terms. Quantum bits enable parallel computation.',
    'How do connection pools work in PostgreSQL? A pool maintains persistent connections.',
    'What are the ACID properties? Atomicity, Consistency, Isolation, Durability.',
    'Describe the difference between SQL and NoSQL database systems.',
    'What is a deadlock and how can it be prevented in concurrent systems?',
    'Explain the CAP theorem and its implications for distributed databases.',
    'What is eventual consistency in distributed systems?',
    'How does the Raft consensus algorithm achieve distributed agreement?',
    'What are the benefits of microservices architecture over monoliths?',
    'Explain the observer pattern and its use in event-driven systems.',
    'What is the difference between threads and processes in operating systems?',
    'How does garbage collection work in managed runtime environments?',
    'What is a race condition and how do you prevent it?',
    'Explain connection pool exhaustion and its impact on database performance.',
    'How does Kubernetes orchestrate container deployments at scale?',
    'What is Terraform and how does it manage infrastructure as code?',
    'Explain monitoring and observability in distributed systems.',
    'What is consensus in distributed computing and why does it matter?',
    'Describe the consistency models used in modern distributed databases.'
])[1 + (g % 20)]
"""

        insert_sql = f"""
INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
SELECT
    gen_random_uuid(),
    ('10000000-0000-0000-0000-' || lpad(((g % 1000))::text, 12, '0'))::uuid,
    {templates_sql},
    'user',
    10,
    now() - interval '1 second' * (g % 3600)
FROM generate_series(1, {count}) AS g;
"""
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, "-c", insert_sql,
            )
            logger.info("Pre-seeded %d messages for search", count)
        except Exception as e:
            logger.warning("Failed to pre-seed search messages: %s", e)

    async def _preseed_for_read_scale(self, count: int = 1_000_000) -> None:
        """Bulk-insert messages concentrated in hot conversations for read scaling chaos."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d messages for read_scale chaos...", count)

        # Use the default user so reads hit these rows
        default_user = "00000000-0000-4000-8000-000000000001"

        # 100 hot conversations with 10K messages each
        setup_sql = (
            f"INSERT INTO conversations (id, user_id, title) "
            f"SELECT "
            f"('20000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'{default_user}', "
            f"'hot conversation ' || g "
            f"FROM generate_series(0, 99) AS g "
            f"ON CONFLICT DO NOTHING;"
        )

        insert_sql = f"""
INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
SELECT
    gen_random_uuid(),
    ('20000000-0000-0000-0000-' || lpad(((g % 100))::text, 12, '0'))::uuid,
    'Message number ' || g || ' in a busy conversation thread.',
    'user',
    10,
    now() - interval '1 second' * (g % 7200)
FROM generate_series(1, {count}) AS g;
"""
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, "-c", insert_sql,
            )
            logger.info("Pre-seeded %d messages for read_scale", count)
        except Exception as e:
            logger.warning("Failed to pre-seed read_scale messages: %s", e)

    async def _preseed_for_unbounded_results(self, count: int = 500_000) -> None:
        """Bulk-insert messages into a few hot conversations for unbounded result set chaos."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d messages for unbounded_results chaos...", count)

        # Use the default user
        default_user = "00000000-0000-4000-8000-000000000001"

        # 10 conversations × 50K messages each
        setup_sql = (
            f"INSERT INTO conversations (id, user_id, title) "
            f"SELECT "
            f"('30000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'{default_user}', "
            f"'unbounded conversation ' || g "
            f"FROM generate_series(0, 9) AS g "
            f"ON CONFLICT DO NOTHING;"
        )

        insert_sql = f"""
INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
SELECT
    gen_random_uuid(),
    ('30000000-0000-0000-0000-' || lpad(((g % 10))::text, 12, '0'))::uuid,
    'Message number ' || g || ' in a very large conversation.',
    'user',
    10,
    now() - interval '1 second' * (g % 7200)
FROM generate_series(1, {count}) AS g;
"""
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, "-c", insert_sql,
            )
            logger.info("Pre-seeded %d messages for unbounded_results", count)
        except Exception as e:
            logger.warning("Failed to pre-seed unbounded_results messages: %s", e)

    async def _preseed_for_correlated_subquery(self, count: int = 500_000) -> None:
        """Bulk-insert messages into conversations for correlated subquery chaos."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d messages for correlated_subquery chaos...", count)

        default_user = "00000000-0000-4000-8000-000000000001"

        # 100 conversations × 5K messages each
        setup_sql = (
            f"INSERT INTO conversations (id, user_id, title) "
            f"SELECT "
            f"('40000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'{default_user}', "
            f"'subquery conversation ' || g "
            f"FROM generate_series(0, 99) AS g "
            f"ON CONFLICT DO NOTHING;"
        )

        insert_sql = f"""
INSERT INTO messages (id, conversation_id, content, role, token_count, created_at)
SELECT
    gen_random_uuid(),
    ('40000000-0000-0000-0000-' || lpad(((g % 100))::text, 12, '0'))::uuid,
    'Message number ' || g || ' with token data.',
    'user',
    10 + (g % 50),
    now() - interval '1 second' * (g % 7200)
FROM generate_series(1, {count}) AS g;
"""
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql, "-c", insert_sql,
            )
            logger.info("Pre-seeded %d messages for correlated_subquery", count)
        except Exception as e:
            logger.warning("Failed to pre-seed correlated_subquery messages: %s", e)

    async def _preseed_notification_users(self, count: int) -> None:
        """Create notification users in the database."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d notification users...", count)

        setup_sql = (
            f"INSERT INTO users (id, email) "
            f"SELECT "
            f"('00000000-0000-4000-9000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'notif-user-' || g || '@example.com' "
            f"FROM generate_series(0, {count - 1}) AS g "
            f"ON CONFLICT DO NOTHING;"
        )
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", setup_sql,
            )
            logger.info("Pre-seeded %d notification users", count)
        except Exception as e:
            logger.warning("Failed to pre-seed notification users: %s", e)

    async def _preseed_notifications(
        self, count: int, user_count: int, uuid_prefix: str = "50000000",
        payload_size: str = "'{}'", unread_only: bool = True,
        with_conversations: bool = False,
    ) -> None:
        """Bulk-insert notifications for chaos testing."""
        ws = await self._ensure_workspace()
        logger.info("Pre-seeding %d notifications (prefix=%s)...", count, uuid_prefix)

        # Ensure notification users exist
        await self._preseed_notification_users(user_count)

        # Also ensure default user exists for non-multi-user scenarios
        default_user = "00000000-0000-4000-8000-000000000001"

        read_expr = "false" if unread_only else "(g % 3 = 0)"

        # Optionally create conversations for N+1 chaos type
        conv_setup = ""
        payload_expr = payload_size
        if with_conversations:
            conv_setup = (
                f"INSERT INTO conversations (id, user_id, title) "
                f"SELECT "
                f"('{uuid_prefix}' || '0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
                f"'{default_user}', "
                f"'notif conversation ' || g "
                f"FROM generate_series(0, 999) AS g "
                f"ON CONFLICT DO NOTHING;"
            )
            # Payload with conversation_id reference
            payload_expr = (
                f"json_build_object('conversation_id', "
                f"('{uuid_prefix}' || '0000-0000-0000-' || lpad(((g % 1000))::text, 12, '0')))::text"
            )

        user_expr = (
            f"('00000000-0000-4000-9000-' || lpad(((g % {user_count}))::text, 12, '0'))::uuid"
            if user_count > 1
            else f"'{default_user}'::uuid"
        )

        insert_sql = f"""
INSERT INTO notifications (id, user_id, type, payload, read, created_at)
SELECT
    gen_random_uuid(),
    {user_expr},
    'system',
    {payload_expr}::jsonb,
    {read_expr},
    now() - interval '1 second' * (g % 86400)
FROM generate_series(1, {count}) AS g;
"""
        full_sql = conv_setup + insert_sql if conv_setup else insert_sql
        try:
            await asyncio.to_thread(
                ws._run_compose,
                "exec", "-T", "postgres",
                "psql", "-U", "chatapp", "-d", "chatdb",
                "-c", full_sql,
            )
            logger.info("Pre-seeded %d notifications", count)
        except Exception as e:
            logger.warning("Failed to pre-seed notifications: %s", e)

    async def inject_chaos(
        self, chaos_type: str, **params: Any
    ) -> dict[str, Any]:
        """Inject targeted load to trigger a specific app defect.

        Args:
            chaos_type: One of the CHAOS_PROFILES keys or "load_pressure"
                (backward-compat alias for pool_exhaustion).
            **params: Optional overrides merged into the profile.

        Returns:
            Chaos metadata dict.
        """
        resolved_type = self._resolve_chaos_type(chaos_type)
        if resolved_type not in CHAOS_PROFILES:
            raise ValueError(
                f"Unknown chaos type: {chaos_type}. "
                f"Supported: {self.get_chaos_types()}"
            )

        ws = await self._ensure_workspace()

        # Merge profile defaults with overrides
        profile = dict(CHAOS_PROFILES[resolved_type])
        for key, value in params.items():
            upper_key = key.upper()
            if upper_key in profile:
                profile[upper_key] = str(value)

        # Pre-seed data for chaos types that need it
        if resolved_type == "missing_index":
            await self._preseed_messages()
        elif resolved_type == "fulltext_search":
            await self._preseed_for_search()
        elif resolved_type == "read_scale":
            await self._preseed_for_read_scale()
        elif resolved_type == "unbounded_results":
            await self._preseed_for_unbounded_results()
        elif resolved_type == "correlated_subquery":
            await self._preseed_for_correlated_subquery()
        elif resolved_type == "notification_fanout":
            await self._preseed_notification_users(1000)
        elif resolved_type == "notification_counter":
            await self._preseed_notifications(
                count=500_000, user_count=1, uuid_prefix="50000000"
            )
        elif resolved_type == "notification_realtime":
            await self._preseed_notification_users(100)
        elif resolved_type == "notification_poll_idle":
            await self._preseed_notification_users(30)
        elif resolved_type == "notification_mark_read":
            await self._preseed_notifications(
                count=1_000_000, user_count=20, uuid_prefix="80000000"
            )
        elif resolved_type == "notification_n_plus_one":
            await self._preseed_notifications(
                count=20_000, user_count=20, uuid_prefix="60000000",
                with_conversations=True,
            )
        elif resolved_type == "notification_payload":
            # 50KB JSONB payloads — TOAST decompression dominates even with LIMIT
            payload_expr = (
                "json_build_object("
                "'message', repeat('x', 40000), "
                "'metadata', json_build_object('key', repeat('y', 5000))"
                ")::text"
            )
            await self._preseed_notifications(
                count=50_000, user_count=20, uuid_prefix="70000000",
                payload_size=payload_expr,
            )
        elif resolved_type == "notification_cleanup":
            await self._preseed_notifications(
                count=1_000_000, user_count=200, uuid_prefix="A0000000",
                unread_only=False,
            )
        elif resolved_type == "notification_serialize":
            await self._preseed_notification_users(500)

        # Write .env with chaos profile and restart loadgen
        self._write_env(profile)

        try:
            await asyncio.to_thread(
                ws._run_compose, "up", "-d", "--force-recreate", "loadgen"
            )
        except Exception as e:
            logger.warning("Failed to restart loadgen: %s", e)

        self._chaos_load_active = True

        return {
            "chaos_type": resolved_type,
            "original_chaos_type": chaos_type,
            "load_params": profile,
            "previous_load": LIGHT_LOAD,
        }

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Revert load back to light levels."""
        if not chaos_metadata:
            return

        chaos_type = chaos_metadata.get("chaos_type", "")
        if chaos_type not in CHAOS_PROFILES:
            return

        ws = await self._ensure_workspace()

        # Restore light load
        self._write_env(LIGHT_LOAD)

        try:
            await asyncio.to_thread(
                ws._run_compose, "up", "-d", "--force-recreate", "loadgen"
            )
        except Exception as e:
            logger.warning("Failed to restart loadgen during cleanup: %s", e)

        self._chaos_load_active = False

    def get_agent_context(self) -> str:
        """Return the prompt context for the agent.

        Includes workspace path and the exact compose commands the agent
        should use to rebuild the app after editing code.
        """
        if not self.workspace:
            return ""

        ws = self.workspace
        workspace_path = ws.workspace_dir

        return f"""
Directory layout:
- docker-compose.yaml is at: {workspace_path}/docker-compose.yaml
- Editable source code is at: {workspace_path}/app/
  (main.py, pool.py, models.py, streaming.py, Dockerfile)

After editing code, commit your changes then rebuild:
    git -C {workspace_path} add -A && git -C {workspace_path} commit -m "describe your changes"
    {ws.compose_command} build app
    {ws.compose_command} up -d app

Other useful commands:
    {ws.compose_command} ps
    {ws.compose_command} logs app --tail 50
    git -C {workspace_path} diff
"""
