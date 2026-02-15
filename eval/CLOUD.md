# Cloud Deployment Reference

Running eval campaigns on GCP. Covers terminology, architecture, Docker images, and the rebuild decision matrix.

## Terminology

| Term | Meaning |
|------|---------|
| **Worker (process)** | The Python process that polls the PostgreSQL work queue and executes trials. Runs inside a Docker container on a worker VM. Code: `runner/worker.py` |
| **Worker VM** | A GCP Compute Engine instance (Container-Optimized OS) that runs the worker container. Created from `eval-worker-template` via `gcp-workers.sh start N`. |
| **Trial VM** | An ephemeral GCP VM created per-trial by the worker. Runs the subject cluster (TiKV + PD + Prometheus + YCSB) and, when enabled, the operator (monitor + agent). Created by `GCPVM` in `subjects/cloud/gcp/vm.py`. Deleted after the trial completes (or pooled across trials of the same subject type). |
| **Operator** | The monitor + agent processes. On trial VMs these run as Docker containers (`operator-monitor`, `operator-agent`) managed by `RemoteOperatorProcesses`. |
| **Work queue** | A PostgreSQL table (`work_queue`) in Cloud SQL. The CLI enqueues work items; workers claim them atomically via `FOR UPDATE SKIP LOCKED`. |

## Architecture

```
 Your laptop                         GCP
 ──────────                          ───
                                ┌──────────────────┐
 eval run campaign              │   Cloud SQL        │
   --cloud=gcp  ──enqueue──────>│   (PostgreSQL)     │
                                │   work_queue table │
                                └────────┬───────────┘
                                         │ poll
                          ┌──────────────┼──────────────┐
                          │              │              │
                    ┌─────▼─────┐  ┌─────▼─────┐  ┌────▼──────┐
                    │ Worker VM │  │ Worker VM │  │ Worker VM │
                    │ (COS)     │  │ (COS)     │  │ (COS)     │
                    │           │  │           │  │           │
                    │ worker    │  │ worker    │  │ worker    │
                    │ container │  │ container │  │ container │
                    └─────┬─────┘  └───────────┘  └───────────┘
                          │ creates
                    ┌─────▼──────────────────────┐
                    │ Trial VM (COS, ephemeral)  │
                    │                            │
                    │  ┌─────────────────────┐   │
                    │  │ Subject cluster     │   │
                    │  │ (docker compose)    │   │
                    │  │ PD x3, TiKV x3,    │   │
                    │  │ Prometheus, YCSB    │   │
                    │  └─────────────────────┘   │
                    │  ┌─────────────────────┐   │
                    │  │ Operator (optional) │   │
                    │  │ monitor + agent     │   │
                    │  │ (docker compose)    │   │
                    │  └─────────────────────┘   │
                    └────────────────────────────┘
```

Key details:
- VMs have **no public IPs**. All SSH goes through IAP tunnels.
- Cloud NAT provides outbound internet (for pulling images, API calls).
- The worker reuses a single trial VM across trials of the same subject type (VM pooling). The VM is destroyed when the subject type changes or the worker shuts down.

## Docker Images

All images are pushed to Artifact Registry at `us-central1-docker.pkg.dev/PROJECT/eval/`.

### Image Tagging

Images are tagged with the **git commit SHA** (`git rev-parse --short HEAD`), not `:latest`. This enables concurrent sessions — two sessions on different commits use different images without overwriting each other. If the code hasn't changed (same commit), the image already exists and no rebuild/push is needed.

### 1. Worker (`eval/Dockerfile`)

| | |
|---|---|
| **Registry path** | `.../eval/worker:${GIT_SHA}` |
| **Base** | `python:3.12-slim` |
| **Contains** | Eval CLI + cloud deps, gcloud CLI, SSH client, subject compose files |
| **Runs on** | Worker VMs |

Build and push:
```bash
cd $PROJECT_ROOT
GIT_SHA=$(git rev-parse --short HEAD)
docker build --platform linux/amd64 -t eval-worker -f eval/Dockerfile .
docker tag eval-worker us-central1-docker.pkg.dev/PROJECT/eval/worker:${GIT_SHA}
docker push us-central1-docker.pkg.dev/PROJECT/eval/worker:${GIT_SHA}
```

### 2. Operator (`subjects/tikv/Dockerfile.operator`)

| | |
|---|---|
| **Registry path** | `.../eval/operator:${GIT_SHA}` |
| **Base** | `python:3.11-slim` |
| **Contains** | operator-core, operator-protocols, all subject observers, Docker CLI, Node.js 22, uv |
| **Runs on** | Trial VMs (as `operator-monitor` and `operator-agent` containers) |

