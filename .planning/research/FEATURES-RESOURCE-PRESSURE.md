# Feature Landscape: TiKV Chaos Types - CPU, Memory, I/O Pressure

**Domain:** Distributed Database Chaos Engineering - TiKV Eval Harness
**Researched:** 2026-02-01
**Milestone Context:** Subsequent milestone adding 3 new chaos types to existing harness

## Executive Summary

This research documents observable symptoms, detection patterns, and remediation strategies for three new TiKV chaos types: cpu_pressure, memory_pressure, and io_latency. The eval harness already supports node_kill, latency, disk_pressure, and network_partition. The new chaos types test the agent's ability to diagnose resource exhaustion scenarios that manifest differently than hard failures.

**Key insight:** Unlike existing chaos types that create binary failure states (dead node, partitioned network), resource pressure chaos creates degraded states with cascading symptoms. Agent must correlate metrics across Prometheus, PD API, and logs to diagnose root cause.

## Table Stakes Features

Features the agent MUST detect and respond to. Missing these = agent fails basic diagnostic reasoning.

### CPU Pressure Detection

| Feature | Why Expected | Complexity | Observable Symptoms |
|---------|--------------|------------|---------------------|
| Raftstore CPU bottleneck detection | When CPU >= 85%, raftstore becomes busy and can't process requests | Medium | - `tikv_thread_cpu{name="raftstore"}` metric >= 85%<br>- Propose wait duration >> 100ms (vs normal 50ms)<br>- Grafana: "Raft store CPU" panel shows spike |
| Raft election timeout correlation | High CPU causes tick processing delays, triggers elections | Medium | - Docker logs: "election timeout" messages<br>- Metrics: increase in election counts<br>- Multiple stores showing leader changes |
| Propose wait duration spike | Backlog of requests waiting for raftstore thread | Low | - Prometheus: `tikv_raftstore_request_wait_time_duration` histogram<br>- Grafana: "Propose wait duration" > 100ms sustained |
| Leader transfer detection | PD automatically evicts leaders from slow stores | Low | - PD API `/pd/api/v1/stores` shows leader count dropping on affected store<br>- Metrics: `tikv_pd_heartbeat_message_total` shows leader transfer operators |

**Detection strategy:**
1. Query Prometheus for `tikv_thread_cpu{name="raftstore"}` - if >= 85%, investigate
2. Check propose wait duration - sustained > 100ms indicates raftstore bottleneck
3. Correlate with PD store stats - leader count drop confirms slow store detection
4. Check docker logs for "election timeout" patterns

### Memory Pressure Detection

| Feature | Why Expected | Complexity | Observable Symptoms |
|---------|--------------|------------|---------------------|
| Block cache pressure detection | RocksDB block-cache is 40% of system memory by default | Medium | - Prometheus: `tikv_engine_block_cache_size_bytes` approaching limit<br>- Grafana: "Block cache size" panel shows sustained high usage |
| OOM kill detection | Container killed when memory exceeds cgroup limit | Low | - Docker logs: "OOMKilled" exit code 137<br>- Container state changes from Running to Exited<br>- PD API shows store going from Up to Down/Disconnected |
| Lock contention memory spike | High-concurrency lock scenarios create long wait queues | High | - Docker logs: lock manager warnings<br>- Metrics: `tikv_lock_manager_waiter_lifetime_duration` spike<br>- Memory grows faster than block cache explains |
| Process restart detection | Container auto-restart after OOM | Low | - Docker inspect shows recent restart timestamp<br>- Store downtime in PD heartbeat gaps<br>- Metrics reset (counters drop to 0) |

**Detection strategy:**
1. Query Docker container state for exit code 137 (OOM killed)
2. Check Prometheus for memory metrics approaching limits
3. Correlate with PD API store state - Down/Disconnected after OOM
4. Check container restart count and timestamps via `docker inspect`

### I/O Latency Detection

