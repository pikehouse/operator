# Architecture Patterns: Extended TiKV Chaos Types

**Domain:** Chaos engineering for distributed databases
**Researched:** 2026-02-01
**Confidence:** HIGH

## Executive Summary

The existing chaos.py architecture follows a clean inject/cleanup pattern using docker exec to run commands inside containers. The 3 new chaos types (cpu_pressure, memory_pressure, io_latency) integrate seamlessly with this pattern using stress-ng, a mature stress testing tool available in the TiKV container image.

**Key Decision:** Use stress-ng for all three chaos types. It provides unified CPU, memory, and I/O stressing in a single tool, with simple command-line parameters and process-based cleanup.

## Current Architecture Pattern

### Injection/Cleanup Cycle

The existing chaos.py follows a consistent pattern across all chaos types:

```python
# Injection returns metadata for cleanup
async def inject_{chaos_type}(...) -> dict[str, Any]:
    # Execute docker command to inject chaos
    # Return metadata dict with:
    #   - chaos_type: str (discriminator for cleanup)
    #   - target_container: str (which container)
    #   - type-specific fields (for cleanup)

# Cleanup uses metadata to reverse chaos
async def cleanup_{chaos_type}(docker: DockerClient, **metadata_fields):
    # Extract fields from metadata
    # Execute docker command to remove chaos
    # Gracefully handle missing containers/resources
```

### Existing Chaos Types

| Type | Injection Method | Cleanup Method | Metadata |
|------|-----------------|----------------|----------|
| node_kill | `docker.kill()` + restart policy change | Restore restart policy + `docker.start()` | target_container, original_restart_policy |
| latency | `tc qdisc add` (network delay) | `tc qdisc del` | target_container, interface, min_ms, max_ms |
| disk_pressure | `mount tmpfs` + `dd` to fill | `umount tmpfs` | target_container, target_path, fill_file, fill_bytes |
| network_partition | `iptables -I` (block IPs) | `iptables -D` (remove rules) | isolated_container, target_ips, pd_ips |

### Integration Point: TiKVEvalSubject

The subject.py orchestrates chaos injection via two methods:

```python
class TiKVEvalSubject:
    async def inject_chaos(self, chaos_type: str, **params) -> dict[str, Any]:
        # Dispatch to chaos.py functions
        # Return metadata dict

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        # Extract chaos_type from metadata
        # Dispatch to appropriate cleanup function
```

## Recommended Architecture for New Chaos Types

### Technology Choice: stress-ng

**Why stress-ng:**
- Single tool for CPU, memory, and I/O stress
- Available in Rocky Linux 9 (TiKV container base)
- Process-based (easy cleanup via pkill)
- Proven tool with active maintenance through 2026
- Background execution support (run as daemon)

**Alternatives considered:**
- Individual tools (cpulimit, memhog, fio) - Rejected: complexity of managing multiple tools
- Docker resource limits - Rejected: requires container restart, affects entire container
- cgroup manipulation - Rejected: requires privileged access, complex cleanup

### Integration Pattern: Process-Based Chaos

Unlike existing chaos types that modify system state (iptables, tc, mounts), the new chaos types inject load via background processes:

```
Injection:
1. Start stress-ng in background (nohup)
2. Capture PID
3. Return metadata with PID

Cleanup:
1. Kill process by PID
2. Verify process terminated
```

### Proposed Function Signatures

