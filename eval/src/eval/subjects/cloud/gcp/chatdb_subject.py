"""GCP Chat DB App subject implementation."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from eval.subjects.cloud.base import CloudSubjectBase
from eval.subjects.cloud.gcp.cos_helpers import (
    install_compose_plugin,
    configure_artifact_registry,
    upload_directory,
)
from eval.subjects.cloud.gcp.vm import GCPVM

logger = logging.getLogger(__name__)

# COS exec-safe workspace path
WORKSPACE_DIR = "/var/lib/workspace"


class GCPChatDBAppSubject(CloudSubjectBase):
    """Chat DB App running on GCP Compute Engine with local PostgreSQL.

    Each VM runs its own PostgreSQL container via Docker Compose, giving
    full isolation between parallel trials. No shared Cloud SQL.

    The service source is uploaded to a git-tracked workspace on the VM
    so the agent can edit code and rebuild the app container.

    Chaos types:
    - Per-defect types (targeted load profiles):
      - missing_index: High read ratio + pre-seeded data → sequential scans
      - pool_exhaustion: Many concurrent users → unbounded pool exhaustion
      - streaming_txn: High stream ratio → idle-in-transaction
      - counter_race: Burst concurrent writes → read-modify-write race
    - load_pressure: Backward-compat alias for pool_exhaustion
    - debug_code_edit: Ticket injection (handled in worker)
    """

    # Per-defect chaos profiles — same as local subject
    CHAOS_PROFILES: dict[str, dict[str, str]] = {
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

    CLOUD_CHAOS_TYPES = [
        "missing_index", "pool_exhaustion", "streaming_txn", "counter_race",
        "fulltext_search", "read_scale",
        "load_pressure", "debug_code_edit",
    ]

    def __init__(
        self,
        instance_id: int = 0,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-2",
        compose_dir: str = "/tmp/chatdb",
        **kwargs: Any,
    ):
        """Initialize GCP Chat DB App subject.

        Args:
            instance_id: Instance number (used for VM naming)
            project: GCP project ID
            zone: GCP zone
            machine_type: VM machine type
            compose_dir: Directory on VM for compose files
            **kwargs: Ignored (absorbs legacy cloud_sql_ip/cloud_sql_password)
        """
        vm = GCPVM(
            project=project,
            zone=zone,
            machine_type=machine_type,
            name_prefix=f"chatdb-eval-{instance_id}",
        )
        cos_compose_cmd = "docker --config /var/lib/toolbox/docker-config compose"
        super().__init__(
            vm=vm,
            compose_file=compose_dir,
            project_name=f"chatdb-eval-{instance_id}",
            docker_compose_cmd=cos_compose_cmd,
        )
        self.instance_id = instance_id
        self.compose_dir = compose_dir
        self.workspace_dir = WORKSPACE_DIR

        # Image URLs from env
        self.app_image = os.environ.get("CHATDB_APP_IMAGE", "")
        self.loadgen_image = os.environ.get("CHATDB_LOADGEN_IMAGE", "")

        # Local service directory to upload (subjects/chat-db-app/service/)
        # Try Docker image path first, fall back to repo-relative path
        docker_path = Path("/usr/local/lib/subjects/chat-db-app/service")
        repo_path = (
            Path(__file__).parents[6] / "subjects" / "chat-db-app" / "service"
        )
        self._local_service_dir = docker_path if docker_path.exists() else repo_path

        # Cloud compose overlay
        docker_cloud_compose = Path(
            "/usr/local/lib/subjects/chat-db-app/docker-compose.cloud.yaml"
        )
        repo_cloud_compose = (
            Path(__file__).parents[6]
            / "subjects"
            / "chat-db-app"
            / "docker-compose.cloud.yaml"
        )
        self._local_cloud_compose = (
            docker_cloud_compose if docker_cloud_compose.exists() else repo_cloud_compose
        )

        # Chaos loadgen container name
        self._chaos_loadgen_name = f"{self.project_name}-chaos-loadgen"

    def set_trial_id(self, trial_instance_id: int) -> None:
        """Update trial ID for VM reuse across trials.

        Called by the worker when reusing a pooled subject for a new trial.
        With local postgres, compose down -v gives a clean slate so no
        per-trial database name is needed.
        """
        pass

    @property
    def database_url(self) -> str:
        """DATABASE_URL for local postgres on the VM.

        The operator runs with host networking, so localhost:5432 reaches
        the compose postgres service (which exposes port 5432 on the host).
        """
        return "postgresql://chatapp:chatapp@localhost:5432/chatdb"

    @property
    def workspace_volume_mount(self) -> str:
        """Return the Docker volume mount for the workspace directory."""
        return f"{self.workspace_dir}:{self.workspace_dir}"

    @property
    def extra_volume_mounts(self) -> list[str]:
        """Return additional volume mounts for the agent container.

        The agent needs access to:
        - compose_dir: docker-compose.yaml and .env for rebuilding the app
        - toolbox docker-config: COS compose plugin (docker CLI plugin)
        """
        return [
            f"{self.compose_dir}:{self.compose_dir}",
            "/var/lib/toolbox/docker-config:/var/lib/toolbox/docker-config:ro",
        ]

    def get_operator_env(self) -> dict[str, str]:
        """Return extra env vars needed by the operator containers.

        The chat-db-app monitor needs DATABASE_URL and APP_URL to observe
        the app and database. Since the operator runs on the same VM with
        host networking, APP_URL points to localhost.
        """
        return {
            "DATABASE_URL": self.database_url,
            "DB_DSN": self.database_url,
            "APP_URL": "http://localhost:8000",
        }

    def get_agent_context(self) -> str:
        """Return prompt context for the agent.

        Includes workspace path and the exact compose commands the agent
        should use to rebuild the app after editing code.
        """
        compose_cmd = (
            f"cd {self.compose_dir} && "
            f"{self.docker_compose_cmd} -p {self.project_name} --env-file .env"
        )
        return f"""
