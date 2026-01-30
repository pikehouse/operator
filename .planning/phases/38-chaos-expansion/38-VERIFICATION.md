---
phase: 38-chaos-expansion
verified: 2026-01-30T00:10:03Z
status: passed
score: 12/12 must-haves verified
---

# Phase 38: Chaos Expansion Verification Report

**Phase Goal:** Developer can run batch campaigns with multiple chaos types
**Verified:** 2026-01-30T00:10:03Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TiKV containers have NET_ADMIN capability for tc/iptables commands | ✓ VERIFIED | cap_add: [NET_ADMIN] found in tikv0, tikv1, tikv2 services (3 occurrences) |
| 2 | Latency chaos injects network delay on TiKV container using tc netem | ✓ VERIFIED | inject_latency_chaos() uses `tc qdisc add dev eth0 root netem delay` command |
| 3 | Disk pressure chaos fills disk space on TiKV container using fallocate | ✓ VERIFIED | inject_disk_pressure() uses `fallocate -l {fill_bytes}` command |
| 4 | Network partition chaos isolates TiKV node from cluster using iptables DROP rules | ✓ VERIFIED | inject_network_partition() uses `iptables -I OUTPUT/INPUT -d/-s {ip} -j DROP` |
| 5 | All chaos types have cleanup functions that revert changes | ✓ VERIFIED | cleanup_latency_chaos, cleanup_disk_pressure, cleanup_network_partition implemented |
| 6 | TiKVEvalSubject.get_chaos_types() returns all four chaos types | ✓ VERIFIED | Returns ['node_kill', 'latency', 'disk_pressure', 'network_partition'] |
| 7 | EvalSubject protocol supports chaos_params kwargs and cleanup_chaos method | ✓ VERIFIED | Protocol has inject_chaos(**params: Any) and cleanup_chaos(chaos_metadata) |
| 8 | Developer can define campaign configuration in YAML file | ✓ VERIFIED | CampaignConfig Pydantic model validates YAML with subjects, chaos_types, trials_per_combination |
| 9 | YAML config supports matrix expansion (subjects x chaos_types) | ✓ VERIFIED | expand_campaign_matrix() uses itertools.product for Cartesian expansion |
| 10 | Developer can run eval run campaign config.yaml and see trials execute | ✓ VERIFIED | CLI command `eval run campaign` exists, loads config, calls run_campaign_from_config() |
| 11 | Campaign runner respects parallel and cooldown_seconds settings | ✓ VERIFIED | asyncio.Semaphore(config.parallel) and asyncio.sleep(config.cooldown_seconds) |
| 12 | Existing run_campaign function remains unchanged for backward compatibility | ✓ VERIFIED | Both run_campaign() and run_campaign_from_config() exist in harness.py |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `subjects/tikv/docker-compose.yaml` | NET_ADMIN capability for tikv0, tikv1, tikv2 | ✓ VERIFIED | cap_add: [NET_ADMIN] on lines 81-82, 110-111, 139-140 (3 containers) |
| `eval/src/eval/types.py` | ChaosType enum with LATENCY, DISK_PRESSURE, NETWORK_PARTITION | ✓ VERIFIED | Enum has all 4 values (NODE_KILL, LATENCY, DISK_PRESSURE, NETWORK_PARTITION) |
| `eval/src/eval/types.py` | EvalSubject protocol with **params and cleanup_chaos | ✓ VERIFIED | inject_chaos signature accepts **params: Any, cleanup_chaos method exists |
| `eval/src/eval/subjects/tikv/chaos.py` | inject/cleanup functions for all chaos types | ✓ VERIFIED | 259 lines, exports inject_latency_chaos, inject_disk_pressure, inject_network_partition + cleanup functions |
| `eval/src/eval/subjects/tikv/subject.py` | TiKVEvalSubject dispatching all chaos types | ✓ VERIFIED | Imports all chaos functions, dispatches based on chaos_type, implements cleanup_chaos() |
| `eval/pyproject.toml` | PyYAML dependency | ✓ VERIFIED | pyyaml>=6.0 in dependencies list |
| `eval/src/eval/runner/campaign.py` | CampaignConfig and matrix expansion | ✓ VERIFIED | 78 lines, exports CampaignConfig, ChaosSpec, expand_campaign_matrix, load_campaign_config |
| `eval/src/eval/runner/harness.py` | run_campaign_from_config with parallel execution | ✓ VERIFIED | 365 lines, NEW function added, uses asyncio.Semaphore, cleanup_chaos called after final_state |
| `eval/src/eval/cli.py` | eval run campaign subcommand | ✓ VERIFIED | campaign command at line 174, loads config, runs campaign, displays help |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| eval/cli.py | eval/runner/campaign.py | load_campaign_config import | ✓ WIRED | Import on line 14, used on line 218 |
| eval/runner/harness.py | eval/runner/campaign.py | expand_campaign_matrix call | ✓ WIRED | Import on line 14, called on line 299 |
| eval/runner/harness.py | eval/subjects/tikv/subject.py | cleanup_chaos call | ✓ WIRED | Called on line 202 after final_state capture |
| eval/subjects/tikv/subject.py | eval/subjects/tikv/chaos.py | chaos function dispatch | ✓ WIRED | Imports all chaos functions (lines 14-23), dispatches in inject_chaos (lines 154-183) |
| eval/runner/harness.py | eval/types.py EvalSubject | inject_chaos with **params | ✓ WIRED | chaos_params passed via **(chaos_params or {}) on line 165 |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| SUBJ-04: TiKV chaos: latency injection (tc netem) | ✓ SATISFIED | inject_latency_chaos() uses tc netem, TiKVEvalSubject dispatches it |
| SUBJ-05: TiKV chaos: disk pressure (fallocate) | ✓ SATISFIED | inject_disk_pressure() uses fallocate, TiKVEvalSubject dispatches it |
| SUBJ-06: TiKV chaos: network partition (iptables) | ✓ SATISFIED | inject_network_partition() uses iptables, TiKVEvalSubject dispatches it |
| CLI-03: eval run campaign config.yaml | ✓ SATISFIED | CLI command exists, loads config, runs batch campaigns |

