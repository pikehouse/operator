"""TiKV evaluation subject implementing EvalSubject protocol."""

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

import httpx
from python_on_whales import DockerClient

logger = logging.getLogger(__name__)

from eval.subjects.tikv.chaos import (
    cleanup_disk_pressure,
    cleanup_latency_chaos,
    cleanup_network_partition,
    get_tikv_peer_ips,
    inject_disk_pressure,
    inject_latency_chaos,
    inject_network_partition,
    kill_random_tikv,
)


class TiKVEvalSubject:
    """TiKV cluster evaluation subject.

    Implements EvalSubject protocol for TiKV clusters managed via Docker Compose.
    Uses subjects/tikv/docker-compose.yaml by default.
    """

    def __init__(self, compose_file: Path | None = None):
        """Initialize TiKV eval subject.

        Args:
            compose_file: Path to docker-compose.yaml. Defaults to subjects/tikv/docker-compose.yaml.
        """
        if compose_file is None:
            # Default to subjects/tikv/docker-compose.yaml relative to repo root
            # eval/src/eval/subjects/tikv/subject.py -> ../../../../subjects/tikv/docker-compose.yaml
            compose_file = (
                Path(__file__).parents[5] / "subjects" / "tikv" / "docker-compose.yaml"
            )

        self.compose_file = compose_file
        self.docker = DockerClient(compose_files=[compose_file])
        self.pd_endpoint = "http://localhost:2379"  # PD API endpoint

    async def reset(self) -> None:
        """Reset TiKV cluster via docker-compose down/up with volume wipe."""
        # Down with volume cleanup (removes all data)
        await asyncio.to_thread(
            self.docker.compose.down,
            volumes=True,
            remove_orphans=True,
        )

        # Up and wait for healthchecks
        await asyncio.to_thread(
            self.docker.compose.up,
            detach=True,
            wait=True,
        )

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for all TiKV + PD containers to be healthy.

        Checks both Docker healthcheck status AND PD API for store count.
        """
        start = asyncio.get_running_loop().time()

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                # Check container health in thread pool
                containers = await asyncio.to_thread(self.docker.compose.ps)

                # Filter to PD + TiKV containers
                cluster_containers = [
                    c
                    for c in containers
                    if ("pd" in c.name.lower() or "tikv" in c.name.lower())
                ]

                # All containers must be running with healthy status
                all_healthy = all(
                    c.state.running and c.state.health in ("healthy", None)
                    for c in cluster_containers
                )

                if all_healthy:
                    # Additional verification: PD reports 3 stores
                    if await self._verify_stores_up():
                        return True

            except Exception:
                pass  # Container not ready yet

            await asyncio.sleep(2.0)

        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture PD cluster state via API.

        Returns store count, region count, and health status.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Query stores endpoint
                stores_resp = await client.get(
                    f"{self.pd_endpoint}/pd/api/v1/stores"
                )
                stores_data = stores_resp.json()

                # Query regions endpoint (summary)
                regions_resp = await client.get(
                    f"{self.pd_endpoint}/pd/api/v1/stats/region"
                )
                regions_data = regions_resp.json()

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

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types for TiKV."""
        return ["node_kill", "latency", "disk_pressure", "network_partition"]

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
        if chaos_type == "node_kill":
            return await kill_random_tikv(self.docker)

        # Get a random running TiKV container for other chaos types
        containers = await asyncio.to_thread(self.docker.compose.ps)
        tikv_containers = [
            c for c in containers if "tikv" in c.name.lower() and c.state.running
        ]

        if not tikv_containers:
            raise RuntimeError("No running TiKV containers for chaos injection")

        target = random.choice(tikv_containers)

        if chaos_type == "latency":
            min_ms = params.get("min_ms", 50)
            max_ms = params.get("max_ms", 150)
            return await inject_latency_chaos(self.docker, target.name, min_ms, max_ms)

        elif chaos_type == "disk_pressure":
            fill_percent = params.get("fill_percent", 80)
            return await inject_disk_pressure(self.docker, target.name, fill_percent)

        elif chaos_type == "network_partition":
            peer_ips = await get_tikv_peer_ips(self.docker, target.name)
            return await inject_network_partition(self.docker, target.name, peer_ips)

        raise ValueError(
            f"Unknown chaos type: {chaos_type}. Supported: {self.get_chaos_types()}"
        )

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up/revert chaos injection.

        Args:
            chaos_metadata: The dict returned by inject_chaos()
        """
        chaos_type = chaos_metadata.get("chaos_type")

        try:
            if chaos_type == "latency":
                target_container = chaos_metadata["target_container"]
                await cleanup_latency_chaos(self.docker, target_container)

            elif chaos_type == "disk_pressure":
                target_container = chaos_metadata["target_container"]
                fill_file = chaos_metadata["fill_file"]
                await cleanup_disk_pressure(self.docker, target_container, fill_file)

            elif chaos_type == "network_partition":
                isolated_container = chaos_metadata["isolated_container"]
                target_ips = chaos_metadata["target_ips"]
                await cleanup_network_partition(
                    self.docker, isolated_container, target_ips
                )

            elif chaos_type == "node_kill":
                # No cleanup needed - container restarts naturally or via reset
                pass

            else:
                logger.warning(f"Unknown chaos type for cleanup: {chaos_type}")

        except Exception as e:
            # Handle gracefully - container may have been restarted/killed
            logger.warning(f"Failed to cleanup chaos {chaos_type}: {e}")

    async def _verify_stores_up(self) -> bool:
        """Verify PD reports 3 TiKV stores in Up state."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.pd_endpoint}/pd/api/v1/stores")
                data = resp.json()

                stores = data.get("stores", [])
                up_stores = [
                    s
                    for s in stores
                    if s.get("store", {}).get("state_name") == "Up"
                ]

                return len(up_stores) >= 3
        except Exception:
            return False
