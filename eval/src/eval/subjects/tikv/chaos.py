"""TiKV chaos injection functions for evaluation harness."""

import asyncio
import logging
import random
import time
from typing import Any

from python_on_whales import DockerClient

logger = logging.getLogger(__name__)


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


async def inject_latency_chaos(
    docker: DockerClient, target_container: str, min_ms: int, max_ms: int
) -> dict[str, Any]:
    """Inject network latency using tc netem.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject latency on
        min_ms: Minimum latency in milliseconds
        max_ms: Maximum latency in milliseconds

    Returns:
        Chaos metadata dict with target_container, interface, min_ms, max_ms
    """
    # Calculate average and variation for tc netem
    avg_ms = (min_ms + max_ms) // 2
    variation_ms = (max_ms - min_ms) // 2

    # Inject latency on eth0 using tc netem
    cmd = f"tc qdisc add dev eth0 root netem delay {avg_ms}ms {variation_ms}ms"
    await asyncio.to_thread(docker.execute, target_container, ["sh", "-c", cmd])

    return {
        "chaos_type": "latency",
        "target_container": target_container,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "interface": "eth0",
    }


async def cleanup_latency_chaos(docker: DockerClient, target_container: str) -> None:
    """Clean up tc netem latency rules.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
    """
    try:
        cmd = "tc qdisc del dev eth0 root"
        await asyncio.to_thread(docker.execute, target_container, ["sh", "-c", cmd])
    except Exception as e:
        # Container may have restarted or rule doesn't exist
        logger.debug(f"Failed to cleanup latency chaos on {target_container}: {e}")


async def inject_disk_pressure(
    docker: DockerClient,
    target_container: str,
    fill_percent: int,
    target_path: str = "/data",
) -> dict[str, Any]:
    """Inject disk pressure by filling disk space.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject disk pressure on
        fill_percent: Percentage of available space to fill (0-100)
        target_path: Path to fill (default: /data)

    Returns:
        Chaos metadata dict with target_container, fill_file, fill_bytes, fill_percent

    Raises:
        ValueError: If fill_percent is not in 0-100 range
    """
    if not 0 <= fill_percent <= 100:
        raise ValueError(f"fill_percent must be 0-100, got {fill_percent}")

    # Get available space in KB
    df_cmd = f"df --output=avail {target_path} | tail -n 1"
    result = await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", df_cmd]
    )
    avail_kb = int(result.strip())

    # Calculate bytes to fill
    fill_bytes = int(avail_kb * (fill_percent / 100) * 1024)

    # Create fill file with timestamp
    timestamp = int(time.time())
    fill_file = f"{target_path}/chaos-fill-{timestamp}.tmp"
    fallocate_cmd = f"fallocate -l {fill_bytes} {fill_file}"
    await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", fallocate_cmd]
    )

    return {
        "chaos_type": "disk_pressure",
        "target_container": target_container,
        "fill_percent": fill_percent,
        "fill_file": fill_file,
        "fill_bytes": fill_bytes,
    }


async def cleanup_disk_pressure(
    docker: DockerClient, target_container: str, fill_file: str
) -> None:
    """Clean up disk fill file.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
        fill_file: Path to fill file to remove
    """
    try:
        cmd = f"rm -f {fill_file}"
        await asyncio.to_thread(docker.execute, target_container, ["sh", "-c", cmd])
    except Exception as e:
        # Container may have restarted or file doesn't exist
        logger.debug(f"Failed to cleanup disk pressure on {target_container}: {e}")


async def inject_network_partition(
    docker: DockerClient, isolated_container: str, target_ips: list[str]
) -> dict[str, Any]:
    """Inject network partition by blocking traffic to target IPs.

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to isolate from peers
        target_ips: List of peer IPs to block

    Returns:
        Chaos metadata dict with isolated_container, target_ips
    """
    # Block outbound and inbound traffic for each target IP
    for ip in target_ips:
        output_cmd = f"iptables -I OUTPUT -d {ip} -j DROP"
        input_cmd = f"iptables -I INPUT -s {ip} -j DROP"
        await asyncio.to_thread(
            docker.execute, isolated_container, ["sh", "-c", output_cmd]
        )
        await asyncio.to_thread(
            docker.execute, isolated_container, ["sh", "-c", input_cmd]
        )

    return {
        "chaos_type": "network_partition",
        "isolated_container": isolated_container,
        "target_ips": target_ips,
    }


async def cleanup_network_partition(
    docker: DockerClient, isolated_container: str, target_ips: list[str]
) -> None:
    """Clean up iptables network partition rules.

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to restore connectivity
        target_ips: List of peer IPs to unblock
    """
    for ip in target_ips:
        try:
            output_cmd = f"iptables -D OUTPUT -d {ip} -j DROP || true"
            input_cmd = f"iptables -D INPUT -s {ip} -j DROP || true"
            await asyncio.to_thread(
                docker.execute, isolated_container, ["sh", "-c", output_cmd]
            )
            await asyncio.to_thread(
                docker.execute, isolated_container, ["sh", "-c", input_cmd]
            )
        except Exception as e:
            # Container may have restarted or rules don't exist
            logger.debug(
                f"Failed to cleanup network partition on {isolated_container} for {ip}: {e}"
            )


async def get_tikv_peer_ips(
    docker: DockerClient, exclude_container: str
) -> list[str]:
    """Get IP addresses of TiKV peer containers.

    Args:
        docker: DockerClient configured with compose file
        exclude_container: Container name to exclude from results

    Returns:
        List of IP addresses for TiKV peers (excluding specified container)
    """
    containers = await asyncio.to_thread(docker.compose.ps)

    # Filter to running TiKV containers, excluding the specified one
    tikv_peers = [
        c
        for c in containers
        if "tikv" in c.name.lower()
        and c.state.running
        and c.name != exclude_container
    ]

    # Get IP addresses from container inspect
    peer_ips = []
    for container in tikv_peers:
        inspect_data = await asyncio.to_thread(docker.inspect, container.name)
        # Extract IP from default bridge network
        networks = inspect_data.network_settings.networks
        if networks:
            # Get first network's IP
            ip = next(iter(networks.values())).ip_address
            if ip:
                peer_ips.append(ip)

    return peer_ips
