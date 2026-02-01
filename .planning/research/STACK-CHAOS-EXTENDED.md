# Technology Stack for Extended TiKV Chaos Types

**Project:** Operator Eval Harness - TiKV Chaos Extension
**Research Date:** 2026-02-01
**Confidence:** HIGH

## Executive Summary

Three new chaos types (cpu_pressure, memory_pressure, io_latency) require different tooling approaches based on Docker container constraints and implementation complexity:

- **cpu_pressure**: stress-ng (recommended) or SIGSTOP (alternative)
- **memory_pressure**: docker update with cgroups (recommended)
- **io_latency**: Deferred - requires privileged containers and dm-delay complexity

## Recommended Stack

### CPU Pressure: stress-ng

| Component | Version | Purpose | Why |
|-----------|---------|---------|-----|
| stress-ng | 0.15.00+ | CPU load generation | Available in Rocky Linux 9 repos, clean timeout support, predictable resource consumption |
| pkill | (coreutils) | Process cleanup | Kill stress-ng by name via docker exec |

**Installation (Dockerfile.tikv-chaos):**
```dockerfile
RUN dnf install -y stress-ng && dnf clean all
```

**Injection command:**
```bash
# Run stress-ng in background with timeout
docker exec -d <container> stress-ng --cpu 0 --timeout 300s
```

**Cleanup command:**
```bash
# Kill all stress-ng processes
docker exec <container> pkill stress-ng
```

**Why stress-ng over SIGSTOP:**
- Generates realistic CPU load (SIGSTOP just pauses process)
- Controllable intensity (--cpu N for specific core count, --cpu 0 for all cores)
- Built-in timeout prevents runaway processes
- Clean termination via SIGALRM or pkill
- Better simulates real-world CPU contention scenarios

**SIGSTOP alternative (NOT recommended):**
- Requires targeting TiKV's specific PID
- Cannot be caught/blocked, forcing immediate pause
- Less realistic (paused process != CPU-saturated process)
- More complex cleanup (must track PIDs, send SIGCONT)
- Use only if stress-ng unavailable

### Memory Pressure: docker update + cgroups

| Component | Version | Purpose | Why |
|-----------|---------|---------|-----|
| docker update | Docker 20.10+ | Runtime memory limit | Changes cgroup limits without container restart |
| docker inspect | Docker 20.10+ | Read current limits | Capture original memory limit for restoration |

**No Dockerfile changes required** - uses Docker API and cgroups v2.

**Injection pattern:**
```python
# 1. Capture current memory limit
inspect_data = await asyncio.to_thread(docker.container.inspect, target.name)
original_memory = inspect_data.host_config.memory  # bytes, 0 = unlimited

# 2. Calculate pressure limit (e.g., 512MB for moderate pressure)
pressure_limit = 512 * 1024 * 1024  # 512MB in bytes

# 3. Apply limit via docker update
await asyncio.to_thread(
    docker.container.update, target.name, memory=pressure_limit
)
```

**Cleanup pattern:**
```python
# Restore original limit (0 = unlimited)
await asyncio.to_thread(
    docker.container.update, target.name, memory=original_memory
)
```

**Why docker update over cgroup files:**
- Higher-level API, portable across cgroups v1/v2
- Docker handles cgroup path differences (/sys/fs/cgroup/memory.max vs memory.limit_in_bytes)
- Immediate effect without container restart
- python-on-whales already wraps docker.container.update
- No need for docker exec or filesystem manipulation

**Cgroups v2 note:**
- Memory limit file changed from `/sys/fs/cgroup/memory/memory.limit_in_bytes` (v1) to `/sys/fs/cgroup/memory.max` (v2)
- docker update abstracts this difference
- Current TiKV containers likely use cgroups v2 (default on Rocky Linux 9)

**Known issue (LOW impact):**
- docker update --memory-reservation (soft limit) may not propagate to cgroup v2 memory.high file
- Hard limit (--memory) works correctly
- Workaround: use hard limits for chaos injection

### I/O Latency: DEFERRED

**Recommendation:** Defer io_latency chaos type to future milestone.

**Why deferred:**

| Requirement | Status | Blocker |
|-------------|--------|---------|
| Privileged containers | Not currently used | Security risk, breaks container isolation |
| dm-delay kernel module | Requires host kernel access | Container cannot load kernel modules |
| Block device access | Requires /dev/mapper access | Not exposed to unprivileged containers |
| Setup complexity | dmsetup create commands | Adds 10+ lines of setup/cleanup code |
| Reversibility risk | Must track dm device names | Cleanup failure leaves devices in delayed state |

**dm-delay approach (if pursued):**

1. Add privileged mode to TiKV containers in docker-compose.yaml:
```yaml
tikv0:
  privileged: true  # Required for device mapper
```

