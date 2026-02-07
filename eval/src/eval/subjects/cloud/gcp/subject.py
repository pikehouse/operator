"""GCP TiKV subject implementation."""

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any

from eval.subjects.cloud.base import CloudSubjectBase, _parse_compose_json
from eval.subjects.cloud.gcp.vm import GCPVM

logger = logging.getLogger(__name__)


class GCPTiKVSubject(CloudSubjectBase):
    """TiKV cluster running on GCP Compute Engine.

    Enables ALL chaos types including dangerous ones (disk_pressure,
    memory_exhaustion, cpu_starvation) that are unsafe for local execution.

    Uses Container-Optimized OS with Docker pre-installed.
    """

    # Chaos types available on cloud (superset of local)
    CLOUD_CHAOS_TYPES = [
        "node_kill",
        "latency",
        "network_partition",
        "disk_pressure",
        "memory_exhaustion",
        "cpu_starvation",
    ]

    def __init__(
        self,
        instance_id: int = 0,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-4",
        compose_dir: str = "/tmp/tikv",
    ):
        """Initialize GCP TiKV subject.

        Args:
            instance_id: Instance number (used for VM naming)
            project: GCP project ID
            zone: GCP zone
            machine_type: VM machine type
            compose_dir: Directory on VM for compose files
        """
        vm = GCPVM(
            project=project,
            zone=zone,
            machine_type=machine_type,
            name_prefix=f"tikv-eval-{instance_id}",
        )
        # COS has noexec on /home and /tmp; compose plugin installed to /var/lib/toolbox
        cos_compose_cmd = "docker --config /var/lib/toolbox/docker-config compose"
        super().__init__(
            vm=vm,
            compose_file=compose_dir,
            project_name=f"tikv-eval-{instance_id}",
            docker_compose_cmd=cos_compose_cmd,
        )
        self.instance_id = instance_id
        self.compose_dir = compose_dir

        # Use cloud-specific compose file (pre-built images, no build step)
        self._local_compose = (
            Path(__file__).parents[6] / "subjects" / "tikv" / "docker-compose.cloud.yaml"
        )

        # PD endpoint (via SSH port forward or external IP)
        self._pd_port = 2379

    @property
    def pd_endpoint(self) -> str:
        """Return PD API endpoint."""
        return f"http://{self.vm.external_ip}:{self._pd_port}"

    async def _upload_compose_files(self) -> None:
        """Upload TiKV docker-compose files to the VM.

        Installs Docker Compose plugin on COS (which doesn't ship it),
        then uploads the cloud-specific compose file that uses pre-built
        images from Artifact Registry (no docker build needed on VM).
        """
        # Install Docker Compose plugin on COS.
        # COS has noexec on /home and /tmp, so we download to /tmp then
        # sudo-copy to /var/lib/toolbox (exec-enabled) and configure as
        # a Docker CLI plugin via --config flag.
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

        # Upload cloud compose file (uses pre-built images from Artifact Registry)
        await self.vm.upload_file(
            str(self._local_compose),
            f"{self.compose_dir}/docker-compose.yaml",
        )

        # Configure Artifact Registry auth for both default and toolbox docker configs.
        # COS has docker-credential-gcr pre-installed; gcloud CLI is NOT available.
        await self.vm.run_command(
            "docker-credential-gcr configure-docker --registries=us-central1-docker.pkg.dev",
            timeout_sec=30.0,
        )
        # Copy credential config to toolbox docker config (used by compose plugin)
        await self.vm.run_command(
            "sudo cp ~/.docker/config.json /var/lib/toolbox/docker-config/config.json && "
            "sudo chmod 644 /var/lib/toolbox/docker-config/config.json",
            timeout_sec=10.0,
        )

        # Pull images
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} pull",
            timeout_sec=300.0,
        )

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for TiKV cluster to be healthy.

        Checks both container health and PD API for store count.
        """
        if not self._created:
            return False

        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                # Check PD API via SSH curl
                exit_code, stdout, _ = await self.vm.run_command(
                    f"curl -s http://localhost:{self._pd_port}/pd/api/v1/stores"
                )
                if exit_code == 0:
                    data = json.loads(stdout)
                    stores = data.get("stores", [])
                    up_stores = [
                        s for s in stores
                        if s.get("store", {}).get("state_name") == "Up"
                    ]
                    if len(up_stores) >= 3:
                        return True

            except Exception as e:
                logger.debug(f"Health check error: {e}")

            await asyncio.sleep(2.0)

        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture PD cluster state via API."""
        try:
            exit_code, stdout, _ = await self.vm.run_command(
                f"curl -s http://localhost:{self._pd_port}/pd/api/v1/stores"
            )
            if exit_code == 0:
                stores_data = json.loads(stdout)

                exit_code, stdout, _ = await self.vm.run_command(
                    f"curl -s http://localhost:{self._pd_port}/pd/api/v1/stats/region"
                )
                regions_data = json.loads(stdout) if exit_code == 0 else {}

                return {
                    "store_count": stores_data.get("count", 0),
                    "stores": [
                        {
                            "id": s.get("store", {}).get("id"),
                            "address": s.get("store", {}).get("address"),
                            "state_name": s.get("store", {}).get("state_name"),
                        }
                        for s in stores_data.get("stores", [])
                    ],
                    "region_count": regions_data.get("count", 0),
                }
        except Exception as e:
            return {"error": str(e)}
        return {}

    def get_chaos_types(self) -> list[str]:
        """Return all chaos types (including dangerous ones)."""
        return self.CLOUD_CHAOS_TYPES

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject chaos on the cloud VM.

        Supports dangerous chaos types that are unsafe for local execution.
        """
        if chaos_type not in self.CLOUD_CHAOS_TYPES:
            raise ValueError(f"Unknown chaos type: {chaos_type}")

        # Get random TiKV container
        exit_code, stdout, _ = await self.vm.run_command(
            f"{self.docker_compose_cmd} -p {self.project_name} ps --format json"
        )
        containers = _parse_compose_json(stdout) if exit_code == 0 else []
        # Filter by Service field (not Name) because the project name
        # "tikv-eval-0" is prefixed on all container names, making Name
        # unreliable for filtering (e.g., "tikv-eval-0-pd1-1" contains "tikv")
        tikv_containers = [
            c for c in containers
            if c.get("Service", "").startswith("tikv") and c.get("State") == "running"
        ]

        if not tikv_containers and chaos_type != "node_kill":
            raise RuntimeError("No running TiKV containers")

        target = random.choice(tikv_containers) if tikv_containers else None
        target_name = target["Name"] if target else None

        if chaos_type == "node_kill":
            return await self._inject_node_kill(target_name)
        elif chaos_type == "latency":
            return await self._inject_latency(
                target_name,
                params.get("min_ms", 50),
                params.get("max_ms", 150),
            )
        elif chaos_type == "network_partition":
            return await self._inject_network_partition(target_name)
        elif chaos_type == "disk_pressure":
            return await self._inject_disk_pressure(
                target_name,
                params.get("fill_percent", 80),
            )
        elif chaos_type == "memory_exhaustion":
            return await self._inject_memory_exhaustion(
                target_name,
                params.get("consume_mb", 512),
            )
        elif chaos_type == "cpu_starvation":
            return await self._inject_cpu_starvation(
                target_name,
                params.get("cores", 4),
            )

        raise ValueError(f"Unknown chaos type: {chaos_type}")

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up chaos on the cloud VM."""
        chaos_type = chaos_metadata.get("chaos_type")
        target = chaos_metadata.get("target_container")

        try:
            if chaos_type == "node_kill":
                # Restore restart policy and start container
                await self.vm.run_command(f"docker update --restart=on-failure {target}")
                await self.vm.run_command(f"docker start {target}")
            elif chaos_type == "latency":
                await self.vm.run_command(
                    f"docker exec {target} tc qdisc del dev eth0 root 2>/dev/null || true"
                )
            elif chaos_type == "network_partition":
                # Flush iptables rules
                await self.vm.run_command(
                    f"docker exec {target} iptables -F INPUT; docker exec {target} iptables -F OUTPUT"
                )
            elif chaos_type == "disk_pressure":
                fill_file = chaos_metadata.get("fill_file", "/tmp/chaos-fill.bin")
                await self.vm.run_command(f"docker exec {target} rm -f {fill_file}")
            elif chaos_type == "memory_exhaustion":
                # Kill stress process
                await self.vm.run_command(
                    f"docker exec {target} pkill -9 stress || true"
                )
            elif chaos_type == "cpu_starvation":
                # Kill stress process
                await self.vm.run_command(
                    f"docker exec {target} pkill -9 stress || true"
                )
        except Exception as e:
            logger.debug(f"Cleanup note: {e}")

    # --- Chaos injection implementations ---

    async def _inject_node_kill(self, target: str) -> dict[str, Any]:
        """Kill a TiKV container.

        Disables restart policy first so the container stays dead
        for the monitor to detect.
        """
        if not target:
            # Get first TiKV container
            exit_code, stdout, _ = await self.vm.run_command(
                f"{self.docker_compose_cmd} -p {self.project_name} ps -q tikv0"
            )
            target = stdout.strip()

        # Disable restart policy so container stays dead after kill
        await self.vm.run_command(f"docker update --restart=no {target}")
        await self.vm.run_command(f"docker kill {target}")
        return {"chaos_type": "node_kill", "target_container": target}

    async def _inject_latency(
        self, target: str, min_ms: int, max_ms: int
    ) -> dict[str, Any]:
        """Inject network latency."""
        avg_ms = (min_ms + max_ms) // 2
        var_ms = (max_ms - min_ms) // 2
        await self.vm.run_command(
            f"docker exec {target} tc qdisc add dev eth0 root netem delay {avg_ms}ms {var_ms}ms"
        )
        return {
            "chaos_type": "latency",
            "target_container": target,
            "min_ms": min_ms,
            "max_ms": max_ms,
        }

    async def _inject_network_partition(self, target: str) -> dict[str, Any]:
        """Inject network partition (block peer communication)."""
        # Block all traffic to other containers
        await self.vm.run_command(
            f"docker exec {target} iptables -I OUTPUT -p tcp --dport 20160 -j DROP"
        )
        await self.vm.run_command(
            f"docker exec {target} iptables -I INPUT -p tcp --sport 20160 -j DROP"
        )
        return {"chaos_type": "network_partition", "target_container": target}

    async def _inject_disk_pressure(
        self, target: str, fill_percent: int
    ) -> dict[str, Any]:
        """Inject REAL disk pressure (not tmpfs).

        This is safe on cloud VMs but dangerous on laptops.
        Fills actual disk space, not container memory.
        """
        # Get available space on root
        exit_code, stdout, _ = await self.vm.run_command(
            f"docker exec {target} df -B1 / | tail -1 | awk '{{print $4}}'"
        )
        available_bytes = int(stdout.strip())
        fill_bytes = int(available_bytes * (fill_percent / 100))

        # Create fill file
        fill_file = "/tmp/chaos-fill.bin"
        block_size = 1024 * 1024  # 1MB
        count = fill_bytes // block_size

        await self.vm.run_command(
            f"docker exec {target} dd if=/dev/zero of={fill_file} bs={block_size} count={count} 2>/dev/null"
        )

        return {
            "chaos_type": "disk_pressure",
            "target_container": target,
            "fill_percent": fill_percent,
            "fill_bytes": fill_bytes,
            "fill_file": fill_file,
        }

    async def _inject_memory_exhaustion(
        self, target: str, consume_mb: int
    ) -> dict[str, Any]:
        """Inject memory pressure using stress tool.

        Consumes actual container memory, may trigger OOM killer.
        """
        # Install stress if not present and run
        await self.vm.run_command(
            f"docker exec {target} sh -c 'command -v stress || apk add --no-cache stress || apt-get install -y stress 2>/dev/null || true'"
        )
        # Run stress in background
        await self.vm.run_command(
            f"docker exec -d {target} stress --vm 1 --vm-bytes {consume_mb}M --vm-keep"
        )

        return {
            "chaos_type": "memory_exhaustion",
            "target_container": target,
            "consume_mb": consume_mb,
        }

    async def _inject_cpu_starvation(
        self, target: str, cores: int
    ) -> dict[str, Any]:
        """Inject CPU starvation using stress tool.

        Spins CPU to 100% on specified number of cores.
        """
        # Install stress if not present and run
        await self.vm.run_command(
            f"docker exec {target} sh -c 'command -v stress || apk add --no-cache stress || apt-get install -y stress 2>/dev/null || true'"
        )
        # Run stress in background
        await self.vm.run_command(
            f"docker exec -d {target} stress --cpu {cores}"
        )

        return {
            "chaos_type": "cpu_starvation",
            "target_container": target,
            "cores": cores,
        }


# Note: Registration happens in eval/subjects/factory.py to enable lazy loading
# without requiring cloud dependencies for local-only usage.
