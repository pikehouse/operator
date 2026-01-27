"""
TiKV chaos injection functions for demo framework.

This module provides TiKV-specific chaos functions:
- kill_random_tikv: Kill random TiKV store container with SIGKILL
- restart_container: Restart a stopped container
- TIKV_CHAOS_CONFIG: ChaosConfig for node kill scenario

Adapted from operator_core/tui/fault.py and operator_core/demo/chaos.py patterns.
"""

import random
from pathlib import Path

from python_on_whales import DockerClient

from demo.types import ChaosConfig, ChaosType


async def kill_random_tikv(compose_file: Path) -> str | None:
    """
    Kill a random TiKV store container with SIGKILL.

    Simulates sudden node failure (crash, hardware fault, network partition).

    Args:
        compose_file: Path to docker-compose.yaml

    Returns:
        Name of killed container, or None if no targets found
    """
    docker = DockerClient(compose_files=[compose_file])

    # Get running TiKV containers
    containers = docker.compose.ps()
    tikv_containers = [
        c
        for c in containers
        if "tikv" in c.name.lower() and c.state.running
    ]

    if not tikv_containers:
        return None

    # Random selection
    target = random.choice(tikv_containers)
    container_name = target.name

    # Kill with SIGKILL (immediate, no cleanup)
    docker.kill(container_name)

    return container_name


async def restart_container(compose_file: Path, container_name: str) -> bool:
    """
    Restart a stopped container.

    Args:
        compose_file: Path to docker-compose.yaml
        container_name: Name of container to restart

    Returns:
        True if restart successful, False otherwise
    """
    docker = DockerClient(compose_files=[compose_file])

    try:
        # Extract service name from container name
        # Container names may have project prefix: "operator-tikv-tikv0-1" -> "tikv0"
        service_name = container_name
        for part in container_name.split("-"):
            if part.startswith("tikv") and len(part) > 4:
                service_name = part
                break

        docker.compose.start(services=[service_name])
        return True
    except Exception:
        return False


async def start_ycsb_load(compose_file: Path) -> bool:
    """
    Start YCSB load generation against TiKV cluster.

    Runs YCSB with workloada profile (50% reads, 50% updates).

    Args:
        compose_file: Path to docker-compose.yaml

    Returns:
        True if YCSB started successfully, False otherwise
    """
    docker = DockerClient(compose_files=[compose_file])

    try:
        # Run YCSB load phase first (creates initial data)
        docker.compose.run(
            "ycsb",
            command=[
                "load", "tikv",
                "-P", "/workloads/workloada",
                "-p", "tikv.pd=pd0:2379",
                "-p", "tikv.type=raw",
            ],
            remove=True,
            detach=False,
        )

        # Run YCSB workload in background
        docker.compose.run(
            "ycsb",
            command=[
                "run", "tikv",
                "-P", "/workloads/workloada",
                "-p", "tikv.pd=pd0:2379",
                "-p", "tikv.type=raw",
                "-p", "operationcount=1000000",  # Run for a long time
            ],
            remove=True,
            detach=True,
            tty=False,
            name="ycsb-run",
        )
        return True
    except Exception as e:
        print(f"[YCSB] Error starting load: {e}")
        return False


# ChaosConfig for TiKV node kill scenario
TIKV_CHAOS_CONFIG = ChaosConfig(
    name="TiKV Node Kill",
    chaos_type=ChaosType.CONTAINER_KILL,
    description="Kill random TiKV store with SIGKILL",
    duration_sec=5.0,
)
