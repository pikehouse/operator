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
    """Chat DB App running on GCP Compute Engine with Cloud SQL.

    The app + loadgen run in Docker on a GCP VM, connecting to a shared
    Cloud SQL instance. Each trial gets an isolated database on Cloud SQL.

    The service source is uploaded to a git-tracked workspace on the VM
    so the agent can edit code and rebuild the app container.

    Chaos types:
    - load_pressure: Run additional heavy loadgen container
    - db_disconnect: iptables block VM → Cloud SQL traffic
    """

    CLOUD_CHAOS_TYPES = ["load_pressure", "db_disconnect", "debug_code_edit"]

    def __init__(
        self,
        instance_id: int = 0,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-2",
        cloud_sql_ip: str | None = None,
        cloud_sql_password: str | None = None,
        compose_dir: str = "/tmp/chatdb",
    ):
        """Initialize GCP Chat DB App subject.

        Args:
            instance_id: Instance number (used for VM naming + trial DB)
            project: GCP project ID
            zone: GCP zone
            machine_type: VM machine type
            cloud_sql_ip: Cloud SQL IP (from .env.gcp or env var)
            cloud_sql_password: Cloud SQL password (from .env.gcp or env var)
            compose_dir: Directory on VM for compose files
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

        # Cloud SQL connection details (from env vars or constructor)
        self.cloud_sql_ip = cloud_sql_ip or os.environ.get("CHATDB_CLOUD_SQL_IP", "")
        self.cloud_sql_password = cloud_sql_password or os.environ.get(
            "CHATDB_CLOUD_SQL_PASSWORD", ""
        )

        # Per-trial database name for isolation
        self.trial_db_name = f"chatdb_trial_{instance_id}"

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

    @property
    def database_url(self) -> str:
        """Construct DATABASE_URL for this trial's isolated database."""
        return (
            f"postgresql://chatapp:{self.cloud_sql_password}"
            f"@{self.cloud_sql_ip}:5432/{self.trial_db_name}"
        )

    @property
    def workspace_volume_mount(self) -> str:
        """Return the Docker volume mount for the workspace directory."""
        return f"{self.workspace_dir}:{self.workspace_dir}"

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