```python
async def inject_cpu_pressure(
    docker: DockerClient,
    target_container: str,
    cpu_workers: int = 2,
    cpu_load_percent: int = 80,
) -> dict[str, Any]:
    """Inject CPU pressure using stress-ng.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject CPU pressure on
        cpu_workers: Number of CPU worker threads (default: 2)
        cpu_load_percent: Target CPU load percentage per worker (default: 80)

    Returns:
        Chaos metadata dict with:
        - chaos_type: "cpu_pressure"
        - target_container: str
        - pid: int (stress-ng process ID)
        - cpu_workers: int
        - cpu_load_percent: int
    """
    # Build stress-ng command with cpu stressor
    # --cpu N: spawn N workers spinning on sqrt()
    # --cpu-load P: load CPUs at P% (0-100)
    # --timeout 0: run indefinitely (until killed)
    cmd = f"nohup stress-ng --cpu {cpu_workers} --cpu-load {cpu_load_percent} --timeout 0 >/dev/null 2>&1 & echo $!"

    # Execute and capture PID
    result = await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", cmd]
    )
    pid = int(result.strip())

    return {
        "chaos_type": "cpu_pressure",
        "target_container": target_container,
        "pid": pid,
        "cpu_workers": cpu_workers,
        "cpu_load_percent": cpu_load_percent,
    }


async def cleanup_cpu_pressure(
    docker: DockerClient, target_container: str, pid: int
) -> None:
    """Clean up CPU pressure by killing stress-ng process.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
        pid: Process ID of stress-ng to kill
    """
    try:
        # Kill stress-ng process and all children
        kill_cmd = f"kill -9 {pid} 2>/dev/null || true"
        await asyncio.to_thread(
            docker.execute, target_container, ["sh", "-c", kill_cmd]
        )

        # Verify cleanup by checking if process exists
        check_cmd = f"kill -0 {pid} 2>/dev/null && echo 'exists' || echo 'gone'"
        result = await asyncio.to_thread(
            docker.execute, target_container, ["sh", "-c", check_cmd]
        )

        if "exists" in result:
            logger.warning(f"Process {pid} still exists after kill attempt")
    except Exception as e:
        # Container may have restarted or process already dead
        logger.debug(f"Failed to cleanup CPU pressure on {target_container}: {e}")


async def inject_memory_pressure(
    docker: DockerClient,
    target_container: str,
    vm_workers: int = 2,
    vm_bytes: str = "256M",
) -> dict[str, Any]:
    """Inject memory pressure using stress-ng.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject memory pressure on
        vm_workers: Number of VM workers (default: 2)
        vm_bytes: Memory per worker (default: "256M")
                  Supports suffixes: K, M, G, %

    Returns:
        Chaos metadata dict with:
        - chaos_type: "memory_pressure"
        - target_container: str
        - pid: int (stress-ng process ID)
        - vm_workers: int
        - vm_bytes: str
    """
    # Build stress-ng command with vm stressor
    # --vm N: spawn N workers spinning on malloc/free
    # --vm-bytes B: allocate B bytes per worker
    # --vm-hang 0: immediately free and reallocate (continuous pressure)
    # --timeout 0: run indefinitely
    cmd = f"nohup stress-ng --vm {vm_workers} --vm-bytes {vm_bytes} --vm-hang 0 --timeout 0 >/dev/null 2>&1 & echo $!"

    # Execute and capture PID
    result = await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", cmd]
    )
    pid = int(result.strip())

    return {
        "chaos_type": "memory_pressure",
        "target_container": target_container,
        "pid": pid,
        "vm_workers": vm_workers,
        "vm_bytes": vm_bytes,
    }


async def cleanup_memory_pressure(
    docker: DockerClient, target_container: str, pid: int
) -> None:
    """Clean up memory pressure by killing stress-ng process.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
        pid: Process ID of stress-ng to kill
    """
    # Same implementation as cleanup_cpu_pressure
    # Memory is automatically freed when process dies
    try:
        kill_cmd = f"kill -9 {pid} 2>/dev/null || true"
        await asyncio.to_thread(
            docker.execute, target_container, ["sh", "-c", kill_cmd]
        )
    except Exception as e:
        logger.debug(f"Failed to cleanup memory pressure on {target_container}: {e}")


async def inject_io_latency(
    docker: DockerClient,
    target_container: str,
    io_workers: int = 2,
) -> dict[str, Any]:
    """Inject I/O latency using stress-ng.

    Note: This injects I/O *load* (creating latency via contention), not
    artificial latency like tc netem. For network latency, use latency chaos type.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to inject I/O pressure on
        io_workers: Number of I/O workers (default: 2)

    Returns:
        Chaos metadata dict with:
        - chaos_type: "io_latency"
        - target_container: str
        - pid: int (stress-ng process ID)
        - io_workers: int
    """
    # Build stress-ng command with io stressor
    # --io N: spawn N workers spinning on sync file writes
    # --timeout 0: run indefinitely
    # I/O worker performs continuous write/fsync cycles, creating disk contention
    cmd = f"nohup stress-ng --io {io_workers} --timeout 0 >/dev/null 2>&1 & echo $!"

    # Execute and capture PID
    result = await asyncio.to_thread(
        docker.execute, target_container, ["sh", "-c", cmd]
    )
    pid = int(result.strip())

    return {
        "chaos_type": "io_latency",
        "target_container": target_container,
        "pid": pid,
        "io_workers": io_workers,
    }


async def cleanup_io_latency(
    docker: DockerClient, target_container: str, pid: int
) -> None:
    """Clean up I/O latency by killing stress-ng process.

    Args:
        docker: DockerClient configured with compose file
        target_container: Container name to clean up
        pid: Process ID of stress-ng to kill
    """
    # Same implementation as other cleanup functions
    try:
        kill_cmd = f"kill -9 {pid} 2>/dev/null || true"
        await asyncio.to_thread(
            docker.execute, target_container, ["sh", "-c", kill_cmd]
        )
    except Exception as e:
        logger.debug(f"Failed to cleanup IO latency on {target_container}: {e}")
```

