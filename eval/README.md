# Eval - Chaos Engineering Framework

Runs campaigns of trials where chaos is injected into a test subject and an autonomous operator agent attempts to diagnose and resolve the problem.

## Prerequisites

### GCP Cloud Campaigns

Cloud campaigns run on GCP Compute Engine VMs. Before running:

```bash
# Authenticate with GCP (required — tokens expire)
gcloud auth login

# Verify auth works
gcloud compute instances list
```

### Environment Variables

Copy `.env` to the repo root (or ensure these are set):

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Agent LLM calls |
| `EVAL_DATABASE_URL` | Cloud PostgreSQL for distributed execution |
| `CHATDB_CLOUD_SQL_IP` | Chat DB App: Cloud SQL IP |
| `CHATDB_CLOUD_SQL_PASSWORD` | Chat DB App: Cloud SQL password |
| `CHATDB_APP_IMAGE` | Chat DB App: pre-built app image |
| `CHATDB_LOADGEN_IMAGE` | Chat DB App: pre-built loadgen image |
| `GCP_PROJECT` | GCP project ID |

## Running a Campaign

### 1. Enqueue

```bash
cd eval
source ../.env  # or set env vars

# Chat DB App — agent fixes code
uv run eval run campaign campaigns/chatdb-debug-edit.yaml --cloud=gcp

# TiKV — agent diagnoses infra chaos
uv run eval run campaign campaigns/cloud-smoke-operator.yaml --cloud=gcp
```

### 2. Start a Worker

```bash
uv run eval worker start --cloud=gcp \
  --operator-image=us-central1-docker.pkg.dev/operator-486214/eval/operator:latest
```

The worker claims items from the queue, provisions VMs, runs trials, and records results.

### 3. Monitor Progress

```bash
# Queue status
uv run eval worker status --remote

# Campaign details
uv run eval show <campaign_id> --remote

# Trial details
uv run eval show --trial <trial_id> --remote

# Web viewer
uv run eval viewer --remote
```

## Recovering from Failures

```bash
# Release stale work items (worker crashed)
uv run eval worker release-stale --remote

# Check for orphaned VMs
gcloud compute instances list --filter="name~chatdb OR name~tikv-eval"

# Delete orphaned VMs
gcloud compute instances delete <name> --zone=us-central1-a --quiet
```

## Campaign Configs

Campaign YAML files live in `eval/campaigns/`. Key fields:

```yaml
name: my-campaign
subjects: [chat-db-app]        # or [tikv]
chaos_types:
  - type: debug_code_edit      # chat-db-app chaos types
  - type: load_pressure
  - type: node_kill            # tikv chaos types
  - type: latency
    params: { min_ms: 50, max_ms: 150 }
trials_per_combination: 3
include_baseline: false
cloud:
  provider: gcp
  operator:
    enabled: true
    image: us-central1-docker.pkg.dev/operator-486214/eval/operator:latest
```

## Analysis

```bash
# Score a campaign
uv run eval analyze <campaign_id> --remote

# Compare two campaigns
uv run eval compare <id1> <id2> --remote

# Compare agent vs baseline
uv run eval compare-baseline <campaign_id> --remote
```

## Running Tests

```bash
cd eval
uv run pytest tests/
```