| Feature | Why Expected | Complexity | Observable Symptoms |
|---------|--------------|------------|---------------------|
| Slow store score detection | TiKV reports SlowScore 1-100, >= 80 triggers slow store scheduler | Medium | - Prometheus: `tikv_raftstore_slow_score` >= 80<br>- PD API: store slow_score field in `/pd/api/v1/stores` response<br>- Grafana: slow score trending upward |
| Append log duration spike | Slow disk causes Raft log writes to stall | Medium | - Prometheus: `tikv_raftstore_append_log_duration_seconds` >> baseline<br>- Grafana: "Append log duration" panel shows p99 spike<br>- Normal: <50ms, Degraded: 200-500ms |
| I/O utilization correlation | Disk saturation visible in system metrics | Low | - Prometheus: `tikv_engine_write_stall` counter increases<br>- Metrics: I/O wait time percentage high<br>- RocksDB compaction delays |
| PD evict-slow-store-scheduler | PD automatically schedules leaders away from slow store | Medium | - PD API `/pd/api/v1/schedulers` shows evict-slow-store-scheduler active<br>- Store leader count drops automatically<br>- Region operators show leader transfers |

**Detection strategy:**
1. Query Prometheus for `tikv_raftstore_slow_score` - if >= 80, store is slow
2. Check append log duration - sustained spike indicates I/O bottleneck
3. Query PD API `/pd/api/v1/stores` for slow_score field confirmation
4. Verify PD has activated evict-slow-store-scheduler automatically

## Differentiators

Advanced detection/remediation that demonstrates sophisticated diagnostic reasoning.

### Advanced Correlation

| Feature | Value Proposition | Complexity | Implementation |
|---------|-------------------|------------|----------------|
| Multi-metric root cause analysis | Distinguish CPU vs I/O vs memory by metric patterns | High | Compare raftstore CPU, append log duration, and memory metrics simultaneously. CPU pressure: high CPU + normal I/O. I/O pressure: normal CPU + high append duration. |
| Cascading failure detection | Identify secondary symptoms caused by primary resource exhaustion | High | Track timeline: resource exhaustion → slow store score → leader eviction → rebalance storm → cluster-wide degradation |
| Pre-OOM prediction | Detect memory pressure before OOM kill | Medium | Monitor memory trend + allocation rate. If `memory_used / memory_limit > 0.9` and growing, predict OOM imminent |
| Store recovery validation | Confirm resource pressure resolved and store healthy | Medium | After remediation, verify: slow_score drops below 80, leader count stabilizes, propose wait duration returns to baseline (<50ms) |

### Proactive Remediation

| Feature | Value Proposition | Complexity | Implementation |
|---------|-------------------|------------|----------------|
| Manual leader transfer | Agent transfers leaders away from stressed store | Medium | Use PD API: `POST /pd/api/v1/operators` with transfer-leader operator payload. Faster than waiting for automatic eviction. |
| Store drain before failure | Proactively drain store showing pre-failure symptoms | High | Add evict-leader-scheduler via `POST /pd/api/v1/schedulers`, drain all leaders, then investigate/restart container |
| Chaos injection cleanup | Detect chaos is ongoing and stop it before fixing symptoms | Medium | Recognize stress-ng processes in container, kill them before attempting other remediation |
| Container restart with investigation | Restart OOM'd container but preserve crash diagnostics | Medium | Capture logs before restart, check memory.max cgroup setting, verify no resource leak before restarting |

### Diagnostic Reasoning

| Feature | Value Proposition | Complexity | Implementation |
|---------|-------------------|------------|----------------|
| Explain symptom causation | Not just "store is slow" but "CPU saturation causes raftstore backlog" | High | Generate explanations: "Store X has CPU usage 95%. This causes raftstore thread starvation. Request backlog creates propose wait duration of 300ms. PD detects slow store and evicts leaders." |
| Distinguish chaos from real failure | Recognize artificial stress vs organic failure | Medium | Check for stress-ng/dd processes, look for tc/iptables rules, check for chaos metadata patterns |
| Time-series analysis | Understand when problem started and progression | Medium | Query Prometheus range queries to build timeline: "CPU spiked at T0, slow score increased at T0+30s, leader eviction started at T0+60s" |
| Cross-store impact assessment | Identify which regions/leaders affected | High | Query PD for regions on affected store, check if other stores seeing increased load from rebalancing |

## Anti-Features

