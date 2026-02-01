# Domain Pitfalls: Resource Pressure Chaos in Docker

**Domain:** Resource pressure chaos injection (CPU, memory, I/O) in Docker containers
**Researched:** 2026-02-01
**Confidence:** MEDIUM-HIGH (verified with official docs and multiple sources)

## Executive Summary

Resource pressure chaos testing in Docker environments is deceptively complex. While tools like stress-ng make it trivial to generate load, proper implementation requires deep understanding of:
- Docker Desktop macOS limitations (cgroups v2 through VM)
- Process lifecycle and cleanup (orphaned processes, signal propagation)
- Cgroup behavior differences between v1 and v2
- False positives in CPU throttling metrics
- Cleanup reversibility requirements

This document catalogs pitfalls discovered through official documentation, community post-mortems, and chaos engineering tool implementations (Chaos Mesh, Pumba).

---

## Critical Pitfalls

Mistakes that cause rewrites, permanent state corruption, or major issues.

### Pitfall 1: Orphaned stress-ng Processes After Docker Exec

**What goes wrong:**
Using `docker exec` to launch stress-ng creates a process tree where the exec'd shell is not PID 1. When you kill the parent process or the `docker exec` session ends unexpectedly, child stress-ng worker processes become orphaned and continue consuming resources indefinitely.

**Why it happens:**
Docker exec spawns processes outside the container's main PID 1 process tree. When the exec session terminates:
1. The shell process exits
2. Child processes (stress-ng workers) are reparented to PID 1
3. If PID 1 doesn't handle SIGCHLD and reap zombies, workers persist
4. Standard TiKV containers don't run init systems, so PID 1 (tikv-server) doesn't reap

**Consequences:**
- Chaos "cleanup" appears successful but CPU/memory pressure continues
- Subsequent chaos injections stack on top of orphaned processes
- Container restart required to actually clean up
- Eval harness reports false cleanup success

**Prevention:**

1. **Track process groups explicitly:**
```python
# Launch with process group ID tracking
cmd = f"stress-ng --cpu 4 --timeout {duration}s --metrics"
result = docker.execute(container, ["sh", "-c", f"exec {cmd}"])
# Store PID of stress-ng parent for cleanup
```

2. **Use process group kill on cleanup:**
```python
# Kill entire process group, not just parent
cleanup_cmd = "pkill -9 stress-ng"  # Kills all stress-ng processes
await asyncio.to_thread(docker.execute, container, ["sh", "-c", cleanup_cmd])
```

3. **Verify cleanup worked:**
```python
# Check for lingering stress-ng processes
verify_cmd = "pgrep stress-ng || echo 'clean'"
result = await asyncio.to_thread(docker.execute, container, ["sh", "-c", verify_cmd])
if "clean" not in result:
    logger.warning(f"stress-ng processes still running: {result}")
```

4. **Use stress-ng's built-in timeout:**
Always specify `--timeout` flag as a safety net. If cleanup fails, processes self-terminate.

**Detection:**
- Monitor container CPU/memory after cleanup returns success
- Check process count: `docker exec <container> pgrep -c stress-ng`
- Look for "defunct" or zombie processes in `ps aux`

**Warning signs:**
- Cleanup succeeds but metrics show continued pressure
- Process count grows across chaos cycles
- Container CPU usage doesn't return to baseline

**Phase to address:** Phase 1 (Basic implementation)

---

### Pitfall 2: macOS Docker Desktop cgroups v2 Limitations

**What goes wrong:**
Docker Desktop on macOS runs containers in a Linux VM with cgroups v2. You cannot directly manipulate cgroups from inside containers the same way you would on native Linux, leading to:
- Inability to use cgroup-based memory pressure techniques
- Nested cgroup creation failing without `--privileged`
- Unexpected behavior when trying to stress test cgroup boundaries

**Why it happens:**
- macOS lacks Linux kernel features (cgroups, namespaces)
- Docker Desktop runs a single Linux VM (HyperKit/QEMU) with all containers inside
- The VM uses cgroups v2 by default (as of Docker Desktop 4.x+)
- Containers see the VM's cgroup filesystem, not host macOS
- cgroups v2 has stricter delegation rules than v1