2. Install dmsetup in Dockerfile.tikv-chaos:
```dockerfile
RUN dnf install -y device-mapper && dnf clean all
```

3. Injection (complex):
```bash
# Find TiKV data volume block device
DEVICE=$(docker exec <container> df /data | tail -1 | awk '{print $1}')

# Get device size
SIZE=$(docker exec <container> blockdev --getsz $DEVICE)

# Create delayed device (500ms latency)
docker exec <container> dmsetup create tikv-data-delayed \
  --table "0 $SIZE delay $DEVICE 0 500"

# Remount TiKV data to delayed device (HIGH RISK)
# ... complex mount/unmount logic here
```

4. Cleanup (fragile):
```bash
docker exec <container> dmsetup remove tikv-data-delayed
# ... restore original mount
```

**Alternatives investigated:**

| Approach | Verdict | Reason |
|----------|---------|--------|
| tc netem on block device | INVALID | tc only works on network interfaces (eth0), not block devices (sda, dm-0) |
| blkio cgroups throttle | LIMITED | Only throttles IOPS/bandwidth, not latency; cgroups v1 limited buffered I/O control |
| fio with high iodepth | NOT CHAOS | fio measures latency, doesn't inject it; saturates I/O but doesn't add fixed delay |

**Recommendation for future:**
- If io_latency needed, use Kubernetes with privileged SecurityContext
- Or use cloud provider's disk throttling features (AWS gp3 IOPS limits, etc.)
- Or accept IOPS throttling (blkio) instead of latency injection
- Current Docker Compose setup not suitable for production-grade I/O chaos

## Alternatives Considered

### CPU Pressure Alternatives

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| stress-ng | SIGSTOP/SIGCONT | Pausing != CPU load; less realistic; complex PID tracking |
| stress-ng | cpulimit | Throttles existing process, doesn't generate load; requires targeting TiKV PID |
| stress-ng | docker update --cpus | Limits CPU quota but doesn't generate pressure; TiKV may not saturate remaining quota |

### Memory Pressure Alternatives

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| docker update | cgroup file writes | Lower-level; v1/v2 path differences; need docker exec with shell commands |
| docker update | memory-filling process | Unpredictable OOM behavior; requires tracking fill process PID; harder cleanup |
| docker update | docker run --memory | Requires container restart; loses in-memory state |

### I/O Latency Alternatives

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| DEFER | dm-delay | Requires privileged containers; complex setup/cleanup; high failure risk |
| DEFER | blkio throttle | Only controls bandwidth/IOPS, not latency; doesn't simulate slow disk |
| DEFER | tc netem | Only works on network interfaces, not block devices |

## Installation

Update subjects/tikv/Dockerfile.tikv-chaos:

```dockerfile
# TiKV image with chaos engineering tools
# Adds iproute-tc (tc command), iptables for network chaos injection
# Base: Rocky Linux 9

FROM pingcap/tikv:v8.5.5

# Install chaos tools (runs as root, same as base image)
RUN dnf install -y \
    iproute-tc \
    iptables \
    util-linux \
    stress-ng \
    && dnf clean all

# Verify tools are available
RUN tc -V && iptables --version && fallocate --help | head -1 && stress-ng --version
```

**No docker-compose.yaml changes required** for cpu_pressure and memory_pressure.

## Implementation Patterns

### CPU Pressure Implementation

```python
async def inject_cpu_pressure(
    docker: DockerClient, target_container: str, duration_sec: int = 300
) -> dict[str, Any]:
    """Inject CPU pressure using stress-ng.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to stress
        duration_sec: How long to run stress test (default 300s = 5min)

    Returns:
        Chaos metadata dict with target_container, duration_sec
    """
    # Run stress-ng in background (-d flag to docker exec)
    # --cpu 0 means stress all CPU cores
    # --timeout ensures automatic cleanup
    cmd = f"stress-ng --cpu 0 --timeout {duration_sec}s"
    await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", cmd], detach=True
    )

    return {
        "chaos_type": "cpu_pressure",
        "target_container": target_container,
        "duration_sec": duration_sec,
    }


async def cleanup_cpu_pressure(docker: DockerClient, target_container: str) -> None:
    """Clean up CPU pressure by killing stress-ng processes.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
    """
    try:
        # Kill all stress-ng processes
        await asyncio.to_thread(
            docker.execute, target_container, ["pkill", "stress-ng"]
        )
    except Exception as e:
        # stress-ng may have already timed out
        logger.debug(f"Failed to cleanup CPU pressure on {target_container}: {e}")
```

### Memory Pressure Implementation