Features to explicitly NOT build. Common mistakes in chaos engineering.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Pre-scripted remediation playbooks | Defeats purpose of testing agent reasoning | Agent should diagnose from first principles using available observability, not match symptoms to hardcoded playbooks |
| Chaos type detection from metadata | Agent shouldn't know chaos was injected | Agent should diagnose "store X is slow" not "cpu_pressure chaos was injected". Evaluation verifies agent reaches correct conclusion without knowing ground truth. |
| Immediate container restart | Masks diagnostic opportunity | Agent should investigate WHY container died/slow before restarting. Capture state, analyze metrics, propose root cause. |
| Single-metric diagnosis | Oversimplifies distributed system behavior | Always correlate multiple signals: metrics + logs + PD state + container state. Example: high CPU alone doesn't explain problem - need to see raftstore CPU specifically. |
| Ignoring PD automatic healing | Fighting against PD's built-in resilience | Recognize when PD's evict-slow-store-scheduler already handling the issue. Agent should validate automatic healing worked, not duplicate effort. |

## Observable Data Sources

What the agent can query to gather evidence.

### Prometheus Metrics (http://localhost:9090)

**CPU Metrics:**
- `tikv_thread_cpu{name="raftstore"}` - Raftstore thread CPU utilization (0-1 per core)
- `tikv_thread_cpu{name="apply"}` - Async apply thread CPU utilization
- `tikv_thread_cpu{name="grpc-poll"}` - gRPC thread CPU utilization

**Memory Metrics:**
- `tikv_engine_block_cache_size_bytes{cf="default"}` - RocksDB block cache usage
- `tikv_engine_memtable_size_bytes` - Memtable size per column family
- `process_resident_memory_bytes` - Total process memory

**Raft Metrics:**
- `tikv_raftstore_request_wait_time_duration_secs_bucket` - Propose wait duration histogram
- `tikv_raftstore_append_log_duration_seconds_bucket` - Append log duration histogram
- `tikv_raftstore_commit_log_duration_seconds_bucket` - Commit log duration histogram
- `tikv_raftstore_slow_score` - Store slow score (1-100, >= 80 is slow)

**I/O Metrics:**
- `tikv_engine_write_stall` - RocksDB write stall counter
- `tikv_engine_sst_read_micros` - SST read duration

**Query Examples:**
```promql
# Check raftstore CPU across all stores
tikv_thread_cpu{name="raftstore"}

# P99 propose wait duration
histogram_quantile(0.99, rate(tikv_raftstore_request_wait_time_duration_secs_bucket[1m]))

# Stores with slow score >= 80
tikv_raftstore_slow_score >= 80
```

### PD API (http://localhost:2379/pd/api/v1)

**Store Information:**
- `GET /pd/api/v1/stores` - List all stores with state, leader count, slow_score
- `GET /pd/api/v1/store/{id}` - Detailed store info
- Response includes: `state_name` (Up/Down/Disconnected), `leader_count`, `region_count`

**Region Information:**
- `GET /pd/api/v1/regions` - List all regions
- `GET /pd/api/v1/region/id/{id}` - Region details with leader and peer info
- `GET /pd/api/v1/stats/region` - Region stats summary

**Operator/Scheduler Management:**
- `GET /pd/api/v1/operators` - List active operators (leader transfers, etc.)
- `POST /pd/api/v1/operators` - Create operator (transfer-leader, transfer-region)
- `GET /pd/api/v1/schedulers` - List active schedulers
- `POST /pd/api/v1/schedulers` - Add scheduler (evict-leader-scheduler)

**Health:**
- `GET /pd/api/v1/health` - PD cluster health

**Example Operator Payload:**
```json
{
  "name": "transfer-leader",
  "region_id": 123,
  "to_store_id": 2
}
```

### Docker Container State

**Via docker CLI:**
- `docker ps` - Container status (running/exited)
- `docker inspect {container}` - Full container state including:
  - `State.Status` - running/exited
  - `State.ExitCode` - 137 = OOMKilled, 0 = clean exit, SIGKILL = 137 or 143
  - `State.OOMKilled` - boolean flag
  - `RestartCount` - how many times restarted
  - `State.StartedAt` - last start time
  - `HostConfig.Memory` - memory limit (cgroup memory.max)

**Via docker logs:**
- `docker logs {container} --tail 100` - Recent log output
- Look for patterns:
  - "election timeout" - Raft elections triggered
  - "OOMKilled" - Out of memory
  - "slow store score" - TiKV reporting high latency
  - "lock manager" - Lock contention warnings

### Container Processes (Chaos Detection)