**Consequences:**
- Techniques that work on Linux fail silently or error on macOS
- Developers get false confidence testing on macOS, prod fails on Linux
- Cannot test cgroup v1-specific behaviors (swappiness=0 vs v2 memory.swap.max)
- Documentation/examples for cgroup manipulation may not apply

**Prevention:**

1. **Use stress-ng instead of cgroup manipulation:**
```python
# WRONG: Try to manipulate cgroups directly
docker.execute(container, ["sh", "-c",
    "echo $((128*1024*1024)) > /sys/fs/cgroup/memory.max"])

# RIGHT: Use stress-ng to create memory pressure
docker.execute(container, ["sh", "-c",
    "stress-ng --vm 2 --vm-bytes 128M --timeout 30s"])
```

2. **Document platform differences explicitly:**
```python
# Add platform checks and warnings
import platform
if platform.system() == "Darwin":
    logger.warning("macOS detected: cgroup manipulation limited to VM layer")
```

3. **Test on Linux CI environment:**
Don't rely solely on macOS development testing. Use Linux CI runners for chaos validation.

4. **Avoid `--privileged` for cgroup access:**
Requiring `--privileged` defeats the purpose of container isolation in chaos testing.

**Detection:**
- Errors like "operation not permitted" when writing to cgroup files
- stress-ng works but cgroup-specific tools (systemd-run, cgexec) fail
- Different behavior between developer laptops (macOS) and CI/prod (Linux)

**Warning signs:**
- Need to add `--privileged` to make chaos work
- Dockerfile installs cgroup-tools but commands fail at runtime
- Comments like "TODO: test on Linux" in chaos code

**Phase to address:** Phase 1 (Basic implementation) - Document and test

---

### Pitfall 3: stress-ng Memory Stressors Triggering OOM Killer Instead of Pressure

**What goes wrong:**
Using stress-ng's `--vm` memory stressor without careful sizing causes the OOM killer to terminate the TiKV process instead of creating sustained memory pressure. This turns a "memory pressure" test into a "node kill" test.

**Why it happens:**
1. stress-ng's `--vm` stressor allocates memory and actively writes to it
2. Without container memory limits, it consumes host memory
3. With container memory limits, it competes with TiKV for the cgroup limit
4. OOM killer targets largest process (TiKV) when limit exceeded
5. cgroup v2 OOM killer is cgroup-aware (kills whole cgroup as unit)

**Consequences:**
- Test labeled "memory_pressure" actually kills TiKV
- Inconsistent results across runs (race between TiKV and stress-ng for OOM)
- Cannot test TiKV behavior under sustained memory pressure
- False diagnosis: "TiKV crashes under memory pressure" when OOM is expected

**Prevention:**

1. **Size stress-ng allocation relative to container limit:**
```python
# Query container memory limit first
inspect = docker.container.inspect(container_name)
memory_limit = inspect.host_config.memory  # bytes

# Use 30-50% of limit for pressure, not 100%
stress_bytes = int(memory_limit * 0.4)
cmd = f"stress-ng --vm 1 --vm-bytes {stress_bytes} --vm-keep --timeout {duration}s"
```

2. **If no limit set, set one before chaos:**
```python
# TiKV containers should have memory limits for chaos testing
if memory_limit == 0:
    raise RuntimeError(f"{container_name} has no memory limit - required for memory_pressure chaos")
```

3. **Use --vm-keep flag to maintain allocation:**
```python
# --vm-keep: allocate once and hold, don't thrash
# Better simulates sustained pressure vs. allocation storm
cmd = "stress-ng --vm 2 --vm-bytes 256M --vm-keep --timeout 60s"
```

4. **Monitor OOM kills explicitly:**
```python
# Check if OOM killer fired during chaos
oom_cmd = "grep -i 'killed process' /dev/kmsg | tail -1"
result = docker.execute(container, ["sh", "-c", oom_cmd])
if "tikv" in result.lower():
    logger.error(f"OOM killer terminated TiKV during memory pressure test")
```

