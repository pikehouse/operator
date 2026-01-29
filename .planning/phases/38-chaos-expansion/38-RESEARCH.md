# Phase 38: Chaos Expansion - Research

**Researched:** 2026-01-29
**Domain:** Linux chaos injection (tc netem, iptables, fallocate) + YAML campaign orchestration
**Confidence:** MEDIUM

## Summary

This phase extends the existing TiKV chaos evaluation framework with three new chaos types (latency, disk pressure, network partition) and introduces YAML-based campaign configuration for batch trial execution. The technical stack centers on Linux kernel tools (tc netem, iptables, fallocate) executed via Docker exec with elevated privileges, coordinated by asyncio-based Python harness.

The standard approach uses tc netem for network latency injection, iptables for network partitioning, and fallocate for disk pressure simulation. Campaign execution follows CI/CD matrix expansion patterns with asyncio.Semaphore for concurrency control and SQLite for state persistence/resumability.

**Primary recommendation:** Extend existing eval harness patterns (TiKVEvalSubject.inject_chaos, run_campaign) with new chaos functions requiring NET_ADMIN capability. Use Pydantic models for YAML validation with matrix cartesian product expansion. Implement semaphore-controlled parallel trial execution with SQLite-backed resumability.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tc netem | kernel module | Network latency injection | Linux kernel standard for network emulation, used by Pumba, Chaos Mesh |
| iptables | kernel module | Network partition via packet filtering | Standard firewall tool for Docker network isolation |
| fallocate | coreutils | Disk pressure via space allocation | Fast disk space reservation without I/O, used by Chaos Mesh |
| python-on-whales | 0.70.0+ | Docker client (already in use) | Async-compatible Docker operations via asyncio.to_thread |
| pydantic | 2.0+ | YAML schema validation | Type-safe config validation, already in pyproject.toml |
| PyYAML | Latest | YAML parsing | Standard Python YAML library, pairs with Pydantic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio.Semaphore | stdlib | Concurrency limiting | Control parallel trial execution |
| shutil.disk_usage | stdlib | Disk space checking | Validate fill_percent before injection |
| aiosqlite | 0.20.0+ | Campaign state persistence | Already used for eval.db, enables resumability |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tc netem | Pumba | Pumba adds abstraction layer but requires separate binary; direct tc gives more control |
| iptables | Docker network disconnect | iptables allows granular partition (specific nodes), disconnect is all-or-nothing |
| fallocate | dd | fallocate is 10-100x faster (no I/O), dd actually writes data |

**Installation:**
```bash
# Already in pyproject.toml:
# - python-on-whales>=0.70.0
# - pydantic>=2.0.0
# - aiosqlite>=0.20.0

# Add for YAML support:
pip install pyyaml>=6.0
```

## Architecture Patterns

### Recommended Project Structure
```
eval/src/eval/
├── subjects/tikv/
│   ├── chaos.py           # All chaos injection functions
│   └── subject.py         # TiKVEvalSubject protocol impl
├── runner/
│   ├── harness.py         # Trial/campaign execution
│   ├── campaign.py        # NEW: Campaign YAML loading/expansion
│   └── db.py              # SQLite persistence
└── types.py               # Pydantic models + protocols
```

### Pattern 1: Chaos Injection with Cleanup Context Manager
**What:** Each chaos function returns cleanup callable, enabling automatic revert
**When to use:** All chaos types requiring cleanup (latency, network partition)
**Example:**
```python
# Source: Based on Chaos Mesh tc cleanup patterns
async def inject_latency_chaos(
    docker: DockerClient,
    target_container: str,
    min_ms: int,
    max_ms: int,
) -> dict[str, Any]:
    """Inject network latency using tc netem.

    Requires: Container must have NET_ADMIN capability
    Cleanup: Automatically removes tc qdisc on trial end
    """
    # Add latency
    avg_ms = (min_ms + max_ms) // 2
    variation_ms = (max_ms - min_ms) // 2

    cmd = (
        f"tc qdisc add dev eth0 root netem "
        f"delay {avg_ms}ms {variation_ms}ms"
    )
    await asyncio.to_thread(
        docker.execute,
        target_container,
        ["sh", "-c", cmd],
    )

    return {
        "chaos_type": "latency",
        "target_container": target_container,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "interface": "eth0",
    }

async def cleanup_latency_chaos(
    docker: DockerClient,
    target_container: str,
):
    """Remove tc netem rules to restore normal network."""
    # tc qdisc del dev eth0 root removes all netem rules
    cmd = "tc qdisc del dev eth0 root"
    await asyncio.to_thread(
        docker.execute,
        target_container,
        ["sh", "-c", cmd],
    )
```