**Via docker exec:**
- `docker exec {container} ps aux` - List running processes
- Chaos indicators:
  - `stress-ng` processes - CPU/memory/I/O stress
  - `dd if=/dev/zero` - Disk fill operation
  - `tc qdisc` - Network latency rules (existing)
  - `iptables -L` - Network partition rules (existing)

## Expected Symptom Patterns by Chaos Type

### cpu_pressure

**Injection:** `stress-ng --cpu 4 --timeout 0` (4 CPU workers, unlimited duration)

**Observable Symptoms:**
1. **Immediate (0-10s):**
   - CPU metrics spike: `tikv_thread_cpu{name="raftstore"}` approaches 100% on target store
   - System CPU in `docker stats` shows high utilization

2. **Early (10-30s):**
   - Propose wait duration increases: p99 goes from <50ms to >100ms
   - Raftstore becomes bottleneck processing requests

3. **Mid (30-60s):**
   - Slow score rises: `tikv_raftstore_slow_score` climbs toward 80
   - Election timeouts in logs as tick processing delays

4. **Late (60s+):**
   - PD detects slow store, may activate evict-slow-store-scheduler
   - Leader count drops on affected store
   - Other stores receive transferred leaders

**Root Cause Chain:**
```
CPU exhaustion → Raftstore thread starvation → Tick processing delays →
Election timeouts + Request backlog → Slow store detection → Leader eviction
```

**Remediation Patterns:**
- Identify and kill stress-ng processes (if chaos injection)
- If real load spike: scale out (add TiKV instances) or redistribute regions
- Temporary: manually transfer leaders to healthy stores while investigating

### memory_pressure

**Injection:** `stress-ng --vm 2 --vm-bytes 1G --timeout 0` (2 workers, 1GB each)

**Observable Symptoms:**
1. **Immediate (0-30s):**
   - Memory usage climbs: `process_resident_memory_bytes` increases rapidly
   - Block cache pressure: may see evictions if stress competes with RocksDB

2. **Critical (30-120s):**
   - Memory approaches cgroup limit
   - If limit exceeded: kernel OOM killer triggers

3. **OOM Kill:**
   - Container exits with code 137
   - `docker inspect` shows `State.OOMKilled: true`
   - Logs show "killed" message
   - Container auto-restarts (if restart policy set)

4. **Post-restart:**
   - Store state goes Down → Disconnected → Up in PD
   - Metrics reset (counters start from 0)
   - Regions rebalance to surviving stores during downtime

**Root Cause Chain:**
```
Memory exhaustion → cgroup memory.max exceeded → Kernel OOM killer →
Container killed → Store goes Down → Regions become unavailable →
Auto-restart → Store rejoins cluster
```

**Remediation Patterns:**
- Identify and kill stress-ng processes (if chaos injection)
- Check for memory leaks in logs
- Verify block-cache-size configuration (should be 30-50% of total memory)
- If real issue: increase container memory limit or scale out
- Restart container after removing pressure source

### io_latency

**Injection:** `stress-ng --iomix 4 --timeout 0` (4 I/O mix workers)

**Observable Symptoms:**
1. **Immediate (0-20s):**
   - Append log duration spikes: `tikv_raftstore_append_log_duration_seconds` p99 increases
   - RocksDB write stalls may occur

2. **Early (20-60s):**
   - Slow score rises: `tikv_raftstore_slow_score` climbs
   - Store slow_score visible in PD API

3. **Mid (60-120s):**
   - PD's evict-slow-store-scheduler may activate automatically
   - Leaders transferred away from slow store
   - Append log duration remains high even with fewer leaders

4. **Sustained:**
   - Store continues operating but degraded
   - Request timeouts possible if I/O latency severe
   - Commit log duration also affected

**Root Cause Chain:**
```
I/O saturation → Append log writes slow → Raft log commits delayed →
Slow store score increases → PD detects slow store → Leader eviction →
Reduced load on slow store but still degraded
```

**Remediation Patterns:**
- Identify and kill stress-ng processes (if chaos injection)
- If real I/O issue: check disk health, filesystem issues, saturation
- Verify PD's automatic evict-slow-store-scheduler is handling it
- May need to drain store entirely if disk failing
- Long-term: replace disk/node, rebalance data away

## Feature Dependencies

