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
}

# Backward compatibility: load_pressure maps to pool_exhaustion
CHAOS_PROFILE_ALIASES: dict[str, str] = {
    "load_pressure": "pool_exhaustion",
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
        ):
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