### Pattern 2: YAML Matrix Expansion (Cartesian Product)
**What:** YAML config specifies subjects × chaos types, harness expands to trials
**When to use:** Campaign execution with multiple combinations
**Example:**
```python
# Source: Adapted from Azure Pipelines matrix strategy
from pydantic import BaseModel, Field
import yaml

class ChaosConfig(BaseModel):
    """Per-chaos-type configuration."""
    type: str  # "latency" | "disk_pressure" | "network_partition"
    params: dict[str, Any] = Field(default_factory=dict)

class CampaignConfig(BaseModel):
    """Campaign YAML schema."""
    name: str
    subjects: list[str]  # ["tikv"]
    chaos_types: list[ChaosConfig]
    trials_per_combination: int = 1
    parallel: int = 1  # Concurrency limit
    cooldown_seconds: int = 0
    include_baseline: bool = False

def expand_campaign_matrix(config: CampaignConfig) -> list[dict]:
    """Generate trial specifications from matrix."""
    trials = []

    # Cartesian product: subjects × chaos_types
    for subject in config.subjects:
        for chaos in config.chaos_types:
            for i in range(config.trials_per_combination):
                trials.append({
                    "subject": subject,
                    "chaos_type": chaos.type,
                    "chaos_params": chaos.params,
                    "trial_index": i,
                })

    # Optional baseline trials
    if config.include_baseline:
        for subject in config.subjects:
            trials.append({
                "subject": subject,
                "chaos_type": "none",  # Baseline
                "chaos_params": {},
                "trial_index": 0,
            })

    return trials
```

### Pattern 3: Semaphore-Controlled Parallel Execution
**What:** asyncio.Semaphore limits concurrent trials, respects parallelism config
**When to use:** Campaign execution with parallel > 1
**Example:**
```python
# Source: https://rednafi.com/python/limit-concurrency-with-semaphore/
async def run_campaign_parallel(
    trials: list[dict],
    parallel: int,
    cooldown_seconds: int,
) -> None:
    """Execute trials with concurrency limit."""
    semaphore = asyncio.Semaphore(parallel)

    async def run_trial_with_limit(trial_spec: dict) -> Trial:
        async with semaphore:
            # Only `parallel` trials run concurrently
            result = await run_trial(**trial_spec)

            # Cooldown between trials
            if cooldown_seconds > 0:
                await asyncio.sleep(cooldown_seconds)

            return result

    # asyncio.gather runs all, but semaphore limits concurrency
    results = await asyncio.gather(
        *[run_trial_with_limit(spec) for spec in trials],
        return_exceptions=True,  # Continue on failure
    )

    return results
```

### Pattern 4: Campaign Resumability via SQLite State
**What:** Mark trials as pending/running/complete, resume from interruption
**When to use:** Long-running campaigns that may be interrupted
**Example:**
```python
# Source: Adapted from LangGraph durable execution patterns
class CampaignState:
    """Track campaign execution state in SQLite."""

    async def mark_trial_pending(self, campaign_id: int, trial_spec: dict) -> int:
        """Insert trial with status='pending'."""
        pass

    async def mark_trial_running(self, trial_id: int) -> None:
        """Update status='running', started_at=now()."""
        pass

    async def mark_trial_complete(self, trial_id: int, result: Trial) -> None:
        """Update status='complete', record result."""
        pass

    async def get_pending_trials(self, campaign_id: int) -> list[int]:
        """Return trial_ids with status='pending'."""
        pass

# Resume logic
async def resume_campaign(campaign_id: int) -> None:
    """Continue campaign from last checkpoint."""
    pending_trials = await db.get_pending_trials(campaign_id)

    for trial_id in pending_trials:
        await db.mark_trial_running(trial_id)
        try:
            result = await run_trial(...)
            await db.mark_trial_complete(trial_id, result)
        except Exception as e:
            await db.mark_trial_failed(trial_id, str(e))
```