Build and push:
```bash
cd $PROJECT_ROOT
GIT_SHA=$(git rev-parse --short HEAD)
docker build --platform linux/amd64 -t operator-eval -f subjects/tikv/Dockerfile.operator .
docker tag operator-eval us-central1-docker.pkg.dev/PROJECT/eval/operator:${GIT_SHA}
docker push us-central1-docker.pkg.dev/PROJECT/eval/operator:${GIT_SHA}
```

### 3. TiKV Chaos (`subjects/tikv/Dockerfile.tikv-chaos`)

| | |
|---|---|
| **Registry path** | `.../eval/tikv-chaos:v8.5.5` |
| **Base** | `pingcap/tikv:v8.5.5` (Rocky Linux 9) |
| **Contains** | TiKV + `iproute-tc`, `iptables`, `fallocate` (chaos injection tools) |
| **Runs on** | Trial VMs (as `tikv0`, `tikv1`, `tikv2` containers) |

Build and push:
```bash
cd $PROJECT_ROOT/subjects/tikv
docker build --platform linux/amd64 -t tikv-chaos:v8.5.5 -f Dockerfile.tikv-chaos .
docker tag tikv-chaos:v8.5.5 us-central1-docker.pkg.dev/PROJECT/eval/tikv-chaos:v8.5.5
docker push us-central1-docker.pkg.dev/PROJECT/eval/tikv-chaos:v8.5.5
```

### 4. YCSB (`subjects/tikv/Dockerfile.ycsb`)

| | |
|---|---|
| **Registry path** | `.../eval/ycsb:latest` |
| **Base** | `golang:1.21-alpine` (build) / `alpine:latest` (runtime) |
| **Contains** | `go-ycsb` binary + workload definitions |
| **Runs on** | Trial VMs (as `ycsb` container for background load generation) |

Build and push:
```bash
cd $PROJECT_ROOT/subjects/tikv
docker build --platform linux/amd64 -t ycsb -f Dockerfile.ycsb .
docker tag ycsb us-central1-docker.pkg.dev/PROJECT/eval/ycsb:latest
docker push us-central1-docker.pkg.dev/PROJECT/eval/ycsb:latest
```

## Do I Need to Rebuild?

| What changed | Rebuild image? | Notes |
|---|---|---|
| **operator-core** (monitor loop, agent, CLI) | **operator** | Agent behavior, monitoring logic, CLI commands |
| **operator-protocols** | **operator** | Interface definitions used by monitor + agent |
| **Subject observers** (tikv-observer, etc.) | **operator** | Invariant checkers, observation logic |
| **System prompt** (via variant YAML) | None | Loaded at runtime from `eval/variants/*.yaml` |
| **Variant config** (model, tools) | None | Loaded at runtime from `eval/variants/*.yaml` |
| **Eval CLI** (`eval/src/eval/`) | **worker** | Campaign runner, analysis, queue logic |
| **Chaos injection code** (`eval/src/eval/subjects/`) | **worker** | Chaos types, subject implementations |
| **Subject compose files** (`docker-compose.cloud.yaml`) | **worker** | Baked into worker image at `/usr/local/lib/subjects/` |
| **Prometheus config** (`config/prometheus.yml`) | None | Uploaded from worker to trial VM at runtime |
| **Campaign YAML** (`eval/campaigns/`) | None | Read by CLI on your laptop at enqueue time |
| **TiKV version or chaos tools** | **tikv-chaos** | Base TiKV image + tc/iptables |
| **YCSB workloads or version** | **ycsb** | go-ycsb binary + workload files |
| **gcp-setup.sh / gcp-workers.sh** | None | Scripts run on your laptop, not baked into images |

**Rebuilding the worker requires restarting worker VMs** (or re-pulling inside them). The operator image is pulled fresh on each trial by the worker, so operator rebuilds take effect on the next trial without restarting workers.

## Concurrent Sessions

Multiple `run-campaign` or `iterate-campaign` sessions can run simultaneously without conflicts. Isolation is split across two scoping keys:

| Resource | Scoped by | Why |
|----------|-----------|-----|
| Docker images | Git commit SHA | Same code = same image; different code = different tag. No overwrites. |
| Worker IDs | Campaign ID (`c${CID}-$i`) | Each campaign's workers are distinguishable in `ps` output. |
| Work claiming | Campaign ID (`--campaign=${CID}`) | Workers only claim work items from their campaign. |
| Worker logs | Campaign ID (`/tmp/c${CID}-$i.log`) | No log file collisions. |
| Cleanup (kill) | Campaign ID (`grep "c${CID}-"`) | Only kills one campaign's workers. |