### Anti-Patterns Found

**None detected.**

- No TODO/FIXME/placeholder comments in modified files
- No stub patterns (empty returns, console.log only)
- All chaos functions have substantive implementations
- Cleanup functions handle errors gracefully (expected for container restarts)

### Human Verification Required

#### 1. Latency Chaos Functional Test

**Test:** 
1. Start TiKV cluster: `cd subjects/tikv && docker compose up -d`
2. Create test YAML:
```yaml
name: latency-test
subjects: [tikv]
chaos_types:
  - type: latency
    params: {min_ms: 100, max_ms: 200}
trials_per_combination: 1
parallel: 1
```
3. Run: `eval run campaign latency-test.yaml`
4. During execution, exec into container and run: `tc qdisc show dev eth0`

**Expected:** 
- Campaign executes without errors
- tc qdisc shows netem delay rule during chaos
- After cleanup, tc qdisc shows no netem rules

**Why human:** Requires observing network state changes inside running containers, verifying tc commands execute correctly

#### 2. Disk Pressure Functional Test

**Test:**
1. Create campaign with disk_pressure chaos (fill_percent: 80)
2. During execution, exec into container: `df -h /data`
3. After cleanup: `df -h /data` and `ls /data/chaos-fill-*`

**Expected:**
- During chaos: /data shows ~80% full
- After cleanup: disk space restored, chaos-fill-*.tmp file removed

**Why human:** Requires observing disk space changes and file cleanup inside containers

#### 3. Network Partition Functional Test

**Test:**
1. Create campaign with network_partition chaos
2. During execution, check PD dashboard for store status
3. Exec into isolated container: `iptables -L OUTPUT -n` and `iptables -L INPUT -n`
4. After cleanup, verify connectivity restored

**Expected:**
- During chaos: iptables shows DROP rules for peer IPs, PD shows store disconnected
- After cleanup: iptables rules removed, PD shows all stores Up

**Why human:** Requires observing cluster behavior and network rules, checking PD API responses

#### 4. Campaign Matrix Expansion

**Test:**
1. Create YAML with 2 chaos types, trials_per_combination: 3
2. Run campaign
3. Check database: `sqlite3 eval.db "SELECT COUNT(*) FROM trials WHERE campaign_id=X"`

**Expected:**
- Campaign creates 6 trials (2 chaos types × 3 trials each)
- All trials execute sequentially or in parallel based on config.parallel

**Why human:** Verifies end-to-end workflow, database persistence, matrix expansion correctness

#### 5. Parallel Execution Control

**Test:**
1. Create campaign with parallel: 2, trials_per_combination: 4
2. Observe trial execution logs for timing overlap
3. Verify semaphore limits concurrency to 2

**Expected:**
- Max 2 trials running concurrently
- Cooldown respected between trials
- All trials complete successfully

**Why human:** Requires observing timing and concurrency behavior during execution

---

## Success Criteria Check

From Phase 38 ROADMAP success criteria:

1. ✓ **TiKV supports latency chaos (tc netem)** — inject_latency_chaos() implemented with tc netem delay command
2. ✓ **TiKV supports disk pressure chaos (fallocate)** — inject_disk_pressure() implemented with fallocate command
3. ✓ **TiKV supports network partition chaos (iptables)** — inject_network_partition() implemented with iptables DROP rules
4. ✓ **Developer can define campaign config YAML** — CampaignConfig Pydantic model validates YAML structure
5. ✓ **Developer can run `eval run campaign config.yaml`** — CLI command exists and wired to run_campaign_from_config()

**All 5 success criteria met.**

---

## Verification Methodology

**Artifact Verification (3 Levels):**

1. **Existence:** All required files exist at expected paths
2. **Substantive:** All files have real implementations (not stubs)
   - chaos.py: 259 lines with tc/fallocate/iptables commands
   - campaign.py: 78 lines with Pydantic models and matrix expansion
   - All functions have real logic, no TODOs or placeholders
3. **Wired:** All components properly connected
   - CLI imports campaign loader
   - Harness imports and calls expand_campaign_matrix
   - Subject imports and dispatches to all chaos functions
   - cleanup_chaos called after final_state capture

**Key Link Verification:**
- CLI → campaign.py: load_campaign_config imported and used
- Harness → campaign.py: expand_campaign_matrix imported and called
- Harness → Subject: cleanup_chaos called with chaos_metadata
- Subject → chaos.py: All chaos functions imported and dispatched

**Anti-Pattern Scan:**
- No TODO/FIXME/placeholder comments
- No empty returns or stub implementations
- All functions have real shell commands (tc, fallocate, iptables)
- Cleanup functions handle errors gracefully (expected for container restarts)

**Import Verification:**
- All chaos functions import successfully
- TiKVEvalSubject.get_chaos_types() returns all 4 types
- Both run_campaign() and run_campaign_from_config() available
- CLI campaign command shows help text with example YAML

---

_Verified: 2026-01-30T00:10:03Z_
_Verifier: Claude (gsd-verifier)_
