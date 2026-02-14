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

## Steps

Execute these steps in order. Use TaskCreate to track progress.

### 1. Clean Up

- Kill all local `eval worker` processes: `ps aux | grep "eval worker" | grep -v grep | awk '{print $2}' | xargs kill -9`
- List and delete all GCP compute instances: `gcloud compute instances list`, then `gcloud compute instances delete <names> --zone=<zone> --quiet`
- Release stale work queue items: `source $PROJECT_ROOT/.env && uv run eval worker release-stale --remote --timeout 1`

### 2. Check & Rebuild Docker Images

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

If there are commits newer than the image, rebuild and push:
```bash
# Operator
docker build --platform linux/amd64 -t operator-eval -f subjects/tikv/Dockerfile.operator .
docker tag operator-eval us-central1-docker.pkg.dev/operator-486214/eval/operator:latest
docker push us-central1-docker.pkg.dev/operator-486214/eval/operator:latest

# Worker
docker build --platform linux/amd64 -t eval-worker -f eval/Dockerfile .
docker tag eval-worker us-central1-docker.pkg.dev/operator-486214/eval/worker:latest
docker push us-central1-docker.pkg.dev/operator-486214/eval/worker:latest

# tikv-chaos (rarely needed)
docker build --platform linux/amd64 -t tikv-chaos:v8.5.5 -f subjects/tikv/Dockerfile.tikv-chaos subjects/tikv/
docker tag tikv-chaos:v8.5.5 us-central1-docker.pkg.dev/operator-486214/eval/tikv-chaos:v8.5.5
docker push us-central1-docker.pkg.dev/operator-486214/eval/tikv-chaos:v8.5.5

# ycsb (rarely needed)
docker build --platform linux/amd64 -t ycsb -f subjects/tikv/Dockerfile.ycsb subjects/tikv/
docker tag ycsb us-central1-docker.pkg.dev/operator-486214/eval/ycsb:latest
docker push us-central1-docker.pkg.dev/operator-486214/eval/ycsb:latest
```

All builds MUST use `--platform linux/amd64` (GCP VMs are amd64, dev machines may be ARM).
All builds use project root as context (except tikv-chaos and ycsb which use `subjects/tikv/`).

Build stale images in parallel when possible. Push sequentially after builds complete.

### 3. Enqueue Campaign

```bash
source $PROJECT_ROOT/.env
uv run eval run campaign $1 --cloud=gcp
```

Note the campaign ID from output.

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

Start each worker as a separate background Bash command with `run_in_background: true`:
```bash
source $PROJECT_ROOT/.env
for i in $(seq 1 ${NUM_WORKERS}); do
  uv run eval worker start --cloud=gcp --id=worker-$i \
    --operator-image=us-central1-docker.pkg.dev/operator-486214/eval/operator:latest
done
```

After starting, wait ~15 seconds and verify each worker claimed a work item by tailing their output files.

### 5. Report

Wait for the campaign to complete with live progress:

```bash
source $PROJECT_ROOT/.env && uv run eval wait <campaign_id> --remote
```

Run this as a background Bash command so you can continue working while it runs. It will show live progress and exit with a summary when all trials finish.

If the user needs to check status manually:
- `eval show <campaign_id> --remote`
- `eval worker status --remote`
- `eval viewer --remote` (web UI)

## Environment

- `$PROJECT_ROOT` is the git repo root (parent of eval/)
- `.env` at project root contains `EVAL_DATABASE_URL` and `ANTHROPIC_API_KEY`
- Working directory is `eval/`
