# GCP Cloud Eval Infrastructure

Run eval campaigns on GCP with distributed workers coordinated through Cloud SQL.

## Architecture

```
Your laptop                         GCP
┌──────────────┐           ┌────────────────────┐
│ eval run     │──enqueue──│  Cloud SQL          │
│ campaign ... │           │  (PostgreSQL 15)    │
└──────────────┘           └────────┬───────────┘
                                    │ poll
                           ┌────────┴───────────┐
                           │  Worker VMs (N)     │
                           │  e2-standard-2      │
                           │  Container-OS       │
                           │  ┌───────────────┐  │
                           │  │ eval worker   │  │
                           │  │ (Docker)      │  │
                           │  └───────────────┘  │
                           └─────────────────────┘
```

Workers pull from the Cloud SQL queue, execute trials (each in an isolated Docker TiKV cluster on the VM), and write results back.

## Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login`)
- Docker installed and running locally
- A GCP project with billing enabled
- `uv` installed for Python dependency management

## Quick Start

```bash
# 1. Set up GCP infrastructure (idempotent, safe to re-run)
./eval/scripts/gcp-setup.sh your-project-id

# 2. Verify the database is working
./eval/scripts/gcp-smoke-test.sh

# 3. Start workers
./eval/scripts/gcp-workers.sh start 3

# 4. Run a campaign
cd eval
source ../.env
uv run eval run campaign campaigns/smoke-test.yaml --cloud=gcp

# 5. Stop workers when done
./eval/scripts/gcp-workers.sh stop
```

## Scripts

### `gcp-setup.sh` - One-time infrastructure setup

Creates all GCP resources and saves configuration to `.env` at the project root.

```bash
./eval/scripts/gcp-setup.sh                  # Uses current gcloud project
./eval/scripts/gcp-setup.sh my-project-id    # Explicit project
```

**What it creates:**
| Resource | Name | Approx. Cost |
|----------|------|-------------|
| Cloud SQL (PostgreSQL 15) | `eval-db` | ~$7-9/mo (db-f1-micro) |
| Artifact Registry | `eval` | ~$0.10/GB stored |
| Instance Template | `eval-worker-template` | Free |
| Docker Image (pushed) | `eval/worker:latest` | Storage only |

**APIs enabled:** Compute Engine, Cloud SQL Admin, Artifact Registry

The script is idempotent - it checks for existing resources before creating them. Re-running it will update `.env` with current values and rebuild/push the Docker image.

### `gcp-workers.sh` - Worker VM management

```bash
./eval/scripts/gcp-workers.sh start 5       # Start 5 workers
./eval/scripts/gcp-workers.sh stop           # Stop all workers
./eval/scripts/gcp-workers.sh status         # List running workers
./eval/scripts/gcp-workers.sh logs <name>    # View worker container logs
./eval/scripts/gcp-workers.sh ssh <name>     # SSH into a worker

# Override zone (default: us-central1-a)
GCP_ZONE=us-west1-a ./eval/scripts/gcp-workers.sh start 3
```

Worker VMs run Container-Optimized OS with the eval worker Docker image. Each VM automatically starts a Cloud SQL Proxy sidecar for database access.

### `gcp-smoke-test.sh` - Database connectivity test

Validates that Cloud SQL is reachable and the queue system works (creates a test campaign, enqueues items, claims one, then cleans up).

```bash
./eval/scripts/gcp-smoke-test.sh
```

### `gcp-e2e-test.sh` - Full integration test

Runs a complete trial using Cloud SQL for coordination but local Docker for TiKV (no worker VMs needed). Good for validating the full pipeline without GCP compute costs.

```bash
./eval/scripts/gcp-e2e-test.sh                    # Default 10min timeout
./eval/scripts/gcp-e2e-test.sh --timeout 5         # 5 minute timeout
./eval/scripts/gcp-e2e-test.sh --cleanup-only      # Just clean up leftover containers
```

**Requires:** Docker running locally and the TiKV chaos image built:
```bash
docker compose -f subjects/tikv/docker-compose.yaml build
```

## Configuration

All configuration lives in `.env` at the project root (gitignored). See `eval/env.example` for the full list of variables.

The setup script auto-generates a database password and populates all GCP-specific values. The only thing you need to provide manually is `ANTHROPIC_API_KEY`.

## Costs and Cleanup

**Persistent resources** (billed even when idle):
- Cloud SQL `eval-db`: ~$7-9/month for `db-f1-micro`

**On-demand resources** (billed only when running):
- Worker VMs: ~$0.067/hr each for `e2-standard-2`

**Free:**
- Instance template, Artifact Registry (negligible storage)

### Tear down everything

```bash
# Stop workers
./eval/scripts/gcp-workers.sh stop

# Delete Cloud SQL (stops billing)
gcloud sql instances delete eval-db --quiet

# Delete Artifact Registry
gcloud artifacts repositories delete eval --location=us-central1 --quiet

# Delete instance template
gcloud compute instance-templates delete eval-worker-template --quiet
```

### Just stop the bleeding

```bash
# Stop the Cloud SQL instance (can restart later, no data loss)
gcloud sql instances patch eval-db --activation-policy=NEVER

# Restart it later
gcloud sql instances patch eval-db --activation-policy=ALWAYS
```

## Customization

The setup script currently hardcodes some values. To change them, edit the configuration block at the top of `eval/scripts/gcp-setup.sh`:

```bash
REGION="us-central1"          # GCP region
ZONE="${REGION}-a"            # Compute zone
DB_INSTANCE="eval-db"         # Cloud SQL instance name
DB_TIER="db-f1-micro"         # Cloud SQL machine type
```

For worker VMs, the machine type is set in the instance template creation (`e2-standard-2` with 20GB boot disk).
