---
name: iterate-campaign
description: Analyze campaign failures, diagnose root causes, fix, rebuild, and retry until win rate improves
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, TaskCreate, TaskUpdate, TaskList, TaskOutput
argument-hint: <campaign-id> [--target-rate N%]
---

# Iterate Campaign

Diagnose and fix campaign failures through targeted investigation and iterative retries. This is the debugging counterpart to `run-campaign` — use it when a campaign has completed but the win rate is below target.

## Arguments

- `$1` (required): Campaign ID to analyze (e.g. `100`)
- `$2` (optional): Target win rate to aim for (default: 90%)

## Session Isolation

Each retry campaign is scoped to avoid conflicts with concurrent sessions:
- **Worker IDs, logs, cleanup**: scoped by campaign ID (`c${CID}`) — each campaign's workers only claim its work items
- **Docker images**: tagged by git commit SHA — if code hasn't changed, images are already in the registry and no rebuild/push is needed. Different sessions on different commits get different images without overwriting each other.

## Overview

The iteration loop:

```
Analyze failures → Diagnose root cause → Fix code → Test → Rebuild images → Retry → Evaluate
     ↑                                                                              │
     └──────────────────────────────────────────────────────────────────────────────-─┘
```

## Steps

### 1. Analyze Campaign Failures

Get overall results and per-trial breakdown:

```bash
source $PROJECT_ROOT/.env
uv run eval show <campaign_id> --remote
```

Then get per-trial chaos types for all failed trials:

```bash
uv run eval show --trial <trial_id> --remote
```

Group failures by chaos type. Common patterns:
- **All trials of a chaos type failed with 0 commands**: Monitor never created a ticket (missing or broken invariant)
- **Trials resolved but scored FAILURE**: Agent fixed the issue but final state check failed (timing or scoring bug)
- **Negative detect times**: Pre-chaos ticket leakage (startup tickets not properly cleared)
- **Timeout (not resolved)**: Agent couldn't fix the issue within the time limit

### 2. Investigate Root Causes

For each failing chaos type, investigate systematically:

#### Check worker logs
If worker logs are available locally:
```bash
tail -100 /tmp/c*-*.log
```

#### Check trial details
```bash
uv run eval show --trial <id> --remote        # Timing, commands, chaos type
uv run eval show --trial <id> --remote --json  # Full state data
```

Look at:
- **Timing**: Is detect time negative (pre-chaos ticket)? Is it 0s (pre-existing ticket)?
- **Commands**: Did the agent run any? Were they relevant to the chaos type?
- **Final state**: Is it empty `{}`? Does it show unhealthy stores?

#### Check invariant coverage
```bash
# What invariants exist?
grep -n "def check_" subjects/tikv/observer/src/tikv_observer/invariants.py

# What violations can the checker produce?
grep -n "name=" subjects/tikv/observer/src/tikv_observer/invariants.py | grep CONFIG
```

#### Common root cause checklist

| Symptom | Likely Cause | Fix Location |
|---------|-------------|--------------|
| 0 commands, no ticket | Missing invariant for chaos type | `subjects/*/observer/invariants.py` |
| 0 commands, ticket exists | Agent stuck on startup ticket | `eval/src/eval/runner/worker.py` (restart_operator) |
| Resolved but FAILURE | Final state captured too early | `eval/src/eval/runner/worker.py` (wait_healthy) |
| Resolved but FAILURE | State capture queries wrong endpoint | `eval/src/eval/subjects/cloud/gcp/subject.py` |
| Negative detect time | Startup ticket leaked past force-resolve | `eval/src/eval/runner/worker.py` (pre-chaos flow) |
| All PD-related chaos fails | Monitor uses single PD endpoint | `eval/src/eval/runner/remote_operator.py` (PD endpoints) |
| Invariant too sensitive | Fires during startup/stabilization | Adjust threshold or grace period in invariants.py |
| Invariant not sensitive enough | Doesn't fire for the chaos effect | Lower threshold in invariants.py |

### 3. Fix

Make code changes. Key files by concern:

| Concern | Files |
|---------|-------|
| Invariant detection | `subjects/tikv/observer/src/tikv_observer/invariants.py` |
| Observation data | `subjects/tikv/observer/src/tikv_observer/subject.py` |
| PD client / failover | `subjects/tikv/observer/src/tikv_observer/pd_client.py` |
| Worker trial flow | `eval/src/eval/runner/worker.py` |
| Remote operator | `eval/src/eval/runner/remote_operator.py` |
| State capture | `eval/src/eval/subjects/cloud/gcp/subject.py` |
| Trial scoring | `eval/src/eval/analysis/scoring.py` |
| Chaos injection | `eval/src/eval/subjects/tikv/chaos.py` (local), `cloud/gcp/subject.py` (cloud) |

### 4. Test

Run tests for all modified packages:

```bash
# Always run these
uv run pytest packages/operator-core/tests/ -x -q
uv run pytest subjects/tikv/observer/tests/ -x -q
cd eval && uv run pytest tests/ -x -q --ignore=tests/test_chat_db_app_e2e.py
```

### 5. Rebuild & Push Images