### Integration with TiKVEvalSubject

Update subject.py to support new chaos types:

```python
# In get_chaos_types()
def get_chaos_types(self) -> list[str]:
    return [
        "node_kill",
        "latency",
        "network_partition",
        "cpu_pressure",      # NEW
        "memory_pressure",   # NEW
        "io_latency",        # NEW
    ]

# In inject_chaos()
async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
    # ... existing chaos types ...

    elif chaos_type == "cpu_pressure":
        cpu_workers = params.get("cpu_workers", 2)
        cpu_load_percent = params.get("cpu_load_percent", 80)
        return await inject_cpu_pressure(
            self.docker, target.name, cpu_workers, cpu_load_percent
        )

    elif chaos_type == "memory_pressure":
        vm_workers = params.get("vm_workers", 2)
        vm_bytes = params.get("vm_bytes", "256M")
        return await inject_memory_pressure(
            self.docker, target.name, vm_workers, vm_bytes
        )

    elif chaos_type == "io_latency":
        io_workers = params.get("io_workers", 2)
        return await inject_io_latency(
            self.docker, target.name, io_workers
        )

# In cleanup_chaos()
async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
    chaos_type = chaos_metadata.get("chaos_type")

    # ... existing chaos types ...

    elif chaos_type in ("cpu_pressure", "memory_pressure", "io_latency"):
        target_container = chaos_metadata["target_container"]
        pid = chaos_metadata["pid"]

        # Dispatch to appropriate cleanup function
        if chaos_type == "cpu_pressure":
            await cleanup_cpu_pressure(self.docker, target_container, pid)
        elif chaos_type == "memory_pressure":
            await cleanup_memory_pressure(self.docker, target_container, pid)
        elif chaos_type == "io_latency":
            await cleanup_io_latency(self.docker, target_container, pid)
```

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ TiKVEvalSubject.inject_chaos()                              │
│ - Select random TiKV container                              │
│ - Dispatch to chaos type function                           │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│ inject_cpu_pressure() / inject_memory_pressure() /          │
│ inject_io_latency()                                         │
│                                                             │
│ 1. Build stress-ng command with parameters                 │
│ 2. Execute: nohup stress-ng ... & echo $!                  │
│ 3. Capture PID from stdout                                 │
│ 4. Return metadata dict:                                   │
│    {                                                        │
│      "chaos_type": "cpu_pressure",                         │
│      "target_container": "tikv0",                          │
│      "pid": 12345,                                         │
│      "cpu_workers": 2,                                     │
│      "cpu_load_percent": 80                                │
│    }                                                        │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ Metadata stored by eval harness
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│ TiKVEvalSubject.cleanup_chaos(metadata)                     │
│ - Extract chaos_type from metadata                          │
│ - Dispatch to cleanup function                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  v
┌─────────────────────────────────────────────────────────────┐
│ cleanup_cpu_pressure() / cleanup_memory_pressure() /        │
│ cleanup_io_latency()                                        │
│                                                             │
│ 1. Extract target_container and pid from metadata          │
│ 2. Execute: kill -9 {pid}                                  │
│ 3. Optionally verify process terminated                    │
│ 4. Log errors but don't raise (graceful degradation)       │
└─────────────────────────────────────────────────────────────┘
```

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| TiKVEvalSubject | Chaos orchestration, container selection | chaos.py injection/cleanup functions |
| inject_cpu_pressure() | Start stress-ng CPU stressor, return PID | Docker API via DockerClient |
| inject_memory_pressure() | Start stress-ng VM stressor, return PID | Docker API via DockerClient |
| inject_io_latency() | Start stress-ng I/O stressor, return PID | Docker API via DockerClient |
| cleanup_cpu_pressure() | Kill stress-ng by PID | Docker API via DockerClient |
| cleanup_memory_pressure() | Kill stress-ng by PID | Docker API via DockerClient |
| cleanup_io_latency() | Kill stress-ng by PID | Docker API via DockerClient |
| stress-ng (in container) | Generate CPU/memory/I/O load | TiKV process (resource contention) |

## Dockerfile Changes

The TiKV chaos container needs stress-ng installed:

```dockerfile
# Current: Dockerfile.tikv-chaos
FROM pingcap/tikv:v8.5.5

