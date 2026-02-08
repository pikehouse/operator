"""TiKV chaos injection functions for evaluation harness."""

import asyncio
import logging
import random
import re
import time
from typing import Any

import httpx
from python_on_whales import DockerClient

logger = logging.getLogger(__name__)

# Pattern to match TiKV service containers: {project}-tikv{N}-{index}
# e.g., tikv-tikv0-1, tikv-eval-1-tikv0-1
# Avoids matching project prefix (tikv-eval-1-grafana-1 should NOT match)
TIKV_CONTAINER_PATTERN = re.compile(r"-tikv\d+-")


async def kill_random_tikv(docker: DockerClient) -> dict[str, Any]:
    """Kill a random TiKV container with SIGKILL and prevent restart.

    Simulates sudden node failure (crash, hardware fault). Disables the
    container's restart policy first to prevent Docker from automatically
    restarting it.

    Args:
        docker: DockerClient configured with compose file

    Returns:
        Chaos metadata dict with target_container, signal, original_restart_policy

    Raises:
        RuntimeError: If no running TiKV containers found
    """
    # Get running containers in thread pool (python-on-whales is sync)
    containers = await asyncio.to_thread(docker.compose.ps)

    # Filter to running TiKV containers (service names: tikv0, tikv1, tikv2)
    tikv_containers = [
        c for c in containers
        if TIKV_CONTAINER_PATTERN.search(c.name.lower()) and c.state.running
    ]

    if not tikv_containers:
        raise RuntimeError("No running TiKV containers to kill")

    # Random selection
    target = random.choice(tikv_containers)

    # Get original restart policy before disabling
    inspect_data = await asyncio.to_thread(docker.container.inspect, target.name)
    original_restart = inspect_data.host_config.restart_policy.name

    # Disable restart policy so container stays dead
    await asyncio.to_thread(
        docker.container.update, target.name, restart="no"
    )

    # Kill with SIGKILL in thread pool
    await asyncio.to_thread(docker.kill, target.name)

    return {
        "chaos_type": "node_kill",
        "target_container": target.name,
        "signal": "SIGKILL",
        "original_restart_policy": original_restart,
    }


async def restore_node_restart_policy(
    docker: DockerClient, target_container: str, restart_policy: str
) -> None:
    """Restore container restart policy after node_kill chaos.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to restore
        restart_policy: Original restart policy to restore (e.g., 'on-failure')
    """
    try:
        await asyncio.to_thread(
            docker.container.update, target_container, restart=restart_policy
        )
    except Exception as e:
        # Container may not exist or policy may already be set
        logger.debug(f"Failed to restore restart policy on {target_container}: {e}")


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


# Disk pressure uses a tmpfs to avoid consuming host disk
# Size of tmpfs in bytes (256MB is enough to stress TiKV)
DISK_PRESSURE_TMPFS_SIZE = 256 * 1024 * 1024  # 256MB


async def inject_disk_pressure(
    docker: DockerClient,
    target_container: str,
    fill_percent: int,
    target_path: str = "/tmp/chaos-disk",
) -> dict[str, Any]:
    """Inject disk pressure using a size-limited tmpfs.

    Creates a tmpfs mount, fills it to the specified percentage, then
    monitors TiKV's response to low disk conditions. The tmpfs is isolated
    from host storage - it uses container memory, not host disk.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject disk pressure on
        fill_percent: Percentage of tmpfs to fill (0-100)
        target_path: Path to mount tmpfs (default: /tmp/chaos-disk)

    Returns:
        Chaos metadata dict with target_container, fill_file, fill_bytes, fill_percent

    Raises:
        ValueError: If fill_percent is not in 0-100 range
    """
    if not 0 <= fill_percent <= 100:
        raise ValueError(f"fill_percent must be 0-100, got {fill_percent}")

    tmpfs_size = DISK_PRESSURE_TMPFS_SIZE
    fill_bytes = int(tmpfs_size * (fill_percent / 100))

    # Create and mount tmpfs (uses container memory, not host disk)
    setup_cmd = f"mkdir -p {target_path} && mount -t tmpfs -o size={tmpfs_size} tmpfs {target_path}"
    await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", setup_cmd]
    )

    # Fill the tmpfs
    timestamp = int(time.time())
    fill_file = f"{target_path}/chaos-fill-{timestamp}.tmp"
    # Use dd instead of fallocate for tmpfs compatibility
    block_size = 1024 * 1024  # 1MB blocks
    count = fill_bytes // block_size
    fill_cmd = f"dd if=/dev/zero of={fill_file} bs={block_size} count={count} 2>/dev/null"
    await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", fill_cmd]
    )

    return {
        "chaos_type": "disk_pressure",
        "target_container": target_container,
        "fill_percent": fill_percent,
        "fill_file": fill_file,
        "fill_bytes": fill_bytes,
        "tmpfs_size": tmpfs_size,
        "target_path": target_path,
    }


