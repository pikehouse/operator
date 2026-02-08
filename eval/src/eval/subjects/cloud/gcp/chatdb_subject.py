"""GCP Chat DB App subject implementation."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from eval.subjects.cloud.base import CloudSubjectBase, _parse_compose_json
from eval.subjects.cloud.gcp.vm import GCPVM

logger = logging.getLogger(__name__)


class GCPChatDBAppSubject(CloudSubjectBase):
    """Chat DB App running on GCP Compute Engine with AlloyDB.

    The app + loadgen run in Docker on a GCP VM, connecting to a shared
    AlloyDB cluster. Each trial gets an isolated database on AlloyDB.

    Chaos types:
    - load_pressure: Run additional heavy loadgen container
    - db_disconnect: iptables block VM → AlloyDB traffic
    """

    CLOUD_CHAOS_TYPES = ["load_pressure", "db_disconnect"]

    def __init__(
        self,
        instance_id: int = 0,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-2",
        alloydb_ip: str | None = None,
        alloydb_password: str | None = None,
        compose_dir: str = "/tmp/chatdb",
    ):
        """Initialize GCP Chat DB App subject.

        Args:
            instance_id: Instance number (used for VM naming + trial DB)
            project: GCP project ID
            zone: GCP zone
            machine_type: VM machine type
            alloydb_ip: AlloyDB IP (from .env.gcp or env var)
            alloydb_password: AlloyDB password (from .env.gcp or env var)
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

        # AlloyDB connection details (from env vars or constructor)
        self.alloydb_ip = alloydb_ip or os.environ.get("ALLOYDB_IP", "")
        self.alloydb_password = alloydb_password or os.environ.get(
            "ALLOYDB_PASSWORD", ""
        )

        # Per-trial database name for isolation
        self.trial_db_name = f"chatdb_trial_{instance_id}"

        # Image URLs from env
        self.app_image = os.environ.get("APP_IMAGE", "")
        self.loadgen_image = os.environ.get("LOADGEN_IMAGE", "")

        # Local cloud compose file to upload
        self._local_compose = (
            Path(__file__).parents[6]
            / "subjects"
            / "chat-db-app"
            / "docker-compose.cloud.yaml"
        )

        # Chaos loadgen container name
        self._chaos_loadgen_name = f"{self.project_name}-chaos-loadgen"

    @property
    def database_url(self) -> str:
        """Construct DATABASE_URL for this trial's isolated database."""
        return (
            f"postgresql://postgres:{self.alloydb_password}"
            f"@{self.alloydb_ip}:5432/{self.trial_db_name}"
            f"?sslmode=require"
        )

    def get_operator_env(self) -> dict[str, str]:
        """Return extra env vars needed by the operator containers.

        The chat-db-app monitor needs DATABASE_URL and APP_URL to observe
        the app and database. Since the operator runs on the same VM with
        host networking, APP_URL points to localhost.
        """
        return {
            "DATABASE_URL": self.database_url,
            "APP_URL": "http://localhost:8000",
        }

    async def _upload_compose_files(self) -> None:
        """Upload Docker Compose files and configure the VM."""
        # Install Docker Compose plugin on COS
        await self.vm.run_command(
            "curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 "
            "-o /tmp/docker-compose-download && "
            "sudo mkdir -p /var/lib/toolbox/docker-config/cli-plugins && "
            "sudo cp /tmp/docker-compose-download /var/lib/toolbox/docker-config/cli-plugins/docker-compose && "
            "sudo chmod +x /var/lib/toolbox/docker-config/cli-plugins/docker-compose && "
            "rm -f /tmp/docker-compose-download",
            timeout_sec=60.0,
        )

        # Create directory on VM
        await self.vm.run_command(f"mkdir -p {self.compose_dir}")

        # Upload cloud compose file
        await self.vm.upload_file(
            str(self._local_compose),
            f"{self.compose_dir}/docker-compose.yaml",
        )

        # Write .env file on VM with image URLs and database URL
        env_content = (
            f"APP_IMAGE={self.app_image}\n"
            f"LOADGEN_IMAGE={self.loadgen_image}\n"
            f"DATABASE_URL={self.database_url}\n"
        )
        await self.vm.run_command(
            f"cat > {self.compose_dir}/.env << 'ENVEOF'\n{env_content}ENVEOF"
        )

        # Configure Artifact Registry auth
        await self.vm.run_command(
            "docker-credential-gcr configure-docker --registries=us-central1-docker.pkg.dev",
            timeout_sec=30.0,
        )
        # Copy credential config to toolbox docker config
        await self.vm.run_command(
            "sudo cp ~/.docker/config.json /var/lib/toolbox/docker-config/config.json && "
            "sudo chmod 644 /var/lib/toolbox/docker-config/config.json",
            timeout_sec=10.0,
        )

        # Pull images (compose images + postgres:16 for DB admin via psql)
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} --env-file .env pull",
            timeout_sec=300.0,
        )
        await self.vm.run_command("docker pull postgres:16", timeout_sec=120.0)

    async def reset(self) -> None:
        """Reset subject: tear down containers, recreate trial database, start fresh."""
        if not self._created:
            await self.setup()

        # Compose down
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} down -v --remove-orphans"
        )

        # Drop and recreate trial database on AlloyDB
        # Use a temporary postgres container to run psql against AlloyDB
        psql_cmd = (
            f"docker run --rm postgres:16 psql "
            f"'postgresql://postgres:{self.alloydb_password}@{self.alloydb_ip}:5432/postgres?sslmode=require'"
        )
        await self.vm.run_command(
            f'{psql_cmd} -c "DROP DATABASE IF EXISTS {self.trial_db_name};"',
            timeout_sec=60.0,
        )
        await self.vm.run_command(
            f'{psql_cmd} -c "CREATE DATABASE {self.trial_db_name};"',
            timeout_sec=60.0,
        )

        # Compose up (app auto-creates tables on startup)
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} --env-file .env up -d --wait",
            timeout_sec=120.0,
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
        """Capture app state via /health and /metrics endpoints."""
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
                alloydb_ip = chaos_metadata.get("alloydb_ip", self.alloydb_ip)
                await self.vm.run_command(
                    f"sudo iptables -D OUTPUT -d {alloydb_ip} -p tcp --dport 5432 -j DROP"
                )
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
        """Block VM traffic to AlloyDB using iptables.

        Simulates a network partition between the app and the database.
        """
        await self.vm.run_command(
            f"sudo iptables -I OUTPUT -d {self.alloydb_ip} -p tcp --dport 5432 -j DROP"
        )

        return {
            "chaos_type": "db_disconnect",
            "alloydb_ip": self.alloydb_ip,
        }