5. **Consider Chaos Mesh approach (memStress):**
Chaos Mesh uses a custom memStress tool instead of stress-ng's `--vm` to avoid high CPU overhead from memory thrashing, which can mask memory pressure effects.

**Detection:**
- TiKV container exits during "memory_pressure" chaos
- Container logs show "Killed" or "OOM" messages
- `/sys/fs/cgroup/memory.oom_control` shows oom_kill count increased
- Docker events show container died with exit code 137 (128+9, SIGKILL from OOM)

**Warning signs:**
- Inconsistent chaos results (sometimes TiKV survives, sometimes dies)
- High CPU usage during "memory pressure" test (thrashing, not pressure)
- Test passes on dev (no limits) but fails in CI (with limits)

**Phase to address:** Phase 1 (Basic implementation) - stress-ng sizing logic

---

### Pitfall 4: I/O Latency Injection Without Verifying Block Device Path

**What goes wrong:**
Attempting to inject I/O latency on `/dev/sda` or similar block devices fails because:
- Docker containers don't see host block devices by default
- TiKV data directory may be on overlay filesystem, not direct block device
- macOS Docker Desktop uses VM with different device naming
- Result: Chaos injection "succeeds" but has no effect

**Why it happens:**
Docker containers use overlay filesystems (overlay2, AUFS) layered on top of host storage. The container sees:
- Virtual filesystems mounted at `/data`, `/tmp`, etc.
- No direct access to `/dev/sda`, `/dev/nvme0n1` without `--device` flag
- File I/O goes through overlay driver, not directly to block device

**Consequences:**
- I/O latency chaos reports success but TiKV sees no latency
- Developer assumes I/O chaos is working, writes tests based on false premise
- Cannot reproduce real-world disk latency issues in testing
- Tools like `tc netem` can't inject latency on filesystem paths, only network interfaces

**Prevention:**

1. **Use file I/O stressors instead of block device latency:**
```python
# Don't try to inject latency on /dev/sda
# Instead, create I/O pressure via file operations
cmd = (
    f"stress-ng --iomix 4 "  # Mixed I/O operations
    f"--temp-path /data "    # TiKV data directory
    f"--timeout {duration}s"
)
```

2. **For true I/O latency, use tools that work at VFS layer:**
```python
# fio with latency targets
cmd = (
    f"fio --name=chaos "
    f"--directory=/data "
    f"--rw=randrw "          # Random read/write
    f"--bs=4k "
    f"--size=100M "
    f"--numjobs=4 "
    f"--time_based "
    f"--runtime={duration} "
    f"--rate_iops=100"       # Limit IOPS to create queuing
)
```

3. **Or use dm-flakey kernel module (requires privileged):**
```python
# Advanced: device-mapper flakey target
# Requires --privileged and device passthrough
# Not recommended for standard chaos testing
```

4. **Document what "I/O latency" actually tests:**
```python
# Be explicit about what's being tested
def inject_io_latency_chaos(docker, container, iops_limit):
    """
    Inject I/O latency by limiting IOPS to create queuing delays.

    Note: This uses I/O rate limiting (stress-ng/fio), not true
    block device latency injection (requires dm-flakey kernel module).
    Tests application behavior under slow I/O, not specific
    device-level latency characteristics.
    """
```

**Detection:**
- TiKV metrics show no change in I/O wait time during "latency" chaos
- `iostat` in container shows normal latency
- Prometheus disk latency metrics unchanged

**Warning signs:**
- Code tries to inject latency on `/dev/sda` without `--device` flag
- No validation that latency injection actually affected I/O
- Comments like "TODO: verify this works"

**Phase to address:** Phase 2 (I/O chaos implementation) - Design validation

---

### Pitfall 5: Cleanup Failure Cascades Across Chaos Cycles

**What goes wrong:**
Chaos cleanup fails silently (container restarted, network unreachable, etc.) but harness continues to next chaos cycle. State accumulates:
- tc netem rules stack on top of each other
- iptables DROP rules compound
- Multiple stress-ng processes from different cycles
- Eventually container is unusable