async def cleanup_disk_pressure(
    docker: DockerClient, target_container: str, fill_file: str, target_path: str = "/tmp/chaos-disk"
) -> None:
    """Clean up tmpfs mount used for disk pressure.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
        fill_file: Path to fill file to remove (unused, kept for compatibility)
        target_path: Path where tmpfs was mounted
    """
    try:
        # Unmount tmpfs and remove directory
        cmd = f"umount {target_path} 2>/dev/null; rm -rf {target_path}"
        await asyncio.to_thread(docker.execute, target_container, ["sh", "-c", cmd])
    except Exception as e:
        # Container may have restarted or mount doesn't exist
        logger.debug(f"Failed to cleanup disk pressure on {target_container}: {e}")


async def inject_network_partition(
    docker: DockerClient,
    isolated_container: str,
    target_ips: list[str],
    pd_ips: list[str] | None = None,
) -> dict[str, Any]:
    """Inject network partition by blocking traffic to peers AND PD.

    Blocks traffic to both TiKV peers and PD nodes, causing the isolated
    node to be marked as Down by PD (can't send heartbeats).

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to isolate from peers
        target_ips: List of peer IPs to block
        pd_ips: List of PD IPs to block (causes store to go Down)

    Returns:
        Chaos metadata dict with isolated_container, target_ips, pd_ips
    """
    all_ips = target_ips + (pd_ips or [])

    # Block outbound and inbound traffic for each target IP
    for ip in all_ips:
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
        "pd_ips": pd_ips or [],
    }


async def cleanup_network_partition(
    docker: DockerClient,
    isolated_container: str,
    target_ips: list[str],
    pd_ips: list[str] | None = None,
) -> None:
    """Clean up iptables network partition rules.

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to restore connectivity
        target_ips: List of peer IPs to unblock
        pd_ips: List of PD IPs to unblock
    """
    all_ips = target_ips + (pd_ips or [])

    for ip in all_ips:
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
        if TIKV_CONTAINER_PATTERN.search(c.name.lower())
        and c.state.running
        and c.name != exclude_container
    ]

    # Get IP addresses from container inspect
    peer_ips = []
    for container in tikv_peers:
        inspect_data = await asyncio.to_thread(docker.container.inspect, container.name)
        # Extract IP from default bridge network
        networks = inspect_data.network_settings.networks
        if networks:
            # Get first network's IP
            ip = next(iter(networks.values())).ip_address
            if ip:
                peer_ips.append(ip)

    return peer_ips


# Pattern to match PD containers: {project}-pd{N}-{index}
PD_CONTAINER_PATTERN = re.compile(r"-pd\d+-")


