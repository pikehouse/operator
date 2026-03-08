---
name: run-campaign
description: Reset workers, rebuild stale Docker images, and run an eval campaign on GCP
disable-model-invocation: true
allowed-tools: Bash, Read, Glob, Grep, TaskCreate, TaskUpdate, TaskList, TaskOutput
argument-hint: <campaign-yaml-path> [--workers N]
---

# Run Campaign

Run a GCP eval campaign end-to-end: clean up, rebuild stale images, enqueue, and start workers.

## Arguments

- `$1` (required): Campaign YAML path relative to eval/, e.g. `campaigns/operations/tikv-all-chaos-cloud.yaml`
- `$2` (optional): Number of workers to start (default: auto, based on quota)

## Session Isolation

Each campaign run is scoped to avoid conflicts with concurrent sessions:
- **Worker IDs, logs, cleanup**: scoped by campaign ID (`c${CID}`) — each campaign's workers only claim its work items
- **Docker images**: tagged by git commit SHA — if code hasn't changed, images are already in the registry and no rebuild/push is needed. Different sessions on different commits get different images without overwriting each other.

## Steps

Execute these steps in order. Use TaskCreate to track progress.

### 1. Clean Up Previous Campaign Workers

**Scoped cleanup** (default): Kill only workers from a specific previous campaign:
```bash
# Kill workers from a previous campaign (replace PREV_CID with the old campaign ID)
ps aux | grep "c${PREV_CID}-" | grep "eval worker" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true
```

Release stale work queue items (this is global and safe):
```bash
source $PROJECT_ROOT/.env && uv run eval worker release-stale --remote --timeout 1
```

**Full cleanup** (only when explicitly requested or no other campaigns are running):
```bash
# Kill ALL local eval worker processes
ps aux | grep "eval worker" | grep -v grep | awk '{print $2}' | xargs kill -9
# Delete ALL GCP compute instances
gcloud compute instances list --format="value(name,zone)" | while read name zone; do gcloud compute instances delete "$name" --zone="$zone" --quiet; done
```

### 2. Check & Rebuild Docker Images

Get the current git SHA for image tagging:
```bash
GIT_SHA=$(git rev-parse --short HEAD)
```

The rebuild decision matrix (from CLOUD.md):

| Image | Dockerfile | Triggers |
|-------|-----------|----------|
| **operator** | `subjects/tikv/Dockerfile.operator` | Changes to `packages/operator-core/`, `packages/operator-protocols/`, `subjects/*/observer/` |
| **worker** | `eval/Dockerfile` | Changes to `eval/src/`, `eval/Dockerfile`, `subjects/*/service/` |
| **tikv-chaos** | `subjects/tikv/Dockerfile.tikv-chaos` | Changes to TiKV base version or chaos tools |
| **ycsb** | `subjects/tikv/Dockerfile.ycsb` | Changes to YCSB workloads or go-ycsb version |

For each image, compare the local Docker image creation timestamp against git commits that touch the trigger paths. Use:
```bash
docker images --format "{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}" | grep <image-name>
git log --oneline --since="<image-date>" -- <trigger-paths>
```

If there are commits newer than the image, rebuild and push. Tag with `:${GIT_SHA}`:
```bash
# Operator
docker build --platform linux/amd64 -t operator-eval -f subjects/tikv/Dockerfile.operator .
docker tag operator-eval us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}

# Worker
docker build --platform linux/amd64 -t eval-worker -f eval/Dockerfile .
docker tag eval-worker us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/worker:${GIT_SHA}
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/worker:${GIT_SHA}

# tikv-chaos (rarely needed)
docker build --platform linux/amd64 -t tikv-chaos:v8.5.5 -f subjects/tikv/Dockerfile.tikv-chaos subjects/tikv/
docker tag tikv-chaos:v8.5.5 us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/tikv-chaos:v8.5.5
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/tikv-chaos:v8.5.5

# ycsb (rarely needed)
docker build --platform linux/amd64 -t ycsb -f subjects/tikv/Dockerfile.ycsb subjects/tikv/
docker tag ycsb us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/ycsb:latest
docker push us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/ycsb:latest
```

All builds MUST use `--platform linux/amd64` (GCP VMs are amd64, dev machines may be ARM).
All builds use project root as context (except tikv-chaos and ycsb which use `subjects/tikv/`).

Build stale images in parallel when possible. Push sequentially after builds complete.

If the image for `${GIT_SHA}` already exists in the registry (same commit, no code changes), skip the rebuild entirely.

### 3. Enqueue Campaign

```bash
source $PROJECT_ROOT/.env
uv run eval run campaign $1 --cloud=gcp
```

Note the campaign ID (CID) from output. Worker IDs and cleanup use `c${CID}` as the scope key.

### 4. Determine Worker Count & Start Workers

If the user specified a worker count, use that. Otherwise, auto-calculate from GCP quota:

```bash
# Get E2 vCPU quota and usage for us-central1
gcloud compute regions describe us-central1 \
  --format="json(quotas)" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for q in data['quotas']:
    if q['metric'] == 'E2_CPUS':
        limit = q['limit']
        usage = q['usage']
        vcpus_per_vm = 4  # e2-standard-4
        available = int((limit - usage) / vcpus_per_vm)
        # Leave 1 VM worth of buffer
        max_workers = max(1, available - 1)
        print(f'limit={int(limit)} used={int(usage)} available_vms={available} recommended_workers={max_workers}')
        break
"
```

Each trial VM is `e2-standard-4` (4 vCPUs). The E2_CPUS quota (typically 24) is usually the binding constraint. After cleanup (step 1), usage should be 0, giving `24/4 - 1 = 5` workers with buffer.

Report the quota situation to the user before starting workers:
- Show E2_CPUS limit, current usage, and how many workers will be started
- If the requested count would exceed quota, warn and cap at the safe maximum

Start each worker as a separate background Bash command with `run_in_background: true`. Use campaign-scoped worker IDs and the `--campaign` flag:
```bash
source $PROJECT_ROOT/.env
for i in $(seq 1 ${NUM_WORKERS}); do
  uv run eval worker start --cloud=gcp --id=c${CID}-$i \
    --campaign=${CID} \
    --operator-image=us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}
done
```

### 5. Wait for Completion

Run `eval wait` as a **background** Bash command (`run_in_background: true`). You will be automatically notified when it completes — do not poll, sleep, or check status in a loop.

```bash
source $PROJECT_ROOT/.env && uv run eval wait ${CID} --remote
```

**Important:** Do NOT run `eval show`, `eval worker status`, or any other status-checking command in a loop while waiting. The `eval wait` command uses PostgreSQL LISTEN/NOTIFY for instant notifications and will exit with a summary when all trials finish. You will be notified automatically.

If the user asks for a status check, run `eval show <CID> --remote` once (not in a loop).

## Environment

- `$PROJECT_ROOT` is the git repo root (parent of eval/)
- `.env` at project root contains `EVAL_DATABASE_URL` and `ANTHROPIC_API_KEY`
- Working directory is `eval/`