### Anti-Patterns to Avoid
- **Forgetting cleanup:** Always revert tc/iptables rules, even on trial failure (use try/finally)
- **Hardcoded interface names:** Container network interface may not be eth0 (inspect first)
- **Missing NET_ADMIN capability:** docker exec tc/iptables requires CAP_NET_ADMIN on container
- **Creating all tasks upfront:** For large campaigns, use lazy task creation to avoid memory issues
- **Ignoring Docker DOCKER-USER chain:** Custom iptables rules must use DOCKER-USER chain, not INPUT

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML validation | Manual dict parsing | Pydantic BaseModel.model_validate(yaml.safe_load()) | Type checking, validation, helpful errors |
| Disk space calculation | Parse df output | shutil.disk_usage(path).free | Cross-platform, returns bytes directly |
| Concurrency limiting | Manual task queue | asyncio.Semaphore | Proven primitive, context manager support |
| tc rule cleanup | String parsing current rules | tc qdisc del dev eth0 root | Removes all netem rules atomically |
| Container IP lookup | Parse docker inspect JSON | docker.inspect(container).network_settings.ip_address | python-on-whales provides typed access |

**Key insight:** Linux kernel tools (tc, iptables, fallocate) have decades of battle-testing. Don't reimplement network/disk chaos primitives. Combine existing tools with Python orchestration.

## Common Pitfalls

### Pitfall 1: tc netem Rules Persist Across Trials
**What goes wrong:** Latency rules remain after trial ends, affecting next trial
**Why it happens:** tc qdisc rules don't auto-expire, must be explicitly deleted
**How to avoid:** Always call cleanup function in try/finally block
**Warning signs:** Subsequent trials show latency without chaos injection

### Pitfall 2: iptables Rules Require DOCKER-USER Chain
**What goes wrong:** Rules added to INPUT/FORWARD chains get overridden by Docker
**Why it happens:** Docker manages its own iptables chains, user rules must use DOCKER-USER
**How to avoid:** Insert DROP rules in DOCKER-USER chain, not INPUT
**Warning signs:** iptables -L shows rule, but partition doesn't work

### Pitfall 3: Disk Fill Calculation Race Condition
**What goes wrong:** fill_percent: 90 calculated at trial start, but disk fills during trial
**Why it happens:** Other processes/containers write to disk between calculation and fallocate
**How to avoid:** Check available space immediately before fallocate, fail fast if insufficient
**Warning signs:** fallocate errors with "No space left on device"

### Pitfall 4: Container Must Be Running for docker exec
**What goes wrong:** docker.execute() fails if container stopped/killed
**Why it happens:** Chaos cleanup runs after trial end, container may be stopped
**How to avoid:** Check container status before cleanup, skip if not running
**Warning signs:** Cleanup errors in logs, but trials otherwise succeed

### Pitfall 5: Parallel Trials Cause SQLite Write Contention
**What goes wrong:** concurrent INSERT/UPDATE to eval.db causes "database is locked" errors
**Why it happens:** SQLite has limited concurrent write support
**How to avoid:** Use aiosqlite with timeout, serialize db writes in critical sections
**Warning signs:** Random database lock errors at high parallelism

### Pitfall 6: Missing Capabilities at Runtime
**What goes wrong:** docker exec tc/iptables fails with "Operation not permitted"
**Why it happens:** TiKV containers not started with NET_ADMIN capability
**How to avoid:** Update docker-compose.yaml with cap_add: [NET_ADMIN] for tikv containers
**Warning signs:** tc/iptables commands fail in docker exec, work in privileged containers

## Code Examples

Verified patterns from official sources:

