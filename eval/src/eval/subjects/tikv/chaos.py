"""TiKV chaos injection functions for evaluation harness."""

import asyncio
import random
from typing import Any

from python_on_whales import DockerClient


async def kill_random_tikv(docker: DockerClient) -> dict[str, Any]:
    """Kill a random TiKV container with SIGKILL.

    Simulates sudden node failure (crash, hardware fault).

    Args:
        docker: DockerClient configured with compose file

    Returns:
        Chaos metadata dict with target_container, signal

    Raises:
        RuntimeError: If no running TiKV containers found
    """
    # Get running containers in thread pool (python-on-whales is sync)
    containers = await asyncio.to_thread(docker.compose.ps)

    # Filter to running TiKV containers
    tikv_containers = [
        c for c in containers if "tikv" in c.name.lower() and c.state.running
    ]

    if not tikv_containers:
        raise RuntimeError("No running TiKV containers to kill")

    # Random selection
    target = random.choice(tikv_containers)

    # Kill with SIGKILL in thread pool
    await asyncio.to_thread(docker.kill, target.name)

    return {
        "chaos_type": "node_kill",
        "target_container": target.name,
        "signal": "SIGKILL",
    }