Determine which images need rebuilding based on what changed:

| Changed | Rebuild |
|---------|---------|
| `subjects/*/observer/` | Operator image |
| `packages/operator-core/` | Operator image |
| `eval/src/eval/` | Worker image |
| Both | Both images |

Tag with the current git commit SHA:

```bash
GIT_SHA=$(git rev-parse --short HEAD)

# Operator (invariant/observer changes)
cd $PROJECT_ROOT
docker build --platform linux/amd64 -f subjects/tikv/Dockerfile.operator -t us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA} .
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}

# Worker (eval code changes)
docker build --platform linux/amd64 -t eval-worker -f eval/Dockerfile .
docker tag eval-worker us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/worker:${GIT_SHA}
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/worker:${GIT_SHA}
```

If the image for `${GIT_SHA}` already exists in the registry (same commit, no code changes since last push), skip the rebuild entirely.

All builds MUST use `--platform linux/amd64` on ARM Macs.

### 6. Create Targeted Retry Campaign & Start Workers

Create a campaign YAML with just the failing chaos types:

```yaml
# eval/campaigns/debug/tikv-retry-<chaos>.yaml
name: tikv-retry-<description>
subjects: [tikv]
chaos_types:
  - type: <failing_chaos_type_1>
  - type: <failing_chaos_type_2>
trials_per_combination: 3
parallel: 3
cooldown_seconds: 10
include_baseline: false
cloud:
  provider: gcp
  operator:
    enabled: true
    image: us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}
```

Enqueue to get the CID, then start workers:

```bash
source $PROJECT_ROOT/.env
GIT_SHA=$(git rev-parse --short HEAD)

# Enqueue to get campaign ID
uv run eval run campaign campaigns/debug/tikv-retry-<chaos>.yaml --cloud=gcp --parallel 3
# Note the CID from output

# Start campaign-scoped workers
for i in 1 2 3; do
  nohup uv run eval worker start --cloud=gcp --id=c${CID}-$i \
    --campaign=${CID} \
    --operator-image=us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA} \
    > /tmp/c${CID}-$i.log 2>&1 &
done
```

### 7. Monitor & Evaluate

Run `eval wait` as a **background** Bash command (`run_in_background: true`):

```bash
source $PROJECT_ROOT/.env && uv run eval wait <new_campaign_id> --remote
```

You will be automatically notified when it completes. Do NOT poll for status in a loop — no `sleep`, no repeated `eval show` or `eval worker status` calls. The wait command uses PostgreSQL LISTEN/NOTIFY for instant updates.

When notified, compare results against the previous campaign:
- Did the targeted chaos types improve?
- Any regressions in previously-passing types?
- Is the win rate at or above target?

### 8. Iterate or Finalize

**If failures remain**: Go back to step 2 with the new campaign's failed trials. Use `eval logs <trial_id> --remote` if Cloud Logging is enabled.

**If target reached on retry**: Run a full campaign to validate no regressions:

```bash
uv run eval run campaign campaigns/operations/tikv-all-chaos-cloud.yaml --cloud=gcp --parallel 3
```

**When done**: Kill scoped workers, mark notable campaigns, commit fixes:

```bash
# Kill workers for this campaign
ps aux | grep "c${CID}-" | grep "eval worker" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true

# Full cleanup (only if no other campaigns running)
# ps aux | grep 'eval worker' | grep -v grep | awk '{print $2}' | xargs kill -9

# Mark campaign as notable
uv run eval notable <campaign_id> --remote
uv run eval note <campaign_id> --remote "<description of what was fixed>"

# Commit
git add <changed-files>
git commit -m "fix(eval): <description>"
git push
```

## Success Criteria

A trial succeeds when the **infrastructure and eval pipeline work correctly**, regardless of whether the agent itself performs well. The agent may fail to resolve the issue — that's a valid (low-scoring) outcome, not a broken trial.

A trial is successful if:

1. **Trial runs to completion on GCP infra** — the worker picks up the trial, provisions a VM, deploys the subject, and the trial reaches its `ended_at` without crashing or erroring out
2. **Deployment becomes healthy** — `wait_healthy()` passes before chaos injection begins; the subject cluster is fully operational
3. **Chaos is successfully injected** (non-baseline trials) — `inject_chaos()` returns valid metadata and the chaos actually takes effect on the target system
4. **Monitor detects the chaos and files a ticket** — an invariant violation fires and creates a ticket with a positive `time_to_detect`
5. **Agent recognizes the ticket** — the agent reads the ticket and begins reasoning about it (commands appear in `commands_json`)

A trial with all of the above but where the agent fails to resolve the issue is a **valid FAILURE** — the eval pipeline worked, the agent just didn't succeed. This is expected data.

A trial is **broken** (and needs iteration) if any of the above don't hold — e.g., VM provisioning fails, deployment never becomes healthy, chaos injection errors out, no ticket is created despite real chaos, or commands_json is empty because the agent never saw the ticket.

## Environment

- `$PROJECT_ROOT` is the git repo root (parent of eval/)
- `.env` at project root contains `EVAL_DATABASE_URL` and `ANTHROPIC_API_KEY`
- Working directory is `eval/`