Workers started **without** `--campaign` claim any pending work (backward compatible). Use `--campaign` when running concurrent sessions.

### Example: two campaigns in parallel

```bash
GIT_SHA=$(git rev-parse --short HEAD)

# Session A
eval run campaign campaigns/operations/tikv-all-chaos-cloud.yaml --cloud=gcp  # → campaign 109
eval worker start --cloud=gcp --id=c109-1 --campaign=109 \
  --operator-image=.../operator:${GIT_SHA}

# Session B (different terminal)
eval run campaign campaigns/coding/chatdb-cloud-all-defects.yaml --cloud=gcp  # → campaign 110
eval worker start --cloud=gcp --id=c110-1 --campaign=110 \
  --operator-image=.../operator:${GIT_SHA}

# Cleanup only session A
ps aux | grep "c109-" | grep "eval worker" | grep -v grep | awk '{print $2}' | xargs kill -9
```

## Runtime vs Baked-in

### Configured at runtime (no rebuild needed)

- **Variant config** (model, system prompt, tools) -- YAML files in `eval/variants/`, loaded by worker at trial time
- **Campaign config** -- YAML files read by `eval run campaign` on your laptop, work items stored in PostgreSQL
- **Prometheus config** -- `subjects/tikv/config/prometheus.yml`, uploaded via SCP from worker to trial VM
- **Environment variables** -- `ANTHROPIC_API_KEY`, `EVAL_DATABASE_URL`, etc. passed through to containers
- **`--operator-image` flag** -- which operator image the worker pulls for each trial
- **`--model` CLI override** -- overrides variant model at enqueue time

### Baked into images (rebuild required)

- **Operator code** -- monitor loop, agent, invariant checkers, CLI commands (in operator image)
- **Eval CLI code** -- campaign runner, chaos injection, queue logic, analysis (in worker image)
- **Subject compose files** -- `docker-compose.cloud.yaml` copied into worker image at build time
- **TiKV + chaos tools** -- base TiKV version and tc/iptables packages (in tikv-chaos image)
- **YCSB binary** -- compiled go-ycsb and workload definitions (in ycsb image)
- **System dependencies** -- gcloud CLI, Docker CLI, Node.js, Python version

## CLI Quick Reference

### Enqueue work

```bash
# From your laptop (requires EVAL_DATABASE_URL in env)
source .env
eval run campaign campaigns/operations/tikv-full-chaos.yaml --cloud=gcp

# With operator (agent diagnoses + resolves)
eval run campaign config.yaml --cloud=gcp --operator-image=us-central1-docker.pkg.dev/PROJECT/eval/operator:$(git rev-parse --short HEAD)

# Override model
eval run campaign config.yaml --cloud=gcp --model claude-sonnet-4-5-20250929
```

### Start/stop workers

```bash
# Start 5 worker VMs from instance template
./scripts/gcp-workers.sh start 5

# Check running workers
./scripts/gcp-workers.sh status

# View worker container logs
./scripts/gcp-workers.sh logs eval-worker-XXXX-1

# SSH into a worker VM
./scripts/gcp-workers.sh ssh eval-worker-XXXX-1

# Stop all workers (deletes VMs)
./scripts/gcp-workers.sh stop
```

### Monitor progress

```bash
# Queue status (campaigns + work items)
eval worker status --remote

# Per-worker activity
eval worker workers --remote

# Campaign details
eval show <campaign_id> --remote
```

### Recovery

```bash
# Release stale items (worker crashed mid-trial)
eval worker release-stale --remote
eval worker release-stale --remote --timeout 1800  # 30min threshold

# Retry failed items
eval worker retry-failed --remote --campaign 59

# Cancel pending items
eval worker cancel --remote --campaign 59

# Kill campaign (cancel pending + running)
eval worker kill 62 --remote
```

## Infrastructure Setup

First-time setup is done by `scripts/gcp-setup.sh`:

```bash
./scripts/gcp-setup.sh my-project-id
```

This creates (idempotently):
1. Cloud SQL PostgreSQL instance (`eval-db`)
2. Artifact Registry repository (`eval`)
3. Cloud NAT + static IP (outbound internet for VMs without public IPs)
4. IAP firewall rule (SSH tunneling)
5. Instance template (`eval-worker-template`) with startup script
6. Builds and pushes all 4 Docker images
7. Writes connection details to `.env`