Rebuild after editing code:
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
        and writes the .env with Cloud SQL connection details.
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
            "git init && git add -A && "
            'git -c user.email="eval@operator" -c user.name="eval" '
            'commit -m "initial"',
            timeout_sec=30.0,
        )

        # Write .env file with Cloud SQL connection and image URLs
        env_content = (
            f"LOADGEN_IMAGE={self.loadgen_image}\n"
            f"DATABASE_URL={self.database_url}\n"
        )
        await self.vm.run_command(
            f"cat > {self.compose_dir}/.env << 'ENVEOF'\n{env_content}ENVEOF"
        )

        await configure_artifact_registry(self.vm)

        # Pull loadgen image + postgres:16 for DB admin via psql
        await self.vm.run_command(
            f"docker pull {self.loadgen_image}",
            timeout_sec=300.0,
        )
        await self.vm.run_command("docker pull postgres:16", timeout_sec=120.0)

    async def reset(self) -> None:
        """Reset subject: tear down containers, reset code, recreate trial database, start fresh."""
        if not self._created:
            await self.setup()

        # Compose down
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} down -v --remove-orphans"
        )

        # Reset workspace code to initial state
        await self.vm.run_command(
            f"cd {self.workspace_dir} && git reset --hard HEAD && git clean -fd",
            timeout_sec=30.0,
        )

        # Drop and recreate trial database on Cloud SQL
        # Use a temporary postgres container to run psql against Cloud SQL
        psql_cmd = (
            f"docker run --rm postgres:16 psql "
            f"'postgresql://chatapp:{self.cloud_sql_password}@{self.cloud_sql_ip}:5432/postgres'"
        )
        await self.vm.run_command(
            f'{psql_cmd} -c "DROP DATABASE IF EXISTS {self.trial_db_name};"',
            timeout_sec=60.0,
        )
        await self.vm.run_command(
            f'{psql_cmd} -c "CREATE DATABASE {self.trial_db_name};"',
            timeout_sec=60.0,
        )

        # Compose up (app builds from workspace source, auto-creates tables on startup)
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} --env-file .env up -d --build --wait",
            timeout_sec=180.0,
        )

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for app to be healthy via SSH curl."""
        if not self._created:
            return False

        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                exit_code, stdout, _ = await self.vm.run_command(
                    "curl -s http://localhost:8000/health"
                )
                if exit_code == 0:
                    try:
                        data = json.loads(stdout)
                        if data.get("status") == "healthy":
                            return True
                    except json.JSONDecodeError:
                        # Non-JSON 200 response is also OK
                        if "healthy" in stdout.lower():
                            return True
            except Exception as e:
                logger.debug(f"Health check error: {e}")

            await asyncio.sleep(2.0)

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

        # Workspace git snapshot
        try:
            exit_code, commit_hash, _ = await self.vm.run_command(
                f"git -C {self.workspace_dir} rev-parse HEAD"
            )
            if exit_code == 0:
                _, dirty_output, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} status --porcelain"
                )
                _, diff_output, _ = await self.vm.run_command(
                    f"git -C {self.workspace_dir} diff HEAD"
                )
                state["code_workspace"] = {
                    "commit": commit_hash.strip(),
                    "dirty": bool(dirty_output.strip()),
                    "diff": diff_output.strip(),
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

        if chaos_type == "load_pressure":
            return await self._inject_load_pressure(**params)
        elif chaos_type == "db_disconnect":
            return await self._inject_db_disconnect()
        elif chaos_type == "debug_code_edit":
            # No system-level chaos — ticket injection happens in the worker
            return {"chaos_type": "debug_code_edit"}

        raise ValueError(f"Unknown chaos type: {chaos_type}")

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up chaos on the cloud VM."""
        chaos_type = chaos_metadata.get("chaos_type")

        try:
            if chaos_type == "load_pressure":
                container = chaos_metadata.get(
                    "chaos_container", self._chaos_loadgen_name
                )
                await self.vm.run_command(f"docker rm -f {container}")
            elif chaos_type == "db_disconnect":
                cloud_sql_ip = chaos_metadata.get("cloud_sql_ip", self.cloud_sql_ip)
                await self.vm.run_command(
                    f"sudo iptables -D OUTPUT -d {cloud_sql_ip} -p tcp --dport 5432 -j DROP"
                )
            elif chaos_type == "debug_code_edit":
                pass  # No system-level chaos to clean up
        except Exception as e:
            logger.debug(f"Cleanup note: {e}")

    # --- Chaos implementations ---

    async def _inject_load_pressure(self, **params) -> dict[str, Any]:
        """Run additional heavy loadgen container."""
        num_users = params.get("num_users", 30)
        request_delay = params.get("request_delay", 0.1)
        stream_ratio = params.get("stream_ratio", 0.5)

        # Get compose network name
        exit_code, stdout, _ = await self.vm.run_command(
            f"{self.docker_compose_cmd} -p {self.project_name} ps --format json"
        )

        # Determine network name
        compose_network = f"{self.project_name}_default"

        # Remove any existing chaos loadgen
        await self.vm.run_command(f"docker rm -f {self._chaos_loadgen_name} 2>/dev/null || true")

        # Run chaos loadgen on compose network
        await self.vm.run_command(
            f"docker run -d --name {self._chaos_loadgen_name} "
            f"--network {compose_network} "
            f"-e APP_URL=http://app:8000 "
            f"-e NUM_USERS={num_users} "
            f"-e REQUEST_DELAY={request_delay} "
            f"-e STREAM_RATIO={stream_ratio} "
            f"-e RAMP_UP_SECONDS=0 "
            f"{self.loadgen_image}",
            timeout_sec=60.0,
        )

        return {
            "chaos_type": "load_pressure",
            "chaos_container": self._chaos_loadgen_name,
            "num_users": num_users,
            "request_delay": request_delay,
            "stream_ratio": stream_ratio,
        }

    async def _inject_db_disconnect(self) -> dict[str, Any]:
        """Block VM traffic to Cloud SQL using iptables.

        Simulates a network partition between the app and the database.
        """
        await self.vm.run_command(
            f"sudo iptables -I OUTPUT -d {self.cloud_sql_ip} -p tcp --dport 5432 -j DROP"
        )

        return {
            "chaos_type": "db_disconnect",
            "cloud_sql_ip": self.cloud_sql_ip,
        }