**Why it happens:**
1. Cleanup functions catch exceptions and log warnings (to avoid breaking harness)
2. Container may restart between injection and cleanup (due to chaos effect)
3. When container restarts, tc rules and processes are cleared, but cleanup code doesn't know
4. Next chaos injection assumes clean state, but may be on new container

**Consequences:**
- Chaos effects accumulate unpredictably
- Later test cycles have different baseline than earlier cycles
- Cannot determine if TiKV behavior is due to current chaos or residual from previous
- Test results not reproducible

**Prevention:**

1. **Verify cleanup with explicit checks:**
```python
async def cleanup_latency_chaos(docker, container):
    try:
        # Remove tc rule
        cmd = "tc qdisc del dev eth0 root"
        await asyncio.to_thread(docker.execute, container, ["sh", "-c", cmd])
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

    # CRITICAL: Verify cleanup worked
    try:
        verify_cmd = "tc qdisc show dev eth0 | grep netem || echo 'clean'"
        result = await asyncio.to_thread(docker.execute, container, ["sh", "-c", verify_cmd])
        if "clean" not in result:
            logger.error(f"tc netem still present after cleanup: {result}")
            # Force remove all rules
            await asyncio.to_thread(docker.execute, container,
                ["sh", "-c", "tc qdisc del dev eth0 root netem || true"])
    except Exception as e:
        logger.warning(f"Cleanup verification failed: {e}")
```

2. **Track container identity to detect restarts:**
```python
# Store container ID/start time during injection
inject_data = await inject_chaos(docker, container)
container_id = (await asyncio.to_thread(docker.container.inspect, container)).id
inject_data["container_id"] = container_id

# During cleanup, check if same container
current_id = (await asyncio.to_thread(docker.container.inspect, container)).id
if current_id != inject_data["container_id"]:
    logger.info(f"Container restarted, cleanup not needed (fresh state)")
    return
```

3. **Use idempotent cleanup commands:**
```python
# Make cleanup commands safe to run multiple times
cleanup_cmd = "tc qdisc del dev eth0 root netem 2>/dev/null || true"
# The '|| true' ensures command succeeds even if rule doesn't exist
```

4. **Provide manual cleanup script:**
```bash
# cleanup-all-chaos.sh
for container in tikv0 tikv1 tikv2; do
    docker exec $container sh -c "
        tc qdisc del dev eth0 root 2>/dev/null || true
        iptables -F 2>/dev/null || true
        pkill -9 stress-ng 2>/dev/null || true
    "
done
```

**Detection:**
- Chaos effects persist after cleanup
- Baseline metrics drift over time during long-running campaigns
- Error logs show "RTNETLINK answers: File exists" (duplicate tc rules)
- Container becomes unresponsive after many chaos cycles

**Warning signs:**
- Cleanup only logs warnings, never raises exceptions
- No verification that cleanup achieved desired state
- Comments like "best effort cleanup"

**Phase to address:** Phase 1 (Basic implementation) - Cleanup verification

---

## Moderate Pitfalls

Mistakes that cause delays, flakiness, or technical debt.

### Pitfall 6: CPU Throttling False Positives from CFS Quota Bugs

**What goes wrong:**
Monitoring shows high CPU throttling (`container_cpu_cfs_throttled_seconds_total`) but actual CPU usage is low. Leads to:
- False diagnosis that CPU limits are too low
- Unnecessary increase of CPU limits
- Masking real performance issues (slow I/O, lock contention)

**Why it happens:**
Historical Linux kernel bugs (4.x, 5.4.0-1029-aws) caused CFS bandwidth controller to throttle unnecessarily due to:
- Clock skew between CPU cores causing premature quota expiration
- 100ms CFS period vs. 1-second monitoring granularity mismatch
- Bursty workloads consuming quota quickly, then idle, but metrics show throttling

**Prevention:**

1. **Monitor CPU throttling but interpret carefully:**
```python
# Don't just alert on throttling > 0
# Check throttling rate vs. CPU usage
throttle_rate = throttled_seconds_delta / period_seconds
cpu_usage_rate = cpu_usage_delta / period_seconds

if throttle_rate > 0.1 and cpu_usage_rate > 0.8:
    logger.warning("Legitimate CPU throttling: usage near limit")
elif throttle_rate > 0.1 and cpu_usage_rate < 0.5:
    logger.warning("Suspicious CPU throttling: possible CFS bug or bursty workload")
```