async def get_pd_ips(docker: DockerClient) -> list[str]:
    """Get IP addresses of all PD containers.

    Args:
        docker: DockerClient configured with compose file

    Returns:
        List of IP addresses for PD nodes
    """
    containers = await asyncio.to_thread(docker.compose.ps)

    # Filter to running PD containers
    pd_containers = [
        c
        for c in containers
        if PD_CONTAINER_PATTERN.search(c.name.lower()) and c.state.running
    ]

    # Get IP addresses from container inspect
    pd_ips = []
    for container in pd_containers:
        inspect_data = await asyncio.to_thread(docker.container.inspect, container.name)
        networks = inspect_data.network_settings.networks
        if networks:
            ip = next(iter(networks.values())).ip_address
            if ip:
                pd_ips.append(ip)

    return pd_ips


async def inject_process_pause(
    docker: DockerClient, target_container: str
) -> dict[str, Any]:
    """Pause a TiKV process with SIGSTOP.

    Container stays alive but process is frozen -- looks running to Docker
    but cannot respond to RPCs or Raft heartbeats. Diagnostically tricky
    because ``docker ps`` still shows the container as running.

    Uses ``docker kill --signal STOP`` from the host side (not ``docker exec``,
    which may hang on a SIGSTOP'd container).

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to pause

    Returns:
        Chaos metadata dict with target_container and signal
    """
    await asyncio.to_thread(docker.kill, target_container, signal="STOP")

    return {
        "chaos_type": "process_pause",
        "target_container": target_container,
        "signal": "SIGSTOP",
    }


async def cleanup_process_pause(
    docker: DockerClient, target_container: str
) -> None:
    """Resume a SIGSTOP'd TiKV process with SIGCONT.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to resume
    """
    try:
        await asyncio.to_thread(docker.kill, target_container, signal="CONT")
    except Exception as e:
        logger.debug(f"Failed to SIGCONT {target_container}: {e}")


async def inject_packet_loss(
    docker: DockerClient, target_container: str, percent: int = 30
) -> dict[str, Any]:
    """Inject packet loss using tc netem.

    Causes intermittent, noisy failures -- some RPCs succeed, some fail.
    Diagnostically difficult because symptoms are non-deterministic.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject packet loss on
        percent: Packet loss percentage (default 30)

    Returns:
        Chaos metadata dict with target_container, interface, percent
    """
    cmd = f"tc qdisc add dev eth0 root netem loss {percent}%"
    await asyncio.to_thread(docker.execute, target_container, ["sh", "-c", cmd])

    return {
        "chaos_type": "packet_loss",
        "target_container": target_container,
        "percent": percent,
        "interface": "eth0",
    }


async def inject_asymmetric_partition(
    docker: DockerClient, isolated_container: str, target_ip: str
) -> dict[str, Any]:
    """Block traffic to ONE specific peer IP only.

    Unlike full network_partition which blocks all peers + PD, this blocks
    traffic to a single peer. The isolated node can still talk to PD and
    other peers, creating partial connectivity that is hard to diagnose.

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to apply partition on
        target_ip: Single peer IP to block

    Returns:
        Chaos metadata dict with isolated_container and target_ip
    """
    output_cmd = f"iptables -I OUTPUT -d {target_ip} -j DROP"
    input_cmd = f"iptables -I INPUT -s {target_ip} -j DROP"
    await asyncio.to_thread(
        docker.execute, isolated_container, ["sh", "-c", output_cmd]
    )
    await asyncio.to_thread(
        docker.execute, isolated_container, ["sh", "-c", input_cmd]
    )

    return {
        "chaos_type": "asymmetric_partition",
        "isolated_container": isolated_container,
        "target_ip": target_ip,
    }


async def cleanup_asymmetric_partition(
    docker: DockerClient, isolated_container: str, target_ip: str
) -> None:
    """Remove iptables rules for a single-peer asymmetric partition.

    Args:
        docker: DockerClient configured with compose file
        isolated_container: Container to restore connectivity on
        target_ip: Peer IP to unblock
    """
    try:
        output_cmd = f"iptables -D OUTPUT -d {target_ip} -j DROP || true"
        input_cmd = f"iptables -D INPUT -s {target_ip} -j DROP || true"
        await asyncio.to_thread(
            docker.execute, isolated_container, ["sh", "-c", output_cmd]
        )
        await asyncio.to_thread(
            docker.execute, isolated_container, ["sh", "-c", input_cmd]
        )
    except Exception as e:
        logger.debug(
            f"Failed to cleanup asymmetric partition on {isolated_container} "
            f"for {target_ip}: {e}"
        )


