"""GCP Chat DB App Shard subject implementation.

Inherits from GCPChatDBAppSubject but uses the shard variant source
(all code bugs pre-fixed) with constrained PostgreSQL (256MB, 30 max_connections).
Supports db_sharding, db_sharding_nudge, db_sharding_direct, blob_storage,
and online_migration chaos types.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from eval.subjects.cloud.gcp.chatdb_subject import GCPChatDBAppSubject

from eval.subjects.chat_db_app_shard.subject import (
    SHARD_CHAOS_PROFILES,
    SHARD_PROMPTS,
)

logger = logging.getLogger(__name__)


class GCPChatDBAppShardSubject(GCPChatDBAppSubject):
    """GCP Chat DB App variant with pre-fixed code for database sharding trials.

    All code-level bugs are pre-fixed. The challenge is architectural:
    a single constrained PG can't handle 2M messages under load.

    Differences from GCPChatDBAppSubject:
    - Uses chat-db-app-shard service source (pre-optimized code)
    - Uses constrained PG cloud compose overlay (256MB, 30 max_connections)
    - Supports db_sharding, db_sharding_nudge, db_sharding_direct chaos types
    - Pre-seeds 2M messages before load injection
    - Agent context varies by chaos type (prompt gradient)
    """

    CLOUD_CHAOS_TYPES = list(SHARD_CHAOS_PROFILES.keys())

    def __init__(
        self,
        instance_id: int = 0,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-2",
        compose_dir: str = "/tmp/chatdb",
        **kwargs: Any,
    ):
        super().__init__(
            instance_id=instance_id,
            project=project,
            zone=zone,
            machine_type=machine_type,
            compose_dir=compose_dir,
            **kwargs,
        )
        # Override VM name prefix to avoid collision with regular chatdb
        self.vm._name_prefix = f"chatdb-shard-eval-{instance_id}"

        # Override source to point to the shard variant
        docker_path = Path("/usr/local/lib/subjects/chat-db-app-shard/service")
        repo_path = (
            Path(__file__).parents[6] / "subjects" / "chat-db-app-shard" / "service"
        )
        self._local_service_dir = docker_path if docker_path.exists() else repo_path

        # Override cloud compose overlay to use constrained PG
        docker_cloud_compose = Path(
            "/usr/local/lib/subjects/chat-db-app-shard/docker-compose.cloud.yaml"
        )
        repo_cloud_compose = (
            Path(__file__).parents[6]
            / "subjects"
            / "chat-db-app-shard"
            / "docker-compose.cloud.yaml"
        )
        self._local_cloud_compose = (
            docker_cloud_compose if docker_cloud_compose.exists() else repo_cloud_compose
        )

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types."""
        return self.CLOUD_CHAOS_TYPES

    def get_operator_env(self) -> dict[str, str]:
        """Return extra env vars including GCS blob bucket for the agent."""
        env = super().get_operator_env()
        env["GCS_BLOB_BUCKET"] = os.environ.get(
            "GCS_BLOB_BUCKET", f"{self.project}-chatdb-eval-blobs"
        )
        return env

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

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject shard chaos: preseed 2M messages then start heavy load.

        All three chaos types (db_sharding, db_sharding_nudge, db_sharding_direct)
        share the same infrastructure — only the agent prompt differs.
        """
        if chaos_type not in self.CLOUD_CHAOS_TYPES:
            raise ValueError(
                f"Unknown chaos type: {chaos_type}. "
                f"Supported: {self.CLOUD_CHAOS_TYPES}"
            )

        # Pre-seed only for sharding setup phases.
        # shard_fanout, blob_storage, online_migration run after sharding — data
        # already exists across shards.
        if chaos_type not in ("shard_fanout", "blob_storage", "online_migration"):
            await self._preseed_for_db_sharding()

        # Apply load profile
        profile = dict(SHARD_CHAOS_PROFILES[chaos_type])
        for key, value in params.items():
            upper_key = key.upper()
            if upper_key in profile:
                profile[upper_key] = str(value)

        # Use a meta chaos_type that the cleanup logic recognizes
        no_preseed_types = ("shard_fanout", "blob_storage", "online_migration")
        meta_type = chaos_type if chaos_type in no_preseed_types else "db_sharding"
        result = await self._inject_load_pressure(
            chaos_type=meta_type, profile=profile, **params
        )
        result["original_chaos_type"] = chaos_type
        return result

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up shard chaos — remove the chaos loadgen container."""
        chaos_type = chaos_metadata.get("chaos_type", "")
        original = chaos_metadata.get("original_chaos_type", chaos_type)
        if original in SHARD_CHAOS_PROFILES or chaos_type in ("db_sharding", "shard_fanout", "blob_storage", "online_migration"):
            try:
                container = chaos_metadata.get("chaos_container", self._chaos_loadgen_name)
                await self.vm.run_command(f"docker rm -f {container}")
            except Exception as e:
                logger.debug(f"Cleanup note: {e}")
            return
        await super().cleanup_chaos(chaos_metadata)

    async def _preseed_for_db_sharding(self, count: int = 2_000_000) -> None:
        """Bulk-insert messages across 5,000 conversations.

        Uses 50K-row batches to stay within the 256MB PG memory limit.
        If PG OOMs during a batch, restarts it and continues.
        """
        batch_size_rows = 50_000
        logger.info("Pre-seeding %d messages for db_sharding chaos...", count)

        compose_network = f"{self.project_name}_default"

        # Create seed user and 5,000 conversations
        setup_sql = (
            "INSERT INTO users (id, email) "
            "VALUES ('00000000-0000-0000-0000-000000000000', 'seed@eval.test') "
            "ON CONFLICT DO NOTHING; "
            "INSERT INTO conversations (id, user_id, title) "
            "SELECT "
            "('C0000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            "'00000000-0000-4000-8000-000000000001', "
            "'conv ' || g "
            "FROM generate_series(0, 4999) AS g "
            "ON CONFLICT DO NOTHING;"
        )

        psql_base = (
            f"docker run --rm --network {compose_network} postgres:16 psql "
            f"'postgresql://chatapp:chatapp@postgres:5432/chatdb'"
        )

        try:
            exit_code, stdout, stderr = await self.vm.run_command(
                f"{psql_base} -c \"{setup_sql}\"",
                timeout_sec=120.0,
            )
            if exit_code != 0:
                logger.warning(
                    "Failed to create seed conversations: %s",
                    (stdout or stderr).strip()[:200],
                )
        except Exception as e:
            logger.warning("Failed to create seed conversations: %s", e)

        # Batch insert messages in small chunks to avoid OOM
        inserted = 0
        for batch_start in range(0, count, batch_size_rows):
            batch_size = min(batch_size_rows, count - batch_start)
            insert_sql = (
                "INSERT INTO messages (id, conversation_id, content, role, token_count, created_at) "
                "SELECT gen_random_uuid(), "
                f"('C0000000-0000-0000-0000-' || lpad(((g % 5000))::text, 12, '0'))::uuid, "
                f"'Message ' || g || ' content padding.', "
                "CASE WHEN g % 2 = 0 THEN 'user' ELSE 'assistant' END, "
                f"10 + (g % 100), "
                f"now() - interval '1 second' * ({batch_start} + g % 2592000) "
                f"FROM generate_series(1, {batch_size}) AS g;"
            )
            try:
                exit_code, stdout, stderr = await self.vm.run_command(
                    f"{psql_base} -c \"{insert_sql}\"",
                    timeout_sec=120.0,
                )
                if exit_code == 0:
                    inserted += batch_size
                    if inserted % 500_000 == 0:
                        logger.info("Pre-seeded %d / %d messages", inserted, count)
                else:
                    logger.warning(
                        "Failed to pre-seed batch at %d: exit %d: %s",
                        batch_start, exit_code, (stdout or stderr).strip()[:200],
                    )
                    # PG may have OOM'd — restart it and continue
                    await self.vm.run_command(
                        f"cd {self.compose_dir} && "
                        f"{self.docker_compose_cmd} -p {self.project_name} "
                        f"up -d postgres",
                        timeout_sec=30.0,
                    )
                    await asyncio.sleep(5)
            except Exception as e:
                logger.warning("Failed to pre-seed batch at %d: %s", batch_start, e)
                try:
                    await self.vm.run_command(
                        f"cd {self.compose_dir} && "
                        f"{self.docker_compose_cmd} -p {self.project_name} "
                        f"up -d postgres",
                        timeout_sec=30.0,
                    )
                    await asyncio.sleep(5)
                except Exception:
                    pass

        # ANALYZE so PG knows the true table stats
        try:
            await self.vm.run_command(
                f"{psql_base} -c \"ANALYZE messages;\"",
                timeout_sec=120.0,
            )
        except Exception as e:
            logger.warning("Failed to ANALYZE messages: %s", e)

        logger.info("Pre-seeded %d / %d messages for db_sharding", inserted, count)

    async def capture_state(self) -> dict[str, Any]:
        """Capture state including docker service inventory."""
        state = await super().capture_state()
        try:
            exit_code, stdout, _ = await self.vm.run_command(
                f"cd {self.compose_dir} && "
                f"{self.docker_compose_cmd} -p {self.project_name} ps --format json"
            )
            if exit_code == 0:
                state["docker_services"] = stdout.strip()
        except Exception:
            pass
        return state