2. **Check kernel version for known bugs:**
```python
# Warn if on known-bad kernel
kernel_version = os.uname().release
if "5.4.0-1029" in kernel_version:
    logger.warning(f"Kernel {kernel_version} has known CFS throttling bug")
```

3. **Use CPU shares instead of hard limits for chaos:**
```python
# For CPU pressure testing, use --cpu-shares (soft limit)
# instead of --cpus (hard CFS quota limit)
# Avoids CFS quota bugs while still creating CPU contention
docker.container.update(container, cpu_shares=512)  # 50% of default 1024
```

4. **Correlate throttling with actual performance impact:**
```python
# Don't just look at throttling metric
# Check if TiKV latency actually increased
if throttle_rate > threshold and tikv_p99_latency > baseline * 1.5:
    # Real impact
else:
    # False positive throttling
```

**Detection:**
- High `cpu.stat` throttle counts but low CPU usage percentage
- Throttling occurs in short bursts matching CFS period (100ms)
- Increasing CPU limit doesn't reduce throttling proportionally

**Warning signs:**
- Alert fatigue from CPU throttling alerts
- Comments like "ignore throttling metric, it's noisy"
- Disabling CPU limits in production due to "false throttling"

**Phase to address:** Phase 3 (CPU pressure) - Metrics interpretation

---

### Pitfall 7: CAP_NET_ADMIN Security Risk Not Documented

**What goes wrong:**
TiKV containers require `CAP_NET_ADMIN` capability for tc netem (network latency chaos). This capability allows:
- Modifying host network firewall (iptables)
- Changing routing tables
- Spoofing packets
- Network access control bypass

If container is compromised, attacker has significant network control.

**Why it happens:**
`tc` command requires `CAP_NET_ADMIN` to modify network queueing disciplines. Docker Compose adds this capability for chaos testing convenience, but security implications aren't obvious.

**Prevention:**

1. **Document security tradeoff explicitly:**
```yaml
# docker-compose.yaml
tikv0:
  cap_add:
    - NET_ADMIN  # Required for tc netem network latency chaos
                 # WARNING: Allows container to modify host network config
                 # Only use in isolated test environments
```

2. **Use minimal capabilities, drop others:**
```yaml
cap_drop:
  - ALL
cap_add:
  - NET_ADMIN  # Only add what's needed
```

3. **Consider alternative without CAP_NET_ADMIN:**
```python
# Use Pumba sidecar pattern instead of in-container tc
# Pumba runs with NET_ADMIN, attaches to target container network
# Target container doesn't need elevated capabilities
docker run --cap-add NET_ADMIN --net container:tikv0 \
    gaiadocker/iproute2 tc qdisc add dev eth0 root netem delay 100ms
```

4. **Network-isolate chaos test environment:**
```yaml
# Use custom network to limit blast radius
networks:
  chaos_test_net:
    driver: bridge
    internal: true  # No external connectivity
```

**Detection:**
- Security scanner flags `CAP_NET_ADMIN` in production
- Containers can modify iptables rules unexpectedly
- Network behavior changes from compromised container

**Warning signs:**
- No comments explaining why `CAP_NET_ADMIN` is needed
- Same docker-compose.yaml used for dev and prod
- No network isolation between chaos containers and other services

**Phase to address:** Phase 0 (Planning) - Document in architecture decisions

---

### Pitfall 8: Restart Policy Conflicts with Chaos Testing

**What goes wrong:**
TiKV containers have `restart: on-failure` policy. During chaos testing:
- Container killed with SIGKILL exits with code 137
- Docker sees code 137 as failure, restarts container
- Chaos effect (node down) lasts seconds instead of intended minutes
- Or worse: Disable restart policy for chaos, forget to re-enable, production container stays down

**Why it happens:**
Existing code (node_kill chaos) updates restart policy to "no" before killing, then restores it during cleanup. But:
- If cleanup fails, policy stays "no"
- If container is manually restarted during chaos, it gets old policy
- Other chaos types don't consider restart policy