```
Detection Layer (Base)
├─ Prometheus query capability
├─ PD API query capability
├─ Docker inspect/logs capability
└─ Process listing capability

└─> Basic Symptom Detection
    ├─ CPU metrics → Raftstore bottleneck
    ├─ Memory metrics → OOM risk
    ├─ I/O metrics → Slow store
    └─ Container state → Exit codes

    └─> Correlation & Root Cause
        ├─ Multi-metric analysis
        ├─ Timeline construction
        └─ Cascading failure detection

        └─> Remediation
            ├─ Chaos cleanup (kill stress-ng)
            ├─ Leader transfer (PD operator)
            ├─ Store drain (evict-leader-scheduler)
            └─ Container restart (with diagnostics)
```

**Critical Path:** Agent must be able to query Prometheus and PD API before any detection works. Container access is needed for chaos detection and cleanup.

## Agent Capabilities Required

To implement these features, agent needs:

| Capability | Why Needed | Priority |
|------------|------------|----------|
| Execute Prometheus queries | Metrics are primary signal source | Critical |
| Call PD HTTP API | Store state, operators, schedulers | Critical |
| Inspect Docker containers | State, exit codes, OOM detection | Critical |
| Read Docker logs | Error messages, election timeouts | High |
| Execute commands in containers | Detect/kill stress-ng processes | High |
| Parse JSON responses | PD API, Prometheus JSON format | Critical |
| Time-series reasoning | Understand metric trends over time | High |
| Multi-source correlation | Connect metrics + logs + API state | High |
| Hypothesis testing | Propose diagnosis, gather evidence to confirm/refute | Medium |

## Validation Criteria

How to verify agent correctly diagnosed each chaos type:

### cpu_pressure

**Agent should conclude:**
- "Store X experiencing CPU saturation"
- "Raftstore thread at 95% CPU causing request backlog"
- "Propose wait duration elevated to 300ms (baseline 50ms)"
- "PD detecting slow store, transferring leaders automatically"

**Evidence agent should cite:**
- `tikv_thread_cpu{name="raftstore"}` metric value
- Propose wait duration p99 value
- Store slow_score from PD API or metrics
- Leader count decreasing on affected store

### memory_pressure

**Agent should conclude:**
- "Container exceeded memory limit and was OOMKilled"
- "Store went Down, auto-restarted"
- "Currently recovering, regions rebalancing"

**Evidence agent should cite:**
- Exit code 137 from docker inspect
- OOMKilled flag true
- Container restart timestamp
- Store state transitions in PD (Down → Up)

### io_latency

**Agent should conclude:**
- "Store X experiencing I/O latency"
- "Append log duration elevated to 400ms (baseline <50ms)"
- "Slow store score 85, PD activated evict-slow-store-scheduler"
- "Leaders being transferred away automatically"

**Evidence agent should cite:**
- `tikv_raftstore_append_log_duration_seconds` p99 value
- `tikv_raftstore_slow_score` >= 80
- PD API showing evict-slow-store-scheduler active
- Decreasing leader count on affected store

## Implementation Notes

### Chaos Injection Methods

**CPU Pressure:**
```bash
docker exec {container} stress-ng --cpu 4 --timeout 300s
```
- 4 workers to saturate multi-core
- 300s timeout (5 min) for sustained pressure

**Memory Pressure:**
```bash
docker exec {container} stress-ng --vm 2 --vm-bytes 1G --timeout 300s
```
- 2 workers, 1GB each = 2GB total allocation
- Will trigger OOM if container memory limit < 2GB + RocksDB overhead

**I/O Latency:**
```bash
docker exec {container} stress-ng --iomix 4 --timeout 300s
```
- iomix combines sequential/random read/write + fsync
- 4 workers to create sustained I/O pressure

**Cleanup:**
```bash
docker exec {container} killall stress-ng
```

### Metric Baselines

For evaluation scoring, establish baselines:
- Propose wait duration: normal < 50ms, degraded > 100ms
- Append log duration: normal < 50ms, degraded > 200ms
- Raftstore CPU: normal < 50%, bottleneck > 85%
- Slow score: healthy < 50, slow >= 80

### PD API Authentication

Current test environment has no auth. Production might need:
- Token-based auth via headers
- TLS certificate verification
- Document in implementation phase

## Research Confidence