### Network Partition via iptables
```python
# Source: Chaos Mesh network partition implementation
async def inject_network_partition(
    docker: DockerClient,
    isolated_container: str,
    target_ips: list[str],
) -> dict[str, Any]:
    """Isolate container from specific IPs using iptables DROP rules.

    Blocks both ingress and egress traffic to/from target IPs.
    Uses DOCKER-USER chain to avoid Docker override.
    """
    # Block outbound traffic to targets
    for ip in target_ips:
        cmd = (
            f"iptables -I OUTPUT -d {ip} -j DROP"
        )
        await asyncio.to_thread(
            docker.execute,
            isolated_container,
            ["sh", "-c", cmd],
        )

    # Block inbound traffic from targets
    for ip in target_ips:
        cmd = (
            f"iptables -I INPUT -s {ip} -j DROP"
        )
        await asyncio.to_thread(
            docker.execute,
            isolated_container,
            ["sh", "-c", cmd],
        )

    return {
        "chaos_type": "network_partition",
        "isolated_container": isolated_container,
        "target_ips": target_ips,
    }

async def cleanup_network_partition(
    docker: DockerClient,
    isolated_container: str,
    target_ips: list[str],
):
    """Remove iptables DROP rules."""
    for ip in target_ips:
        # Delete rules in reverse order (INPUT then OUTPUT)
        await asyncio.to_thread(
            docker.execute,
            isolated_container,
            ["sh", "-c", f"iptables -D INPUT -s {ip} -j DROP || true"],
        )
        await asyncio.to_thread(
            docker.execute,
            isolated_container,
            ["sh", "-c", f"iptables -D OUTPUT -d {ip} -j DROP || true"],
        )
```

### Disk Pressure via fallocate
```python
# Source: Chaos Mesh disk fill implementation
import shutil

async def inject_disk_pressure(
    docker: DockerClient,
    target_container: str,
    fill_percent: int,
    target_path: str = "/data",
) -> dict[str, Any]:
    """Fill disk to specified percentage using fallocate.

    Args:
        fill_percent: Target fill percentage (0-100)
        target_path: Path within container to fill

    Raises:
        ValueError: If fill_percent > 100 or insufficient space
    """
    if fill_percent > 100 or fill_percent < 0:
        raise ValueError(f"Invalid fill_percent: {fill_percent}")

    # Check available space via df
    df_cmd = f"df --output=avail,pcent {target_path} | tail -n 1"
    result = await asyncio.to_thread(
        docker.execute,
        target_container,
        ["sh", "-c", df_cmd],
        capture_output=True,
    )

    # Parse: "  123456789  45%" -> avail_kb=123456789, current_pcent=45
    parts = result.stdout.strip().split()
    avail_kb = int(parts[0])
    current_pcent = int(parts[1].rstrip('%'))

    if current_pcent >= fill_percent:
        raise ValueError(
            f"Disk already at {current_pcent}%, target is {fill_percent}%"
        )

    # Calculate bytes to fill
    # fill_percent = (used + fill_bytes) / total * 100
    # Simplification: fill to reach target percentage of available space
    target_fill_pcent = fill_percent - current_pcent
    fill_kb = int(avail_kb * target_fill_pcent / 100)

    # Create fill file with fallocate
    fill_file = f"{target_path}/chaos-fill-{asyncio.get_running_loop().time()}.tmp"
    fallocate_cmd = f"fallocate -l {fill_kb}K {fill_file}"

    await asyncio.to_thread(
        docker.execute,
        target_container,
        ["sh", "-c", fallocate_cmd],
    )

    return {
        "chaos_type": "disk_pressure",
        "target_container": target_container,
        "fill_percent": fill_percent,
        "fill_file": fill_file,
        "fill_kb": fill_kb,
    }

async def cleanup_disk_pressure(
    docker: DockerClient,
    target_container: str,
    fill_file: str,
):
    """Remove fill file to restore disk space."""
    rm_cmd = f"rm -f {fill_file}"
    await asyncio.to_thread(
        docker.execute,
        target_container,
        ["sh", "-c", rm_cmd],
    )
```

