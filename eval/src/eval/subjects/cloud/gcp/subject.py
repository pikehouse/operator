"""GCP TiKV subject implementation."""

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any

from eval.subjects.cloud.base import CloudSubjectBase, _parse_compose_json
from eval.subjects.cloud.gcp.cos_helpers import (
    install_compose_plugin,
    configure_artifact_registry,
)
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
        "process_pause",
        "packet_loss",
        "asymmetric_partition",
        "pd_leader_kill",
        "leader_concentration",
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
        # Try Docker image path first, fall back to repo-relative path for dev
        docker_path = Path("/usr/local/lib/subjects/tikv/docker-compose.cloud.yaml")
        repo_path = Path(__file__).parents[6] / "subjects" / "tikv" / "docker-compose.cloud.yaml"
        self._local_compose = docker_path if docker_path.exists() else repo_path

        # PD port (accessed via SSH commands to localhost)
        self._pd_port = 2379

    async def _upload_compose_files(self) -> None:
        """Upload TiKV docker-compose files to the VM.

        Installs Docker Compose plugin on COS (which doesn't ship it),
        then uploads the cloud-specific compose file that uses pre-built
        images from Artifact Registry (no docker build needed on VM).
        """
        await install_compose_plugin(self.vm)

        # Create directories on VM
        await self.vm.run_command(f"mkdir -p {self.compose_dir}/config")

        # Upload cloud compose file (uses pre-built images from Artifact Registry)
        await self.vm.upload_file(
            str(self._local_compose),
            f"{self.compose_dir}/docker-compose.yaml",
        )

        # Upload Prometheus config (needed for metrics collection)
        prom_config = self._local_compose.parent / "config" / "prometheus.yml"
        await self.vm.upload_file(
            str(prom_config),
            f"{self.compose_dir}/config/prometheus.yml",
        )

        await configure_artifact_registry(self.vm)

        # Pull images
        await self.vm.run_command(
            f"cd {self.compose_dir} && {self.docker_compose_cmd} -p {self.project_name} pull",
            timeout_sec=300.0,
        )

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for TiKV cluster to be healthy.

        Checks PD API for store count with progressive backoff.
        """
        if not self._created:
            return False

        start = asyncio.get_running_loop().time()
        while True:
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= timeout_sec:
                logger.warning(f"TiKV health check timed out after {elapsed:.0f}s")
                return False

            try:
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
                        logger.info(f"TiKV healthy: {len(up_stores)} stores up ({elapsed:.0f}s)")
                        return True
                    logger.debug(f"Waiting for stores: {len(up_stores)}/3 up ({elapsed:.0f}s)")

            except Exception as e:
                logger.debug(f"Health check error ({elapsed:.0f}s): {e}")

            # Progressive backoff: 3s early, 5s mid, 10s late
            if elapsed < 30:
                await asyncio.sleep(3.0)
            elif elapsed < 60:
                await asyncio.sleep(5.0)
            else:
                await asyncio.sleep(10.0)

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
        elif chaos_type == "process_pause":
            return await self._inject_process_pause(target_name)
        elif chaos_type == "packet_loss":
            return await self._inject_packet_loss(
                target_name,
                params.get("percent", 30),
            )
        elif chaos_type == "asymmetric_partition":
            return await self._inject_asymmetric_partition(target_name)
        elif chaos_type == "pd_leader_kill":
            return await self._inject_pd_leader_kill()
        elif chaos_type == "leader_concentration":
            return await self._inject_leader_concentration()

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
            elif chaos_type == "process_pause":
                await self.vm.run_command(f"docker kill --signal CONT {target}")
            elif chaos_type == "packet_loss":
                await self.vm.run_command(
                    f"docker exec {target} tc qdisc del dev eth0 root 2>/dev/null || true"
                )
            elif chaos_type == "asymmetric_partition":
                target_ip = chaos_metadata.get("target_ip")
                if target_ip:
                    await self.vm.run_command(
                        f"docker exec {target} iptables -D OUTPUT -d {target_ip} -j DROP 2>/dev/null || true"
                    )
                    await self.vm.run_command(
                        f"docker exec {target} iptables -D INPUT -s {target_ip} -j DROP 2>/dev/null || true"
                    )
            elif chaos_type == "pd_leader_kill":
                original_policy = chaos_metadata.get("original_restart_policy", "on-failure")
                await self.vm.run_command(f"docker update --restart={original_policy} {target}")
                await self.vm.run_command(f"docker start {target}")
            elif chaos_type == "leader_concentration":
                pass  # PD auto-rebalances
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

        # Create fill file using fallocate (instant) with dd fallback
        fill_file = "/tmp/chaos-fill.bin"

        exit_code, _, _ = await self.vm.run_command(
            f"docker exec {target} fallocate -l {fill_bytes} {fill_file}"
        )
        if exit_code != 0:
            # fallocate not available (e.g., tmpfs), fall back to dd
            block_size = 1024 * 1024  # 1MB
            count = fill_bytes // block_size
            await self.vm.run_command(
                f"docker exec {target} dd if=/dev/zero of={fill_file} bs={block_size} count={count} 2>/dev/null",
                timeout_sec=300.0,
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

    async def _inject_process_pause(self, target: str) -> dict[str, Any]:
        """SIGSTOP a TiKV container. Container looks alive but process is frozen."""
        await self.vm.run_command(f"docker kill --signal STOP {target}")
        return {"chaos_type": "process_pause", "target_container": target}

    async def _inject_packet_loss(self, target: str, percent: int) -> dict[str, Any]:
        """Inject packet loss via tc netem."""
        await self.vm.run_command(
            f"docker exec {target} tc qdisc add dev eth0 root netem loss {percent}%"
        )
        return {
            "chaos_type": "packet_loss",
            "target_container": target,
            "percent": percent,
        }

    async def _inject_asymmetric_partition(self, target: str) -> dict[str, Any]:
        """Block traffic to ONE random peer only."""
        # Get all TiKV container IPs
        exit_code, stdout, _ = await self.vm.run_command(
            f"{self.docker_compose_cmd} -p {self.project_name} ps --format json"
        )
        containers = _parse_compose_json(stdout) if exit_code == 0 else []
        tikv_containers = [
            c for c in containers
            if c.get("Service", "").startswith("tikv") and c.get("State") == "running"
        ]

        # Pick a peer that isn't the target
        peers = [c for c in tikv_containers if c["Name"] != target]
        if not peers:
            raise RuntimeError("No peers to partition from")
        peer = random.choice(peers)

        # Get peer's IP
        exit_code, peer_ip, _ = await self.vm.run_command(
            f"docker inspect -f '{{{{.NetworkSettings.Networks}}}}' {peer['Name']} | grep -oP '\\d+\\.\\d+\\.\\d+\\.\\d+' | head -1"
        )
        peer_ip = peer_ip.strip()
        if not peer_ip:
            # Fallback: inspect with format
            exit_code, peer_ip, _ = await self.vm.run_command(
                f"docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {peer['Name']}"
            )
            peer_ip = peer_ip.strip()

        # Block traffic to/from this one peer
        await self.vm.run_command(
            f"docker exec {target} iptables -I OUTPUT -d {peer_ip} -j DROP"
        )
        await self.vm.run_command(
            f"docker exec {target} iptables -I INPUT -s {peer_ip} -j DROP"
        )
        return {
            "chaos_type": "asymmetric_partition",
            "target_container": target,
            "target_ip": peer_ip,
        }

    async def _inject_pd_leader_kill(self) -> dict[str, Any]:
        """Kill a PD container (control plane disruption)."""
        exit_code, stdout, _ = await self.vm.run_command(
            f"{self.docker_compose_cmd} -p {self.project_name} ps --format json"
        )
        containers = _parse_compose_json(stdout) if exit_code == 0 else []
        pd_containers = [
            c for c in containers
            if c.get("Service", "").startswith("pd") and c.get("State") == "running"
        ]
        if not pd_containers:
            raise RuntimeError("No running PD containers")

        target = random.choice(pd_containers)["Name"]

        # Get current restart policy
        exit_code, policy, _ = await self.vm.run_command(
            f"docker inspect -f '{{{{.HostConfig.RestartPolicy.Name}}}}' {target}"
        )
        original_policy = policy.strip() or "on-failure"

        await self.vm.run_command(f"docker update --restart=no {target}")
        await self.vm.run_command(f"docker kill {target}")
        return {
            "chaos_type": "pd_leader_kill",
            "target_container": target,
            "original_restart_policy": original_policy,
        }

    async def _inject_leader_concentration(self) -> dict[str, Any]:
        """Transfer all region leaders to one store via PD API."""
        # Get stores
        exit_code, stdout, _ = await self.vm.run_command(
            f"curl -s http://localhost:{self._pd_port}/pd/api/v1/stores"
        )
        stores = json.loads(stdout).get("stores", []) if exit_code == 0 else []
        up_stores = [
            s for s in stores
            if s.get("store", {}).get("state_name") == "Up"
        ]
        if not up_stores:
            raise RuntimeError("No Up stores")

        target_store_id = up_stores[0]["store"]["id"]

        # Get all regions and transfer leaders
        exit_code, stdout, _ = await self.vm.run_command(
            f"curl -s http://localhost:{self._pd_port}/pd/api/v1/regions"
        )
        regions = json.loads(stdout).get("regions", []) if exit_code == 0 else []

        transferred = 0
        for region in regions:
            region_id = region.get("id")
            leader = region.get("leader", {})
            if leader.get("store_id") != target_store_id:
                await self.vm.run_command(
                    f"curl -s -X POST http://localhost:{self._pd_port}/pd/api/v1/operators "
                    f'-d \'{{"name": "transfer-leader", "region_id": {region_id}, "to_store_id": {target_store_id}}}\''
                )
                transferred += 1

        return {
            "chaos_type": "leader_concentration",
            "target_store_id": target_store_id,
            "regions_transferred": transferred,
        }


# Note: Registration happens in eval/subjects/factory.py to enable lazy loading
# without requiring cloud dependencies for local-only usage.