async def kill_random_pd(docker: DockerClient) -> dict[str, Any]:
    """Kill a random PD container with SIGKILL and prevent restart.

    Simulates control plane disruption -- PD is down but TiKV data plane
    stays up. Existing Raft leaders continue to serve reads/writes, but
    new scheduling (region splits, leader transfers) stops.

    Args:
        docker: DockerClient configured with compose file

    Returns:
        Chaos metadata dict with target_container, signal, original_restart_policy

    Raises:
        RuntimeError: If no running PD containers found
    """
    containers = await asyncio.to_thread(docker.compose.ps)

    pd_containers = [
        c
        for c in containers
        if PD_CONTAINER_PATTERN.search(c.name.lower()) and c.state.running
    ]

    if not pd_containers:
        raise RuntimeError("No running PD containers to kill")

    target = random.choice(pd_containers)

    inspect_data = await asyncio.to_thread(docker.container.inspect, target.name)
    original_restart = inspect_data.host_config.restart_policy.name

    await asyncio.to_thread(
        docker.container.update, target.name, restart="no"
    )

    await asyncio.to_thread(docker.kill, target.name)

    return {
        "chaos_type": "pd_leader_kill",
        "target_container": target.name,
        "signal": "SIGKILL",
        "original_restart_policy": original_restart,
    }


async def inject_leader_concentration(
    docker: DockerClient, pd_endpoint: str, target_store_id: int | None = None
) -> dict[str, Any]:
    """Transfer all region leaders to a single store via PD API.

    Creates a hot spot by concentrating all region leaders on one store.
    The overloaded store may see increased latency and CPU usage while
    other stores sit idle.

    Args:
        docker: DockerClient configured with compose file (unused, kept for interface consistency)
        pd_endpoint: PD API endpoint (e.g., http://localhost:2379)
        target_store_id: Store to concentrate leaders on (random if None)

    Returns:
        Chaos metadata dict with target_store_id and transfer_count
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get all stores to pick a target
        stores_resp = await client.get(f"{pd_endpoint}/pd/api/v1/stores")
        stores_resp.raise_for_status()
        stores_data = stores_resp.json()
        up_stores = [
            s["store"]["id"]
            for s in stores_data.get("stores", [])
            if s.get("store", {}).get("state_name") == "Up"
        ]

        if not up_stores:
            raise RuntimeError("No Up stores to concentrate leaders on")

        if target_store_id is None:
            target_store_id = random.choice(up_stores)

        # Get all regions
        regions_resp = await client.get(f"{pd_endpoint}/pd/api/v1/regions")
        regions_resp.raise_for_status()
        regions_data = regions_resp.json()

        transfer_count = 0
        for region in regions_data.get("regions", []):
            region_id = region.get("id")
            leader = region.get("leader", {})
            current_store = leader.get("store_id")

            if current_store == target_store_id:
                continue  # Already on target

            # Check that target store is a peer for this region
            peers = region.get("peers", [])
            peer_store_ids = [p.get("store_id") for p in peers]
            if target_store_id not in peer_store_ids:
                continue  # Target not a replica for this region

            # Transfer leader
            try:
                transfer_resp = await client.post(
                    f"{pd_endpoint}/pd/api/v1/operators",
                    json={
                        "name": "transfer-leader",
                        "region_id": region_id,
                        "to_store_id": target_store_id,
                    },
                )
                if transfer_resp.status_code == 200:
                    transfer_count += 1
            except Exception as e:
                logger.debug(f"Failed to transfer region {region_id}: {e}")

    return {
        "chaos_type": "leader_concentration",
        "target_store_id": target_store_id,
        "transfer_count": transfer_count,
    }