```python
async def inject_memory_pressure(
    docker: DockerClient, target_container: str, limit_mb: int = 512
) -> dict[str, Any]:
    """Inject memory pressure by setting container memory limit.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to limit
        limit_mb: Memory limit in megabytes (default 512MB)

    Returns:
        Chaos metadata dict with target_container, limit_mb, original_memory_bytes
    """
    # Capture original memory limit
    inspect_data = await asyncio.to_thread(docker.container.inspect, target_container)
    original_memory = inspect_data.host_config.memory  # 0 = unlimited

    # Convert MB to bytes for docker API
    limit_bytes = limit_mb * 1024 * 1024

    # Apply memory limit via cgroups
    await asyncio.to_thread(
        docker.container.update, target_container, memory=limit_bytes
    )

    return {
        "chaos_type": "memory_pressure",
        "target_container": target_container,
        "limit_mb": limit_mb,
        "original_memory_bytes": original_memory,
    }


async def cleanup_memory_pressure(
    docker: DockerClient, target_container: str, original_memory_bytes: int
) -> None:
    """Clean up memory pressure by restoring original limit.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to restore
        original_memory_bytes: Original memory limit (0 = unlimited)
    """
    try:
        # Restore original memory limit
        await asyncio.to_thread(
            docker.container.update, target_container, memory=original_memory_bytes
        )
    except Exception as e:
        # Container may have restarted or been removed
        logger.debug(f"Failed to cleanup memory pressure on {target_container}: {e}")
```

## Testing Verification

Before implementing chaos types, verify tools work in containers:

### Verify stress-ng
```bash
# Build updated image
docker-compose -f subjects/tikv/docker-compose.yaml build tikv0

# Start cluster
docker-compose -f subjects/tikv/docker-compose.yaml up -d

# Test stress-ng (should peg CPU for 10s)
docker exec tikv-tikv0-1 stress-ng --cpu 0 --timeout 10s

# Verify cleanup
docker exec tikv-tikv0-1 pgrep stress-ng  # Should return nothing
```

### Verify docker update memory limits
```bash
# Check current memory limit (should be 0 = unlimited)
docker inspect tikv-tikv0-1 | jq '.[0].HostConfig.Memory'

# Apply 512MB limit
docker update --memory=512m tikv-tikv0-1

# Verify limit applied
docker inspect tikv-tikv0-1 | jq '.[0].HostConfig.Memory'
# Should show: 536870912 (512MB in bytes)

# Restore unlimited
docker update --memory=0 tikv-tikv0-1
```

## Confidence Assessment

| Chaos Type | Confidence | Rationale |
|------------|------------|-----------|
| cpu_pressure (stress-ng) | HIGH | stress-ng in Rocky Linux 9 repos; tested pattern from existing chaos types; clean timeout/cleanup |
| memory_pressure (docker update) | HIGH | Docker API well-documented; cgroups v2 stable; python-on-whales wraps update; reversible |
| io_latency (dm-delay) | MEDIUM | dm-delay documented but requires privileged containers; high complexity; recommend defer |

## Sources

### CPU Pressure (stress-ng)
- [stress-ng Docker usage](https://serverspace.io/support/help/what-is-stress-in-docker-and-why-do-i-need-it/)
- [stress-ng RPM for Rocky Linux 9](https://rockylinux.pkgs.org/9/rockylinux-devel-x86_64/stress-ng-0.15.00-1.el9.x86_64.rpm.html)
- [stress-ng manual page](https://manpages.ubuntu.com/manpages/focal/man1/stress-ng.1.html)
- [pkill process management](https://linuxconfig.org/how-to-kill-process-by-name)

### Memory Pressure (docker update + cgroups)
- [Docker Resource Constraints](https://docs.docker.com/engine/containers/resource_constraints/)
- [Docker Resource Limits Guide 2026](https://eastondev.com/blog/en/posts/dev/20251218-docker-resource-limits-guide/)
- [Managing Docker Resources with Cgroups](https://medium.com/@maheshwar.ramkrushna/managing-docker-resources-with-cgroups-a-practical-guide-169289c80451)
- [Linux cgroups Explained 2026](https://medium.com/@dmosyan/linux-cgroups-explained-how-containers-use-it-c99eebb8c9c6)

### I/O Latency (dm-delay research)
- [dm-delay Linux Kernel Documentation](https://docs.kernel.org/admin-guide/device-mapper/delay.html)
- [Emulating Disk Latency with dm-delay (Oracle Linux Blog, Jan 2026)](https://blogs.oracle.com/linux/emulating-disk-latency-with-dm-delay)
- [tc netem manual page](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
- [blkio cgroup controller](https://docs.kernel.org/admin-guide/cgroup-v1/blkio-controller.html)

### SIGSTOP Research (Alternative approach, not recommended)
- [Docker container pause](https://docs.docker.com/reference/cli/docker/container/pause/)
- [Docker pause vs SIGSTOP](https://last9.io/blog/pausing-docker-containers/)
- [Docker container kill](https://docs.docker.com/reference/cli/docker/container/kill/)
