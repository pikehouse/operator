# Project Research Summary: v3.3 Extended TiKV Chaos

**Project:** Operator v3.3 - Extended TiKV Failure Modes
**Domain:** Resource pressure chaos injection in Docker containers
**Researched:** 2026-02-01
**Confidence:** HIGH

## Executive Summary

This research covers adding 3 new chaos types (cpu_pressure, memory_pressure, io_latency) to the existing eval harness. The key finding is that **stress-ng provides a unified solution** for all three chaos types, requiring only a single Dockerfile addition and consistent inject/cleanup patterns.

**Scope change:** io_latency was originally envisioned as block device latency injection, but research shows this requires privileged containers and dm-delay complexity. Instead, we'll implement **I/O pressure via stress-ng's I/O stressors**, which creates latency through contention rather than artificial delay.

## Key Findings

### Recommended Stack

| Chaos Type | Tool | Implementation |
|------------|------|----------------|
| cpu_pressure | stress-ng --cpu | Spawn CPU workers that saturate cores |
| memory_pressure | stress-ng --vm | Allocate and hold memory to create pressure |
| io_latency | stress-ng --io | Spawn I/O workers to create disk contention |

**Single Dockerfile change:** Add `stress-ng` to existing dnf install line in `Dockerfile.tikv-chaos`.

**No new Python dependencies.** Uses existing docker.execute pattern.

### Expected Features

**Table stakes (agent must detect):**
- CPU: Raftstore CPU bottleneck (>85%), propose wait duration spike
- Memory: OOM kill detection (exit code 137), container restart
- I/O: Slow store score (>=80), append log duration spike

**Differentiators (advanced reasoning):**
- Multi-source correlation: Prometheus + PD API + Docker state
- Root cause chain explanation ("CPU saturation → raftstore starvation → election timeouts")
- Distinguish chaos injection from organic failure

**Anti-features (explicitly avoid):**
- Pre-scripted remediation playbooks (defeats testing purpose)
- Single-metric diagnosis (oversimplifies distributed systems)

### Architecture Approach

Follow existing chaos.py pattern:

```python
async def inject_cpu_pressure(docker, container, cpu_workers=2, cpu_load=80) -> dict:
    cmd = f"nohup stress-ng --cpu {cpu_workers} --cpu-load {cpu_load} --timeout 0 ... & echo $!"
    pid = int(docker.execute(container, cmd).strip())
    return {"chaos_type": "cpu_pressure", "target_container": container, "pid": pid, ...}

async def cleanup_cpu_pressure(docker, container, pid):
    docker.execute(container, ["sh", "-c", f"kill -9 {pid} || true"])
```

**Metadata structure:** PID-based cleanup. All three types return `pid` in metadata for kill-based cleanup.

### Critical Pitfalls

| Pitfall | Severity | Prevention |
|---------|----------|------------|
| Orphaned stress-ng processes | CRITICAL | Use `pkill -9 stress-ng` + verification |
| OOM kills TiKV instead of pressure | CRITICAL | Size memory to 30-40% of container limit |
| Cleanup failures cascade | CRITICAL | Verify cleanup with explicit state checks |
| macOS Docker Desktop differences | MODERATE | Test on Linux CI, document limitations |
| I/O latency on block device | MODERATE | Use file I/O stressors, not dm-delay |

## Implications for Roadmap

### Recommended Phases

**Phase 40: CPU Pressure**
- Add stress-ng to Dockerfile.tikv-chaos
- Implement inject_cpu_pressure / cleanup_cpu_pressure in chaos.py
- Update TiKVEvalSubject.get_chaos_types() and inject_chaos()
- Test: stress causes raftstore bottleneck, cleanup removes pressure

**Phase 41: Memory & I/O Pressure**
- Implement inject_memory_pressure / cleanup_memory_pressure
- Implement inject_io_latency / cleanup_io_latency
- Both follow same PID-based pattern from Phase 40
- Can be parallel tasks within same phase

**Phase 42: Integration Testing**
- Run campaigns with all 7 chaos types
- Verify cleanup handles container restarts
- Document agent observable symptoms for each type

### Build Order Rationale

1. **CPU first** - Establishes stress-ng pattern, simplest parameters
2. **Memory/I/O together** - Copy CPU pattern, can parallelize
3. **Integration last** - Requires all chaos types working

### Requirements to Derive

| Category | Requirements |
|----------|-------------|
| Chaos Injection | cpu_pressure type, memory_pressure type, io_latency type |
| Cleanup | PID-based cleanup, verification after cleanup |
| Integration | Update get_chaos_types(), inject_chaos(), cleanup_chaos() |
| Testing | Campaign YAML support for new types |

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack (stress-ng) | HIGH | Available in Rocky Linux 9 repos, proven tool |
| Features (symptoms) | MEDIUM-HIGH | TiKV docs confirm metrics, exact names need validation |
| Architecture | HIGH | Matches existing chaos.py pattern exactly |
| Pitfalls | HIGH | Verified across multiple chaos engineering sources |

### Gaps to Address

1. **Exact Prometheus metric names** - Need runtime validation against live TiKV
2. **stress-ng parameters for consistent pressure** - May need tuning per container size
3. **Container memory limits** - TiKV containers may need limits for memory pressure testing

## Sources

**Primary (HIGH confidence):**
- stress-ng documentation and Rocky Linux 9 packages
- Docker resource constraints documentation
- Chaos Mesh implementation patterns

**Secondary (MEDIUM confidence):**
- TiKV GitHub issues for slow store detection
- PD scheduler documentation for leader eviction

---
*Research completed: 2026-02-01*
*Ready for roadmap: yes*
