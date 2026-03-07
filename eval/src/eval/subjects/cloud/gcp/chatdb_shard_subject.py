"""GCP Chat DB App Shard subject implementation.

Inherits from GCPChatDBAppSubject but uses the shard variant source
(all code bugs pre-fixed) with constrained PostgreSQL (256MB, 30 max_connections).
Supports db_sharding, db_sharding_nudge, db_sharding_direct, blob_storage,
and online_migration chaos types.
"""

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
        project = self.vm.project or "operator-486214"
        env["GCS_BLOB_BUCKET"] = os.environ.get(
            "GCS_BLOB_BUCKET", f"{project}-chatdb-eval-blobs"
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
        if original in SHARD_CHAOS_PROFILES:
            try:
                container = chaos_metadata.get("chaos_container", self._chaos_loadgen_name)
                await self.vm.run_command(f"docker rm -f {container}")
            except Exception as e:
                logger.debug(f"Cleanup note: {e}")
            return
        await super().cleanup_chaos(chaos_metadata)

    async def _preseed_for_db_sharding(self, count: int = 2_000_000) -> None:
        """Bulk-insert messages across 5,000 conversations.

        Runs the entire seeding loop on the VM in a single SSH session
        to avoid per-batch IAP tunnel overhead. Uses 50K-row batches
        to stay within the 256MB PG memory limit.
        """
        batch_size_rows = 10_000
        num_batches = (count + batch_size_rows - 1) // batch_size_rows
        logger.info(
            "Pre-seeding %d messages (%d batches) for db_sharding chaos...",
            count, num_batches,
        )

        compose_network = f"{self.project_name}_default"
        psql_cmd = (
            f"docker run --rm --network {compose_network} postgres:16 psql "
            f"'postgresql://chatapp:chatapp@postgres:5432/chatdb'"
        )

        # Build a shell script that runs entirely on the VM:
        # 1. Create seed user + conversations
        # 2. Loop through batches, restarting PG on failure
        # 3. ANALYZE at the end
        script = f"""#!/bin/bash
set -o pipefail
exec 2>&1

PSQL="{psql_cmd}"
COMPOSE_DIR="{self.compose_dir}"
COMPOSE_CMD="{self.docker_compose_cmd}"
PROJECT="{self.project_name}"
BATCH_SIZE={batch_size_rows}
TOTAL={count}

# Step 1: Create seed user and conversations
$PSQL -c "INSERT INTO users (id, email) VALUES ('00000000-0000-0000-0000-000000000000', 'seed@eval.test') ON CONFLICT DO NOTHING; INSERT INTO conversations (id, user_id, title) SELECT ('C0000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, '00000000-0000-4000-8000-000000000001', 'conv ' || g FROM generate_series(0, 4999) AS g ON CONFLICT DO NOTHING;"
if [ $? -ne 0 ]; then
    echo "WARN: Failed to create seed conversations"
fi

# Step 2: Batch insert messages
INSERTED=0
BATCH_START=0
while [ $BATCH_START -lt $TOTAL ]; do
    REMAINING=$((TOTAL - BATCH_START))
    BS=$BATCH_SIZE
    if [ $REMAINING -lt $BS ]; then BS=$REMAINING; fi

    $PSQL -c "INSERT INTO messages (id, conversation_id, content, role, token_count, created_at) SELECT gen_random_uuid(), ('C0000000-0000-0000-0000-' || lpad(((g % 5000))::text, 12, '0'))::uuid, 'Message ' || g || ' content padding.', CASE WHEN g % 2 = 0 THEN 'user' ELSE 'assistant' END, 10 + (g % 100), now() - interval '1 second' * ($BATCH_START + g % 2592000) FROM generate_series(1, $BS) AS g;"
    if [ $? -eq 0 ]; then
        INSERTED=$((INSERTED + BS))
        if [ $((INSERTED % 500000)) -eq 0 ]; then
            echo "PROGRESS: $INSERTED / $TOTAL messages"
        fi
    else
        echo "WARN: Failed batch at $BATCH_START (exit $?), restarting postgres..."
        cd $COMPOSE_DIR && $COMPOSE_CMD -p $PROJECT up -d postgres 2>&1 || echo "WARN: compose restart failed"
        sleep 5
    fi
    BATCH_START=$((BATCH_START + BATCH_SIZE))
done

# Step 3: ANALYZE
$PSQL -c "ANALYZE messages;"
echo "DONE: $INSERTED / $TOTAL messages inserted"
"""

        # Write script to VM then execute — avoids quoting issues with
        # nested quotes going through SSH.
        remote_script = "/tmp/preseed.sh"
        try:
            await self.vm.run_command(
                f"cat > {remote_script} << 'PRESEED_EOF'\n{script}\nPRESEED_EOF",
                timeout_sec=30.0,
            )
            await self.vm.run_command(f"chmod +x {remote_script}", timeout_sec=10.0)
            exit_code, stdout, stderr = await self.vm.run_command(
                f"bash {remote_script}",
                timeout_sec=1200.0,  # 20 min for full seeding
            )
            output = stdout or stderr or ""
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS:") or line.startswith("DONE:"):
                    logger.info("Pre-seed: %s", line)
                elif line.startswith("WARN:") or line.startswith("ERROR"):
                    logger.warning("Pre-seed: %s", line)

            if exit_code != 0:
                logger.warning(
                    "Pre-seed script exited %d, last 1000 chars: %s",
                    exit_code, output[-1000:],
                )
        except Exception as e:
            logger.warning("Pre-seed script failed: %s", e)

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