**Prevention:**

1. **Always restore restart policy in finally block:**
```python
async def inject_chaos_with_restart_handling(docker, container):
    original_policy = get_restart_policy(docker, container)
    try:
        await disable_restart(docker, container)
        await inject_chaos(docker, container)
        await asyncio.sleep(chaos_duration)
    finally:
        # ALWAYS restore, even if chaos failed
        await restore_restart_policy(docker, container, original_policy)
```

2. **Use stop instead of kill for node_down chaos:**
```python
# docker stop sends SIGTERM, waits, then SIGKILL
# Exits with code 0 (graceful), doesn't trigger on-failure restart
await asyncio.to_thread(docker.stop, container, timeout=10)
# Then disable restart policy and don't start
```

3. **Provide restart policy audit script:**
```python
# check-restart-policies.py
for container in docker.compose.ps():
    policy = get_restart_policy(docker, container.name)
    if policy != "on-failure":
        logger.error(f"{container.name} has policy '{policy}', expected 'on-failure'")
```

4. **For long-duration chaos, use pause instead of stop:**
```python
# Pause suspends all processes but keeps container "running"
# Doesn't trigger restart policy
await asyncio.to_thread(docker.pause, container)
# Resume later
await asyncio.to_thread(docker.unpause, container)
```

**Detection:**
- TiKV container restarts immediately after node_kill chaos
- Container stays down after chaos campaign finishes
- Docker events show unexpected restart activity

**Warning signs:**
- Chaos duration parameter doesn't match actual downtime
- Comments about "sometimes container restarts early"
- Manual intervention needed to restart containers after testing

**Phase to address:** Phase 1 (Basic implementation) - Refactor node_kill cleanup

---

### Pitfall 9: stress-ng Metrics Overhead Impacts Test Subject

**What goes wrong:**
stress-ng's `--metrics` flag collects detailed statistics (CPU cycles, cache misses, etc.) which itself consumes CPU and memory. During resource pressure testing, this overhead:
- Increases CPU usage beyond intended pressure
- Causes earlier OOM kills
- Pollutes CPU cache (affects TiKV performance)

**Why it happens:**
stress-ng metrics collection calls `getrusage()`, reads `/proc` files, and performs statistical calculations every second. On systems under pressure, this becomes non-trivial overhead.

**Prevention:**

1. **Omit --metrics during actual chaos injection:**
```python
# Use metrics for calibration/debugging, not production chaos
if debug_mode:
    cmd = f"stress-ng --cpu 4 --metrics --timeout {duration}s"
else:
    cmd = f"stress-ng --cpu 4 --timeout {duration}s"  # No metrics
```

2. **Use --metrics-brief for less overhead:**
```python
# Provides summary without per-stressor detailed stats
cmd = f"stress-ng --cpu 4 --metrics-brief --timeout {duration}s"
```

3. **Collect metrics externally instead:**
```python
# Monitor from Prometheus/cAdvisor instead of stress-ng internal metrics
# More realistic (production doesn't have stress-ng metrics)
```

**Detection:**
- stress-ng CPU usage higher than expected (`--cpu 4` uses >400% CPU)
- Removing `--metrics` changes chaos impact significantly
- High system CPU (vs user CPU) during stress-ng runs

**Warning signs:**
- stress-ng output includes detailed per-worker statistics
- Code always enables `--metrics` without justification

**Phase to address:** Phase 1 (Basic implementation) - Remove metrics flag

---

## Minor Pitfalls

Mistakes that cause annoyance or confusion but are fixable.

### Pitfall 10: stress-ng Installation Bloats Container Images

**What goes wrong:**
Installing stress-ng via apt requires 50+ MB of dependencies (compilers, libraries). For minimal container images, this is significant bloat.

**Prevention:**

1. **Use static binary instead:**
```dockerfile
RUN wget https://github.com/ColinIanKing/stress-ng/releases/download/V0.17.00/stress-ng-0.17.00.tar.xz \
    && tar xf stress-ng-0.17.00.tar.xz \
    && cd stress-ng-0.17.00 \
    && make -j && make install \
    && cd .. && rm -rf stress-ng-*
```