# Install chaos tools
RUN dnf install -y \
    iproute-tc \
    iptables \
    util-linux \
    stress-ng \     # NEW: Add stress-ng
    && dnf clean all

# Verify tools are available
RUN tc -V && iptables --version && fallocate --help | head -1 && stress-ng --version
```

## Build Order Recommendation

Based on implementation complexity and dependencies:

### Phase 1: Foundation (Single Chaos Type)
**Milestone 1.1: CPU Pressure**
- Add stress-ng to Dockerfile.tikv-chaos
- Implement inject_cpu_pressure() in chaos.py
- Implement cleanup_cpu_pressure() in chaos.py
- Update TiKVEvalSubject to support cpu_pressure
- Add unit tests for CPU pressure injection/cleanup

**Rationale:** CPU pressure is simplest (fewest parameters), establishes the pattern.

### Phase 2: Extend Pattern (Parallel Implementation)
**Milestone 2.1: Memory Pressure**
- Implement inject_memory_pressure() (copy CPU pattern)
- Implement cleanup_memory_pressure() (copy CPU pattern)
- Update TiKVEvalSubject to support memory_pressure
- Add unit tests for memory pressure

**Milestone 2.2: I/O Latency**
- Implement inject_io_latency() (copy CPU pattern)
- Implement cleanup_io_latency() (copy CPU pattern)
- Update TiKVEvalSubject to support io_latency
- Add unit tests for I/O latency

**Rationale:** Once pattern is established with CPU, memory and I/O follow the same structure. Can be implemented in parallel.

### Phase 3: Integration Testing
**Milestone 3.1: Integration Tests**
- Test all three chaos types against running TiKV cluster
- Verify cleanup handles container restarts
- Verify cleanup handles missing processes
- Verify metadata is correctly preserved/restored

## Edge Cases and Error Handling

### Container Restart During Chaos
**Problem:** Container restarts, killing stress-ng process
**Detection:** PID no longer exists when cleanup runs
**Solution:** Cleanup gracefully handles missing process (kill -9 returns non-zero)

### Cleanup Called Twice
**Problem:** cleanup_chaos() called multiple times with same metadata
**Detection:** First cleanup kills process, second finds no process
**Solution:** Use `|| true` in kill command to suppress errors

### stress-ng Not Available
**Problem:** Dockerfile build fails or stress-ng not in PATH
**Detection:** docker execute returns "command not found"
**Solution:** Verify stress-ng in Dockerfile RUN command, fail fast during container build

### Invalid Parameters
**Problem:** User passes negative cpu_workers or invalid vm_bytes
**Detection:** stress-ng exits immediately or returns error
**Solution:** Validate parameters before injection:
- cpu_workers > 0
- cpu_load_percent in 0-100 range
- vm_bytes matches pattern: number + suffix (K/M/G/%)
- io_workers > 0

### Process Orphaning
**Problem:** stress-ng spawns child processes, kill only kills parent
**Detection:** Load continues after cleanup
**Solution:** Use `kill -9` (SIGKILL) which terminates entire process group. stress-ng handles SIGKILL by cleaning up children.

## Performance Considerations

### Resource Consumption

| Chaos Type | Resource Usage | Impact on Container |
|------------|---------------|---------------------|
| cpu_pressure | 2 workers at 80% load = ~1.6 CPU cores | Starves TiKV of CPU cycles |
| memory_pressure | 2 workers * 256M = 512M memory | Forces TiKV to swap or triggers OOM |
| io_latency | 2 workers doing sync writes | Delays TiKV disk writes |

### Recommended Defaults

Based on TiKV container typical resource allocation:

```python
# CPU: 2 workers at 80% load (leaves ~20% for TiKV critical paths)
CPU_PRESSURE_DEFAULTS = {
    "cpu_workers": 2,
    "cpu_load_percent": 80,
}