Directory layout:
- docker-compose.yaml is at: {self.compose_dir}/docker-compose.yaml
- Editable source code is at: {self.workspace_dir}/app/
  (main.py, pool.py, models.py, streaming.py, Dockerfile)
- These are separate directories — compose files are in {self.compose_dir}/, source is in {self.workspace_dir}/

After editing code, commit your changes then rebuild:
    git -C {self.workspace_dir} add -A && git -C {self.workspace_dir} commit -m "describe your changes"
    {compose_cmd} build app
    {compose_cmd} up -d app

Other useful commands:
    {compose_cmd} ps
    {compose_cmd} logs app --tail 50
    git -C {self.workspace_dir} diff
"""

    async def _upload_compose_files(self) -> None:
        """Upload service source, compose files, and configure the VM.

        Uploads the entire service directory to the workspace, overlays
        the cloud compose file, initialises a git repo for code tracking,
        and writes the .env with image URLs.
        """
        await install_compose_plugin(self.vm)

        # Create workspace and compose directories
        await self.vm.run_command(
            f"sudo mkdir -p {self.workspace_dir} && "
            f"sudo chown $(id -u):$(id -g) {self.workspace_dir} && "
            f"mkdir -p {self.compose_dir}"
        )

        # Upload entire service directory to workspace
        await upload_directory(
            self.vm, str(self._local_service_dir), self.workspace_dir
        )

        # Overlay cloud compose as the primary docker-compose.yaml
        await self.vm.upload_file(
            str(self._local_cloud_compose),
            f"{self.compose_dir}/docker-compose.yaml",
        )

        # Init git repo in workspace for code tracking
        await self.vm.run_command(
            f"cd {self.workspace_dir} && "
            "git init && "
            'git config user.email "eval@operator" && '
            'git config user.name "eval" && '
            'git add -A && git commit -m "initial"',
            timeout_sec=30.0,
        )

        await self._write_env_file()

        await configure_artifact_registry(self.vm)

        # Pull loadgen image (postgres:16 is pulled by compose automatically)
        await self.vm.run_command(
            f"docker pull {self.loadgen_image}",
            timeout_sec=300.0,
        )

    async def _write_env_file(self) -> None:
        """Write .env file with image URLs.

        DATABASE_URL is baked into docker-compose.cloud.yaml, so the .env
        only needs the loadgen image reference.
        """
        env_content = f"LOADGEN_IMAGE={self.loadgen_image}\n"
        await self.vm.run_command(
            f"cat > {self.compose_dir}/.env << 'ENVEOF'\n{env_content}ENVEOF"
        )

    async def reset(self) -> None:
        """Reset subject: tear down containers, reset code, start fresh.

        With local postgres, compose down -v destroys the data volume,
        giving a clean database on the next compose up.
        """
        if not self._created:
            await self.setup()

        await self._write_env_file()

        # Compose down — -v removes postgres data volume for clean slate
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} down -v --remove-orphans"
        )

        # Reset workspace code to initial commit (not HEAD — previous trials
        # may have added commits that would persist across VM reuse)
        await self.vm.run_command(
            f"cd {self.workspace_dir} && "
            "git reset --hard $(git rev-list --max-parents=0 HEAD) && "
            "git clean -fd",
            timeout_sec=30.0,
        )

        # Compose up (app builds from workspace source, auto-creates tables on startup)
        exit_code, stdout, stderr = await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} --env-file .env up -d --build --wait",
            timeout_sec=180.0,
        )
        if exit_code != 0:
            logger.error("compose up failed (exit %d): %s", exit_code, stderr.strip())
            raise RuntimeError(
                f"compose up failed (exit {exit_code}): {stderr.strip()[:200]}"
            )

        # Verify postgres is accepting connections before proceeding
        await self._wait_for_postgres()

    async def _wait_for_postgres(self, timeout_sec: float = 30.0) -> None:
        """Wait for postgres to be ready via pg_isready."""
        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            exit_code, _, _ = await self.vm.run_command(
                "docker run --rm --network=host postgres:16 "
                "pg_isready -h localhost -U chatapp -d chatdb",
                timeout_sec=10.0,
            )
            if exit_code == 0:
                return
            await asyncio.sleep(2.0)
        logger.warning("pg_isready did not succeed within %.0fs", timeout_sec)

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for app to be healthy via SSH curl."""
        if not self._created:
            return False

        start = asyncio.get_running_loop().time()
        last_response = "(no response yet)"
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                exit_code, stdout, stderr = await self.vm.run_command(
                    "curl -s -w '\\n%{http_code}' http://localhost:8000/health"
                )
                last_response = f"exit={exit_code} body={stdout.strip()[:200]}"
                if exit_code == 0:
                    try:
                        # curl -w appends HTTP status code on last line
                        lines = stdout.strip().rsplit("\n", 1)
                        body = lines[0] if len(lines) > 1 else stdout.strip()
                        data = json.loads(body)
                        if data.get("status") == "healthy":
                            return True
                    except json.JSONDecodeError:
                        if "healthy" in stdout.lower():
                            return True
            except Exception as e:
                last_response = f"error: {e}"
                logger.debug("Health check error: %s", e)

            await asyncio.sleep(2.0)

        # Log container state for post-mortem
        try:
            _, ps_out, _ = await self.vm.run_command(
                f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} ps -a"
            )
            _, logs_out, _ = await self.vm.run_command(
                f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} logs app --tail 30"
            )
            logger.error(
                "Health check timeout after %.0fs. Last response: %s\nContainers:\n%s\nApp logs:\n%s",
                timeout_sec, last_response, ps_out.strip(), logs_out.strip(),
            )
        except Exception:
            logger.error(
                "Health check timeout after %.0fs. Last response: %s",
                timeout_sec, last_response,
            )

        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture app state via /health and /metrics, plus workspace git state."""
        state: dict[str, Any] = {}
        try:
            # Health endpoint
            exit_code, stdout, _ = await self.vm.run_command(
                "curl -s http://localhost:8000/health"
            )
            if exit_code == 0:
                try:
                    state["health"] = json.loads(stdout)
                except json.JSONDecodeError:
                    state["health_raw"] = stdout

            # Metrics endpoint
            exit_code, stdout, _ = await self.vm.run_command(
                "curl -s http://localhost:8000/metrics"
            )
            if exit_code == 0:
                state["metrics_raw"] = stdout
        except Exception as e:
            state["error"] = str(e)

        # PostgreSQL config state (via psql in docker container)
        try:
            from eval.subjects.chat_db_app.pg_state import capture_pg_state_psql

            state["db_config"] = await capture_pg_state_psql(
                self.vm.run_command, self.database_url
            )
        except Exception as e:
            state["db_config"] = {"error": str(e)}

        # Workspace git snapshot — capture full history of agent changes
        try:
            exit_code, commit_hash, _ = await self.vm.run_command(
                f"git -C {self.workspace_dir} rev-parse HEAD"
            )
            if exit_code == 0:
                _, dirty_output, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} status --porcelain"
                )
                # Uncommitted changes
                _, diff_head, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} diff HEAD"
                )
                # All changes since initial commit (includes committed fixes)
                _, diff_full, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} diff $(git -C {self.workspace_dir} rev-list --max-parents=0 HEAD)..HEAD"
                )
                # Commit log (shows agent's commit messages)
                _, log_output, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} log --oneline --no-decorate"
                )
                state["code_workspace"] = {
                    "commit": commit_hash.strip(),
                    "dirty": bool(dirty_output.strip()),
                    "diff": diff_head.strip(),
                    "diff_full": diff_full.strip(),
                    "log": log_output.strip(),
                }
        except Exception as e:
            state["code_workspace"] = {"error": str(e)}

        return state

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types for cloud chat-db-app."""
        return self.CLOUD_CHAOS_TYPES

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject chaos on the cloud VM."""
        if chaos_type not in self.CLOUD_CHAOS_TYPES:
            raise ValueError(
                f"Unknown chaos type: {chaos_type}. Supported: {self.CLOUD_CHAOS_TYPES}"
            )

        # Per-defect types and load_pressure all route through load injection
        if chaos_type in self.CHAOS_PROFILES:
            resolved_type = chaos_type
            profile = dict(self.CHAOS_PROFILES[resolved_type])
            # Pre-seed data for chaos types that need it
            if resolved_type == "missing_index":
                await self._preseed_messages()
            elif resolved_type == "fulltext_search":
                await self._preseed_for_search()
            elif resolved_type == "read_scale":
                await self._preseed_for_read_scale()
            return await self._inject_load_pressure(
                chaos_type=resolved_type, profile=profile, **params
            )
        elif chaos_type == "load_pressure":
            # Backward compat: load_pressure → pool_exhaustion profile
            profile = dict(self.CHAOS_PROFILES["pool_exhaustion"])
            return await self._inject_load_pressure(
                chaos_type="load_pressure", profile=profile, **params
            )
        elif chaos_type == "debug_code_edit":
            # No system-level chaos — ticket injection happens in the worker
            return {"chaos_type": "debug_code_edit"}

        raise ValueError(f"Unknown chaos type: {chaos_type}")

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up chaos on the cloud VM."""
        chaos_type = chaos_metadata.get("chaos_type")

        try:
            # All load-based chaos types clean up the same way
            if chaos_type in self.CHAOS_PROFILES or chaos_type == "load_pressure":
                container = chaos_metadata.get(
                    "chaos_container", self._chaos_loadgen_name
                )
                await self.vm.run_command(f"docker rm -f {container}")
            elif chaos_type == "debug_code_edit":
                pass  # No system-level chaos to clean up
        except Exception as e:
            logger.debug(f"Cleanup note: {e}")

    # --- Chaos implementations ---

    async def _inject_load_pressure(
        self, chaos_type: str = "load_pressure", profile: dict[str, str] | None = None, **params
    ) -> dict[str, Any]:
        """Run additional heavy loadgen container.

        Args:
            chaos_type: The chaos type name for metadata.
            profile: Base env var profile. Falls back to legacy defaults if None.
            **params: Overrides (lowercase keys like num_users).
        """
        if profile is None:
            # Legacy call path (direct load_pressure without profile)
            profile = {
                "NUM_USERS": "30",
                "REQUEST_DELAY": "0.1",
                "STREAM_RATIO": "0.5",
                "RAMP_UP_SECONDS": "0",
                "READ_RATIO": "0.3",
                "BURST_MODE": "false",
                "BURST_CONCURRENCY": "1",
            }

        # Apply overrides from params
        for key, value in params.items():
            upper_key = key.upper()
            if upper_key in profile:
                profile[upper_key] = str(value)

        # Always use instant ramp for chaos injection
        profile["RAMP_UP_SECONDS"] = "0"

        # Determine network name
        compose_network = f"{self.project_name}_default"

        # Remove any existing chaos loadgen
        await self.vm.run_command(f"docker rm -f {self._chaos_loadgen_name} 2>/dev/null || true")

        # Build -e flags for all profile env vars
        env_flags = " ".join(f"-e {k}={v}" for k, v in profile.items())

        # Run chaos loadgen on compose network
        await self.vm.run_command(
            f"docker run -d --name {self._chaos_loadgen_name} "
            f"--network {compose_network} "
            f"-e APP_URL=http://app:8000 "
            f"{env_flags} "
            f"{self.loadgen_image}",
            timeout_sec=60.0,
        )

        return {
            "chaos_type": chaos_type,
            "chaos_container": self._chaos_loadgen_name,
            "load_params": profile,
        }

    async def _preseed_messages(self, count: int = 200_000) -> None:
        """Bulk-insert rows into messages table to make missing-index scans expensive."""
        logger.info("Pre-seeding %d messages for missing_index chaos...", count)
        # Create a seed user and 1000 fake conversations to satisfy FK constraints,
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
        insert_sql = (
            "INSERT INTO messages (id, conversation_id, content, role, token_count, created_at) "
            "SELECT gen_random_uuid(), "
            "('00000000-0000-0000-0000-' || lpad(((g % 1000))::text, 12, '0'))::uuid, "
            "'seed message ' || g, 'user', 10, "
            "now() - interval '1 second' * (g % 3600) "
            f"FROM generate_series(1, {count}) AS g;"
        )
        # Use compose network so psql can reach postgres by service name
        compose_network = f"{self.project_name}_default"
        psql_cmd = (
            f"docker run --rm --network {compose_network} postgres:16 psql "
            f"'postgresql://chatapp:chatapp@postgres:5432/chatdb' "
            f"-c \"{setup_sql}\" -c \"{insert_sql}\""
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                exit_code, stdout, stderr = await self.vm.run_command(
                    psql_cmd, timeout_sec=300.0
                )
                if exit_code == 0:
                    logger.info("Pre-seeded %d messages", count)
                    return
                output = stdout.strip() or stderr.strip()
                last_err = RuntimeError(
                    f"preseed psql exited {exit_code}: {output[:200]}"
                )
                logger.warning(
                    "Preseed attempt %d/%d failed (exit %d): %s",
                    attempt + 1, 3, exit_code, output[:200],
                )
            except TimeoutError:
                last_err = TimeoutError(f"Preseed timed out after 300s (attempt {attempt + 1})")
                logger.warning("Preseed attempt %d/%d timed out", attempt + 1, 3)
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
        raise last_err  # type: ignore[misc]

    async def _preseed_for_search(self, count: int = 500_000) -> None:
        """Bulk-insert messages with diverse content for fulltext search chaos."""
        logger.info("Pre-seeding %d messages for fulltext_search chaos...", count)

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

        # Use a single-line array for shell safety
        templates_array = (
            "(ARRAY["
            "'What is the capital of France? Paris is the capital and largest city.',"
            "'Explain quantum computing in simple terms. Quantum bits enable parallel computation.',"
            "'How do connection pools work in PostgreSQL? A pool maintains persistent connections.',"
            "'What are the ACID properties? Atomicity, Consistency, Isolation, Durability.',"
            "'Describe the difference between SQL and NoSQL database systems.',"
            "'What is a deadlock and how can it be prevented in concurrent systems?',"
            "'Explain the CAP theorem and its implications for distributed databases.',"
            "'What is eventual consistency in distributed systems?',"
            "'How does the Raft consensus algorithm achieve distributed agreement?',"
            "'What are the benefits of microservices architecture over monoliths?',"
            "'Explain the observer pattern and its use in event-driven systems.',"
            "'What is the difference between threads and processes in operating systems?',"
            "'How does garbage collection work in managed runtime environments?',"
            "'What is a race condition and how do you prevent it?',"
            "'Explain connection pool exhaustion and its impact on database performance.',"
            "'How does Kubernetes orchestrate container deployments at scale?',"
            "'What is Terraform and how does it manage infrastructure as code?',"
            "'Explain monitoring and observability in distributed systems.',"
            "'What is consensus in distributed computing and why does it matter?',"
            "'Describe the consistency models used in modern distributed databases.'"
            "])[1 + (g % 20)]"
        )

        insert_sql = (
            "INSERT INTO messages (id, conversation_id, content, role, token_count, created_at) "
            "SELECT gen_random_uuid(), "
            "('10000000-0000-0000-0000-' || lpad(((g % 1000))::text, 12, '0'))::uuid, "
            f"{templates_array}, 'user', 10, "
            "now() - interval '1 second' * (g % 3600) "
            f"FROM generate_series(1, {count}) AS g;"
        )

        compose_network = f"{self.project_name}_default"
        psql_cmd = (
            f"docker run --rm --network {compose_network} postgres:16 psql "
            f"'postgresql://chatapp:chatapp@postgres:5432/chatdb' "
            f"-c \"{setup_sql}\" -c \"{insert_sql}\""
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                exit_code, stdout, stderr = await self.vm.run_command(
                    psql_cmd, timeout_sec=300.0
                )
                if exit_code == 0:
                    logger.info("Pre-seeded %d messages for search", count)
                    return
                output = stdout.strip() or stderr.strip()
                last_err = RuntimeError(
                    f"search preseed psql exited {exit_code}: {output[:200]}"
                )
                logger.warning(
                    "Search preseed attempt %d/%d failed (exit %d): %s",
                    attempt + 1, 3, exit_code, output[:200],
                )
            except TimeoutError:
                last_err = TimeoutError(f"Search preseed timed out (attempt {attempt + 1})")
                logger.warning("Search preseed attempt %d/%d timed out", attempt + 1, 3)
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
        raise last_err  # type: ignore[misc]

    async def _preseed_for_read_scale(self, count: int = 1_000_000) -> None:
        """Bulk-insert messages concentrated in hot conversations for read scaling chaos."""
        logger.info("Pre-seeding %d messages for read_scale chaos...", count)

        default_user = "00000000-0000-4000-8000-000000000001"

        setup_sql = (
            f"INSERT INTO conversations (id, user_id, title) "
            f"SELECT "
            f"('20000000-0000-0000-0000-' || lpad(g::text, 12, '0'))::uuid, "
            f"'{default_user}', "
            f"'hot conversation ' || g "
            f"FROM generate_series(0, 99) AS g "
            f"ON CONFLICT DO NOTHING;"
        )

        insert_sql = (
            "INSERT INTO messages (id, conversation_id, content, role, token_count, created_at) "
            "SELECT gen_random_uuid(), "
            "('20000000-0000-0000-0000-' || lpad(((g % 100))::text, 12, '0'))::uuid, "
            "'Message number ' || g || ' in a busy conversation thread.', 'user', 10, "
            "now() - interval '1 second' * (g % 7200) "
            f"FROM generate_series(1, {count}) AS g;"
        )

        compose_network = f"{self.project_name}_default"
        psql_cmd = (
            f"docker run --rm --network {compose_network} postgres:16 psql "
            f"'postgresql://chatapp:chatapp@postgres:5432/chatdb' "
            f"-c \"{setup_sql}\" -c \"{insert_sql}\""
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                exit_code, stdout, stderr = await self.vm.run_command(
                    psql_cmd, timeout_sec=300.0
                )
                if exit_code == 0:
                    logger.info("Pre-seeded %d messages for read_scale", count)
                    return
                output = stdout.strip() or stderr.strip()
                last_err = RuntimeError(
                    f"read_scale preseed psql exited {exit_code}: {output[:200]}"
                )
                logger.warning(
                    "Read scale preseed attempt %d/%d failed (exit %d): %s",
                    attempt + 1, 3, exit_code, output[:200],
                )
            except TimeoutError:
                last_err = TimeoutError(f"Read scale preseed timed out (attempt {attempt + 1})")
                logger.warning("Read scale preseed attempt %d/%d timed out", attempt + 1, 3)
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
        raise last_err  # type: ignore[misc]