2. **Or install only at runtime via exec:**
```python
# Install stress-ng on-demand when chaos starts
await docker.execute(container, ["sh", "-c",
    "command -v stress-ng || (apt update && apt install -y stress-ng)"])
```

3. **Use existing stress (legacy) for simple cases:**
```python
# 'stress' package is smaller than stress-ng
# Sufficient for basic CPU/memory pressure
cmd = "stress --cpu 4 --timeout 60s"
```

**Phase to address:** Phase 1 (Basic implementation) - Optimize Dockerfile

---

### Pitfall 11: Hardcoded Interface Names (eth0)

**What goes wrong:**
Code assumes network interface is always `eth0`. In some Docker configurations:
- Bridge networks use `eth0`, but host networking doesn't
- Custom CNI plugins may use different names
- Code fails with "Cannot find device eth0"

**Prevention:**

1. **Query interface name at runtime:**
```python
# Find primary interface dynamically
cmd = "ip -o -4 route show to default | awk '{print $5}'"
interface = await asyncio.to_thread(docker.execute, container, ["sh", "-c", cmd])
interface = interface.strip()
```

2. **Or use wildcards:**
```python
# Apply to all interfaces (less precise but more robust)
cmd = f"tc qdisc add dev $(ip route | grep default | awk '{{print $5}}') root netem delay {ms}ms"
```

**Phase to address:** Phase 2 (Network chaos) - Dynamic interface detection

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|------------|
| Phase 1 | CPU pressure (stress-ng) | Orphaned processes after cleanup | Use pkill -9 stress-ng + verification |
| Phase 1 | CPU pressure (stress-ng) | Metrics overhead | Remove --metrics flag |
| Phase 1 | Memory pressure (stress-ng) | OOM kills TiKV instead of pressure | Size allocation to 30-40% of container limit |
| Phase 1 | All chaos types | Cleanup failures cascade | Verify cleanup with explicit state checks |
| Phase 1 | All chaos types | macOS Docker Desktop differences | Test on Linux CI, document platform limitations |
| Phase 2 | I/O latency (fio/ioping) | Block device path doesn't exist | Use file I/O stressors, not device latency |
| Phase 2 | Network latency (tc netem) | Hardcoded eth0 interface | Query interface name dynamically |
| Phase 2 | All network chaos | CAP_NET_ADMIN security risk | Document tradeoffs, consider Pumba sidecar |
| Phase 3 | CPU throttling metrics | False positives from CFS bugs | Correlate with actual latency impact |
| Phase 3 | Long-duration chaos | Restart policy conflicts | Use pause/unpause instead of stop/start |

---

## Cross-Phase Patterns

### Pattern 1: "It works on my machine" (macOS vs Linux)

**Symptom:** Chaos works in development (macOS) but fails in CI/prod (Linux), or vice versa.

**Root cause:** Docker Desktop macOS uses VM layer, different cgroup visibility.

**Solution:**
- Test on both platforms during development
- Use CI/Linux as source of truth for "correct" behavior
- Document platform-specific limitations in code comments

### Pattern 2: "Silent cleanup failures"

**Symptom:** Cleanup returns success but chaos effects persist.

**Root cause:** Catching all exceptions and logging warnings instead of verifying state.

**Solution:**
- Verify cleanup with explicit checks (e.g., `pgrep stress-ng || echo clean`)
- Return cleanup status to caller
- Provide manual cleanup scripts for disaster recovery

### Pattern 3: "Stacking chaos effects"

**Symptom:** Later chaos cycles have different impact than earlier cycles.

**Root cause:** Residual state from failed cleanups accumulating.

**Solution:**
- Use idempotent cleanup commands (`|| true`)
- Track container identity to detect restarts (fresh state)
- Reset baseline metrics between chaos cycles

---

## Confidence Assessment

