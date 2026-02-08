"""Chat DB App evaluation subject implementing EvalSubject protocol."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx
from python_on_whales import DockerClient

logger = logging.getLogger(__name__)


# Port allocation for parallel instances
# Instance 0: standard ports
# Instance N: base + N*10000
BASE_APP_PORT = 8000
BASE_PG_PORT = 5432
BASE_PROM_PORT = 9090
PORT_INCREMENT = 10000

# Network name for the compose project (used by chaos loadgen)
CHAOS_LOADGEN_CONTAINER = "chatdb-chaos-loadgen"


class ChatDBAppEvalSubject:
    """Chat DB App evaluation subject.

    Implements EvalSubject protocol for the chat-db-app (FastAPI + PostgreSQL)
    managed via Docker Compose.

    Supports parallel instances via instance_id parameter, which:
    - Sets Docker Compose project name for container/volume isolation
    - Allocates unique host ports (instance N uses base_port + N*10000)
    """

    def __init__(self, compose_file: Path | None = None, instance_id: int = 0, **kwargs):
        """Initialize Chat DB App eval subject.

        Args:
            compose_file: Path to docker-compose.yaml. Defaults to
                subjects/chat-db-app/service/docker-compose.yaml.
            instance_id: Instance number for parallel execution (0, 1, 2, ...).
        """
        if compose_file is None:
            compose_file = (
                Path(__file__).parents[5]
                / "subjects"
                / "chat-db-app"
                / "service"
                / "docker-compose.yaml"
            )

        self.compose_file = compose_file
        self.instance_id = instance_id

        # Calculate ports for this instance
        port_offset = instance_id * PORT_INCREMENT
        self.app_port = BASE_APP_PORT + port_offset
        self.pg_port = BASE_PG_PORT + port_offset
        self.prom_port = BASE_PROM_PORT + port_offset

        # Project name for Docker Compose isolation
        self.project_name = (
            f"chatdb-eval-{instance_id}" if instance_id > 0 else "chat-db-app"
        )

        # Environment variables for compose file port substitution
        self._compose_env = {
            "APP_HOST_PORT": str(self.app_port),
            "PG_HOST_PORT": str(self.pg_port),
            "PROM_HOST_PORT": str(self.prom_port),
        }

        # Create env file in compose directory for this instance
        self._env_file = compose_file.parent / f".env.instance-{instance_id}"
        with open(self._env_file, "w") as f:
            for key, value in self._compose_env.items():
                f.write(f"{key}={value}\n")

        # Create Docker client with project name and env file
        self.docker = DockerClient(
            compose_files=[compose_file],
            compose_project_name=self.project_name,
            compose_env_files=[self._env_file],
        )

        # App endpoint (host port)
        self.app_endpoint = f"http://localhost:{self.app_port}"

        # Chaos loadgen container name (unique per instance)
        self._chaos_loadgen_name = f"{self.project_name}-chaos-loadgen"

    async def reset(self) -> None:
        """Reset chat-db-app via docker-compose down/up with volume wipe."""
        await asyncio.to_thread(
            self.docker.compose.down,
            volumes=True,
            remove_orphans=True,
        )

        await asyncio.to_thread(
            self.docker.compose.up,
            detach=True,
            wait=True,
        )

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for app to be healthy by polling /health endpoint."""
        start = asyncio.get_running_loop().time()

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{self.app_endpoint}/health")
                    if resp.status_code == 200:
                        logger.debug("App healthy")
                        return True
            except Exception as e:
                logger.debug(f"Health check error: {e}")

            await asyncio.sleep(2.0)

        logger.warning(f"Health check timeout after {timeout_sec}s")
        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture app state via /health and /metrics endpoints."""
        state: dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Health endpoint
                health_resp = await client.get(f"{self.app_endpoint}/health")
                if health_resp.status_code == 200:
                    state["health"] = health_resp.json()

                # Metrics endpoint (Prometheus text format)
                metrics_resp = await client.get(f"{self.app_endpoint}/metrics")
                if metrics_resp.status_code == 200:
                    state["metrics_raw"] = metrics_resp.text
        except Exception as e:
            state["error"] = str(e)

        return state

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types for local chat-db-app.

        - load_pressure: Run additional heavy loadgen
        - db_kill: Kill the postgres container
        """
        return ["load_pressure", "db_kill"]

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject specified chaos type.

        Args:
            chaos_type: One of get_chaos_types() values
            **params: Type-specific parameters

        Returns:
            Chaos metadata dict

        Raises:
            ValueError: If chaos_type not supported
        """
        if chaos_type == "load_pressure":
            return await self._inject_load_pressure(**params)
        elif chaos_type == "db_kill":
            return await self._inject_db_kill()

        raise ValueError(
            f"Unknown chaos type: {chaos_type}. Supported: {self.get_chaos_types()}"
        )

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up/revert chaos injection."""
        chaos_type = chaos_metadata.get("chaos_type")

        try:
            if chaos_type == "load_pressure":
                container_name = chaos_metadata.get(
                    "chaos_container", self._chaos_loadgen_name
                )
                try:
                    await asyncio.to_thread(
                        self.docker.remove, container_name, force=True
                    )
                except Exception as e:
                    logger.debug(f"Cleanup load_pressure: {e}")

            elif chaos_type == "db_kill":
                # Restore restart policy and start postgres
                target = chaos_metadata.get("target_container")
                if target:
                    restart_policy = chaos_metadata.get(
                        "original_restart_policy", "on-failure"
                    )
                    try:
                        await asyncio.to_thread(
                            self.docker.container.update,
                            target,
                            restart=restart_policy,
                        )
                    except Exception:
                        pass
                    try:
                        await asyncio.to_thread(self.docker.start, target)
                    except Exception as e:
                        logger.debug(f"Failed to start {target}: {e}")

            else:
                logger.warning(f"Unknown chaos type for cleanup: {chaos_type}")

        except Exception as e:
            logger.warning(f"Failed to cleanup chaos {chaos_type}: {e}")

    # --- Chaos injection implementations ---

    async def _inject_load_pressure(self, **params) -> dict[str, Any]:
        """Run an additional loadgen container with heavy load settings.

        This creates pressure on the app's connection pool and increases
        latency, triggering pool_exhaustion and high_latency violations.
        """
        num_users = params.get("num_users", 30)
        request_delay = params.get("request_delay", 0.1)
        stream_ratio = params.get("stream_ratio", 0.5)

        # Get the compose network name
        networks = await asyncio.to_thread(self.docker.network.list)
        compose_network = None
        for net in networks:
            if self.project_name in net.name and "default" in net.name:
                compose_network = net.name
                break

        if not compose_network:
            # Fallback: construct expected network name
            compose_network = f"{self.project_name}_default"

        # Get the loadgen image from existing compose service
        containers = await asyncio.to_thread(self.docker.compose.ps)
        loadgen_image = None
        for c in containers:
            if "loadgen" in c.name.lower():
                loadgen_image = c.config.image
                break

        if not loadgen_image:
            raise RuntimeError("Could not find loadgen container image")

        # Remove any existing chaos loadgen
        try:
            await asyncio.to_thread(
                self.docker.remove, self._chaos_loadgen_name, force=True
            )
        except Exception:
            pass

        # Run chaos loadgen on the same network
        await asyncio.to_thread(
            self.docker.run,
            loadgen_image,
            name=self._chaos_loadgen_name,
            detach=True,
            networks=[compose_network],
            envs={
                "APP_URL": "http://app:8000",
                "NUM_USERS": str(num_users),
                "REQUEST_DELAY": str(request_delay),
                "STREAM_RATIO": str(stream_ratio),
                "RAMP_UP_SECONDS": "0",
            },
        )

        return {
            "chaos_type": "load_pressure",
            "chaos_container": self._chaos_loadgen_name,
            "num_users": num_users,
            "request_delay": request_delay,
            "stream_ratio": stream_ratio,
        }

    async def _inject_db_kill(self) -> dict[str, Any]:
        """Kill the postgres container.

        Disables restart policy first so the container stays dead
        for the monitor to detect.
        """
        containers = await asyncio.to_thread(self.docker.compose.ps)
        pg_container = None
        for c in containers:
            # Filter by service name pattern
            if "postgres" in c.name.lower():
                pg_container = c.name
                break

        if not pg_container:
            raise RuntimeError("No postgres container found")

        # Get original restart policy before disabling
        inspect_data = await asyncio.to_thread(
            self.docker.container.inspect, pg_container
        )
        original_restart = inspect_data.host_config.restart_policy.name

        # Disable restart policy so container stays dead after kill
        await asyncio.to_thread(
            self.docker.container.update, pg_container, restart="no"
        )

        # Kill with SIGKILL
        await asyncio.to_thread(self.docker.kill, pg_container)

        return {
            "chaos_type": "db_kill",
            "target_container": pg_container,
            "original_restart_policy": original_restart,
        }