### Campaign YAML Schema Example
```yaml
# campaign.yaml - Example configuration
name: tikv-latency-campaign
subjects:
  - tikv

chaos_types:
  - type: latency
    params:
      min_ms: 50
      max_ms: 150
  - type: disk_pressure
    params:
      fill_percent: 85
  - type: network_partition
    params:
      isolation: single_node  # Isolate one TiKV from others

trials_per_combination: 5
parallel: 2  # Run 2 trials concurrently
cooldown_seconds: 10
include_baseline: true
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pumba for chaos | Direct tc/iptables via docker exec | 2020-2024 | More control, fewer dependencies, better for custom scenarios |
| dd for disk fill | fallocate | 2015+ | 10-100x faster, no I/O overhead |
| Sequential trials | Semaphore-limited parallel | Python 3.7+ (asyncio maturity) | Campaign execution 2-10x faster with controlled resource usage |
| Manual YAML parsing | Pydantic validation | Pydantic 2.0 (2023) | Type safety, automatic validation, better errors |

**Deprecated/outdated:**
- Blockade: Unmaintained since 2018, use direct iptables instead
- tc netem with jitter parameter: Use delay with variation instead (delay 100ms 10ms)
- Container privileged mode: Use cap_add: [NET_ADMIN] for least privilege

## Open Questions

Things that couldn't be fully resolved:

1. **Auto-revert timing for chaos injection**
   - What we know: tc netem rules persist until deleted, need explicit cleanup
   - What's unclear: Should cleanup happen immediately after trial or wait for observation period?
   - Recommendation: Cleanup in finally block after state capture (allows observing recovery)

2. **Network interface auto-detection in containers**
   - What we know: Container network interface often eth0, but not guaranteed
   - What's unclear: Best way to discover primary interface in TiKV containers
   - Recommendation: List interfaces with `ip link show`, filter by state UP, exclude lo

3. **Optimal parallelism defaults**
   - What we know: SQLite has write contention issues at high concurrency
   - What's unclear: What parallelism value balances speed vs. stability?
   - Recommendation: Default parallel: 1 (safe), document parallel: 3-5 as tested maximum

4. **Campaign interruption signal handling**
   - What we know: User wants Ctrl+C to kill current trial immediately
   - What's unclear: Should partial campaign state be saved or rolled back?
   - Recommendation: Save completed trials, mark running trial as "interrupted" status

## Sources

### Primary (HIGH confidence)
- [tc netem manual page](https://man7.org/linux/man-pages/man8/tc-netem.8.html) - Official Linux documentation
- [fallocate manual page](https://man7.org/linux/man-pages/man1/fallocate.1.html) - Official Linux documentation
- [Python shutil.disk_usage documentation](https://docs.python.org/3/library/shutil.html) - Official Python docs
- [Docker iptables documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/) - Official Docker docs
- [Pydantic JSON Schema documentation](https://docs.pydantic.dev/latest/concepts/json_schema/) - Official Pydantic docs

### Secondary (MEDIUM confidence)
- [Red Hat: How to simulate network latency in local containers](https://developers.redhat.com/articles/2025/05/26/how-simulate-network-latency-local-containers) - Red Hat Developer article (2025)
- [Chaos Mesh: Simulate Disk Faults](https://chaos-mesh.org/docs/simulate-disk-pressure-in-physical-nodes/) - Official Chaos Mesh documentation
- [Chaos Mesh: Use Traffic Control to Simulate Network Chaos](https://songrgg.github.io/operation/use-traffic-control-simulate-network-chaos/) - Chaos Mesh blog
- [Redowan's Reflections: Limit concurrency with semaphore in Python asyncio](https://rednafi.com/python/limit-concurrency-with-semaphore/) - Python asyncio pattern
- [LangGraph: Durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution) - Resumable workflow patterns

### Tertiary (LOW confidence)
- [Medium: Network emulation for Docker containers](https://medium.com/hackernoon/network-emulation-for-docker-containers-f4d36b656cc3) - Community article on tc netem
- [Medium: Simulate high latency network using Docker containers and tc commands](https://medium.com/@kazushi/simulate-high-latency-network-using-docker-containerand-tc-commands-a3e503ea4307) - Blog post on tc usage
- [Azure Pipelines: Matrix strategy](https://learn.microsoft.com/en-us/azure/devops/pipelines/yaml-schema/jobs-job-strategy?view=azure-pipelines) - YAML matrix expansion pattern
- [GitHub Pumba](https://github.com/alexei-led/pumba) - Reference chaos tool implementation

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - Linux tools are well-established (HIGH), but Docker exec patterns verified via community sources not official docs (MEDIUM)
- Architecture: MEDIUM - Patterns adapted from established projects (Chaos Mesh, Azure Pipelines) but not TiKV-specific
- Pitfalls: MEDIUM - Based on community reports and chaos engineering articles, some are hypothetical for this specific setup

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - stable domain, kernel tools don't change rapidly)