| Area | Confidence | Evidence |
|------|------------|----------|
| stress-ng process cleanup | HIGH | Official Docker docs on orphaned processes, existing code patterns |
| macOS Docker Desktop limitations | MEDIUM-HIGH | GitHub issues, community forums, documented cgroups v2 behavior |
| OOM killer behavior | HIGH | Official Linux kernel docs, Chaos Mesh blog post |
| I/O latency injection | MEDIUM | Multiple tool docs (fio, ioping, Chaos Mesh), but no macOS-specific testing |
| CPU throttling false positives | MEDIUM-HIGH | Kubernetes issues with patches, multiple vendor blogs |
| CAP_NET_ADMIN security | HIGH | Docker security docs, CVE databases |
| Restart policy conflicts | MEDIUM | Pumba GitHub issues, existing code in chaos.py |
| stress-ng metrics overhead | LOW-MEDIUM | Implied from docs, not explicitly measured |

---

## Sources

### Official Documentation
- [Docker Resource Constraints](https://docs.docker.com/engine/containers/resource_constraints/)
- [Docker Start Containers Automatically](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [Linux Memory Resource Controller](https://docs.kernel.org/admin-guide/cgroup-v1/memory.html)
- [tc netem man page](https://man7.org/linux/man-pages/man8/tc-netem.8.html)

### Chaos Engineering Tools
- [Chaos Mesh: Simulate Heavy Stress on Kubernetes](https://chaos-mesh.org/docs/simulate-heavy-stress-on-kubernetes/)
- [Chaos Mesh: How to Efficiently Stress Test Pod Memory](https://chaos-mesh.org/blog/how-to-efficiently-stress-test-pod-memory/)
- [Chaos Mesh: Simulate Block Device Incidents](https://chaos-mesh.org/docs/simulate-block-chaos-on-kubernetes/)
- [Pumba: Chaos Testing Tool for Containers](https://github.com/alexei-led/pumba)

### Technical Articles (2025-2026)
- [The Complete Guide to Docker Resource Limits](https://eastondev.com/blog/en/posts/dev/20251218-docker-resource-limits-guide/) (Dec 2025)
- [Indeed Engineering: Unthrottled: Fixing CPU Limits in the Cloud](https://engineering.indeedblog.com/blog/2019/12/unthrottled-fixing-cpu-limits-in-the-cloud/)
- [Omio Engineering: CPU Limits and Aggressive Throttling in Kubernetes](https://medium.com/omio-engineering/cpu-limits-and-aggressive-throttling-in-kubernetes-c5b20bd8a718)

### Container Security
- [Container Privilege Escalation Vulnerabilities](https://www.aikido.dev/blog/container-privilege-escalation)
- [Excessive Container Capabilities](https://redfoxsec.com/blog/exploiting-excessive-container-capabilities/)
- [Docker Privileged Containers Security Risk](https://www.sourcery.ai/vulnerabilities/docker-privileged-containers)

### Process Management
- [Orphan Process Handling in Docker](https://petermalmgren.com/orphan-children-handling-containerd/)
- [Hunting Zombie Processes in Go and Docker](https://www.stormkit.io/blog/hunting-zombie-processes-in-go-and-docker)
- [Docker exec and Orphan Process Problem](https://github.com/moby/moby/issues/29700)

### Platform-Specific Issues
- [Docker for Mac cgroups v2 Issues](https://github.com/docker/for-mac/issues/6288)
- [Cgroup V2 Saga on Docker Desktop](https://forums.docker.com/t/cgroup-v2-the-saga-continues/139329)
- [Pumba restart policy issue](https://github.com/alexei-led/pumba/issues/249)

### CPU Throttling False Positives
- [Kubernetes: CFS quotas lead to unnecessary throttling](https://github.com/kubernetes/kubernetes/issues/67577)
- [Kubernetes: CPU Throttling on Linux kernel 5.4.0](https://github.com/kubernetes/kubernetes/issues/97445)
- [Last9: Kubernetes CPU Throttling](https://last9.io/blog/kubernetes-cpu-throttling/)

### Tools
- [stress-ng Official Site](http://colinianking.github.io/stress-ng/)
- [docker-iops: Fio and IOPing in Docker](https://github.com/tool-dockers/docker-iops)
- [Spencer Krum: Injecting Latency with Docker](https://spencerkrum.com/posts/inject_latency_docker/)