| Area | Confidence | Source | Notes |
|------|------------|--------|-------|
| CPU pressure symptoms | HIGH | Official docs, Grafana dashboard spec | Raftstore CPU metric confirmed in TiKV docs |
| Memory OOM patterns | HIGH | Docker docs, cgroup documentation | Exit code 137 standard across Linux containers |
| I/O slow store detection | MEDIUM | GitHub issues, PD scheduler code | Slow score mechanism confirmed but exact thresholds vary by version |
| Prometheus metric names | MEDIUM | Grafana dashboard, doc excerpts | Full `tikv_` prefix confirmed but some exact names extrapolated from dashboard panels |
| PD API endpoints | MEDIUM | pd-ctl docs, API doc references | Endpoint paths confirmed via pd-ctl but JSON payload formats need validation |
| stress-ng syntax | HIGH | stress-ng official docs, man pages | Command syntax verified across multiple sources |
| Remediation patterns | MEDIUM | Community discussions, best practices docs | Patterns documented but real-world timing may vary |

**Gaps requiring validation:**
- Exact Prometheus metric names with full labels (HIGH priority)
- PD operator API JSON payload format (HIGH priority)
- Typical timeline for slow store score to trigger eviction (MEDIUM priority)
- Whether TiKV logs slow score changes (LOW priority)

## Sources

### TiKV Architecture & Metrics
- [TiKV CPU Anomaly, Raft Election Failure - TiDB Forum](https://ask.pingcap.com/t/tikv-cpu-anomaly-raft-election-failure/8271)
- [Key Monitoring Metrics of TiKV - TiDB Docs](https://docs.pingcap.com/tidb/stable/grafana-tikv-dashboard/)
- [Best Practices for Tuning TiKV Performance with Massive Regions](https://docs.pingcap.com/tidb/stable/massive-regions-best-practices/)
- [Troubleshoot Increased Read and Write Latency - TiDB Docs](https://docs.pingcap.com/tidb/stable/troubleshoot-cpu-issues/)

### Memory & OOM
- [Tune TiKV Memory Parameter Performance - TiDB Docs](https://docs.pingcap.com/tidb/stable/tune-tikv-memory-performance/)
- [Memory usage may grow unexpectedly and causes OOM - GitHub Issue #17394](https://github.com/tikv/tikv/issues/17394)
- [TiKV OOM Killed - GitHub Issue #14346](https://github.com/tikv/tikv/issues/14346)

### I/O & Slow Store Detection
- [Improve current slow-store detecting - GitHub Issue #14131](https://github.com/tikv/tikv/issues/14131)
- [scheduler: new slow store detecting and leader evicting - Pull Request #5808](https://github.com/tikv/pd/pull/5808)
- [Performance/health feedback and Unified Health Controller - GitHub Issue #16297](https://github.com/tikv/tikv/issues/16297)

### PD Scheduling & Leader Transfer
- [Best Practices for PD Scheduling - TiDB Docs](https://docs.pingcap.com/tidb/stable/pd-scheduling-best-practices/)
- [PD Control User Guide - TiDB Docs](https://docs.pingcap.com/tidb/stable/pd-control/)
- [Speed up evict leader scheduler - GitHub Issue #10602](https://github.com/tikv/tikv/issues/10602)

### Chaos Injection Tools
- [stress-ng (stress next generation) - Official Site](http://colinianking.github.io/stress-ng/)
- [stress-ng Ubuntu Manpage](https://manpages.ubuntu.com/manpages/bionic/man1/stress-ng.1.html)
- [Stress Testing Your System with Docker and Stress - Medium](https://medium.com/@ravipatel.it/stress-testing-your-system-with-docker-and-stress-bd7760b8fbcf)

### Docker & cgroups
- [Resource constraints - Docker Docs](https://docs.docker.com/engine/containers/resource_constraints/)
- [The Complete Guide to Docker Resource Limits - BetterLink Blog](https://eastondev.com/blog/en/posts/dev/20251218-docker-resource-limits-guide/)

### Recovery Patterns
- [Leader Transfer In TiKV - Blog Post](https://int64.me/2017/Leader%20Transfer%20In%20TiKV.html)
- [TiKV Configuration File - TiDB Docs](https://docs.pingcap.com/tidb/stable/tikv-configuration-file/)