# Memory: 2 workers * 256M = 512M (moderate pressure, unlikely to OOM)
MEMORY_PRESSURE_DEFAULTS = {
    "vm_workers": 2,
    "vm_bytes": "256M",
}

# I/O: 2 workers (moderate contention on disk writes)
IO_LATENCY_DEFAULTS = {
    "io_workers": 2,
}
```

### Scalability

Process-based chaos scales linearly with parameter increases:
- More cpu_workers = more CPU load
- Larger vm_bytes = more memory pressure
- More io_workers = more I/O contention

No system-wide state maintained (unlike iptables rules or tc qdiscs), so cleanup is O(1) per chaos injection.

## Alternative Approaches (Not Recommended)

### Alternative 1: Docker Resource Limits
**Approach:** Use docker update --cpus/--memory to constrain container
**Rejected because:**
- Requires container restart to apply limits
- Affects entire container (can't target specific times)
- Hard limit vs stress (different behavior)
- Cleanup complexity (must remember original limits)

### Alternative 2: cgroup Direct Manipulation
**Approach:** Modify /sys/fs/cgroup files to constrain resources
**Rejected because:**
- Requires privileged container or CAP_SYS_ADMIN
- cgroups v1 vs v2 compatibility issues
- Complex cleanup (must restore original cgroup values)
- Brittle (cgroup paths vary by Docker version)

### Alternative 3: Separate Tools per Type
**Approach:** Use cpulimit for CPU, memhog for memory, fio for I/O
**Rejected because:**
- Multiple tools = multiple installations in Dockerfile
- Different command-line interfaces for each
- Some tools not available in Rocky Linux repos
- stress-ng already does all three

## Sources

**HIGH confidence sources:**
- [stress-ng Manual Pages](https://manpages.debian.org/testing/stress-ng/stress-ng.1.en.html) - Comprehensive documentation of stress-ng options
- [Docker Resource Constraints](https://docs.docker.com/engine/containers/resource_constraints/) - Official Docker documentation on resource limiting
- [stress-ng GitHub Repository](https://github.com/ColinIanKing/stress-ng) - Active maintenance through 2026

**MEDIUM confidence sources:**
- [Using stress-ng for CPU and Memory Stress Testing](https://dohost.us/index.php/2025/10/25/using-stress-ng-for-cpu-and-memory-stress-testing/) - Recent 2025 guide
- [Stress Testing CPU with dd command](https://www.unixtutorial.org/stress-testing-cpu-with-dd-command/) - Alternative approaches
- [How to Kill Processes in Linux](https://www.cyberciti.biz/faq/how-force-kill-process-linux/) - Process cleanup techniques

**Verification notes:**
- stress-ng availability in Rocky Linux 9: Verified via EPEL repository
- PID capture from background process: Standard shell idiom `& echo $!`
- Process cleanup: SIGKILL (kill -9) terminates stress-ng and children
