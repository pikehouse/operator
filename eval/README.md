# Eval - Chaos Engineering Framework

Runs campaigns of trials where chaos is injected into a test subject and an autonomous operator agent attempts to diagnose and resolve the problem.

## Prerequisites

- Docker and Docker Compose running
- Python 3.12+
- `uv` package manager
- `ANTHROPIC_API_KEY` set in environment (or in `.env` at repo root)

## Running Local Campaigns

Local campaigns run against Docker Compose clusters on your machine. No cloud setup needed.

### Quick start: TiKV smoke test

```bash
cd eval
uv run eval run campaign campaigns/smoke-tests/tikv-smoke.yaml
```

This runs 1 trial each of `node_kill`, `latency`, and `network_partition` against a local TiKV cluster. The harness starts Docker Compose, runs the operator, injects chaos, waits for detection and resolution, and records results.

### Available local campaigns

| Campaign | Subject | What it tests |
|----------|---------|---------------|
| `smoke-tests/tikv-smoke.yaml` | tikv | node_kill, latency, network_partition (1 trial each) |
| `operations/tikv-node-kill.yaml` | tikv | node_kill only (1 trial) |
| `operations/tikv-all-chaos-local.yaml` | tikv | All 8 local-safe chaos types (3 trials each, + baseline) |
| `operations/tikv-cascading-failures.yaml` | tikv | pd_leader_kill, node_kill (3 trials each) |
| `operations/tikv-diagnostic-difficulty.yaml` | tikv | process_pause, packet_loss, asymmetric_partition (3 trials each) |
| `operations/tikv-subtle-gradual.yaml` | tikv | leader_concentration, process_pause (3 trials each) |
| `coding/chatdb-code-fix.yaml` | chat-db-app | load_pressure (3 trials) |
| `coding/chatdb-missing-index.yaml` | chat-db-app | missing_index (3 trials) |
| `coding/chatdb-pool-exhaustion.yaml` | chat-db-app | pool_exhaustion (3 trials) |
| `coding/chatdb-streaming-txn.yaml` | chat-db-app | streaming_txn (3 trials) |
| `coding/chatdb-counter-race.yaml` | chat-db-app | counter_race (3 trials) |
| `coding/chatdb-all-defects.yaml` | chat-db-app | all 4 per-defect types (3 trials each) |
| `coding/chatdb-continuous-defects.yaml` | chat-db-app | missing_index, pool_exhaustion, streaming_txn — continuous mode (no reset between trials) |
| `coding/chatdb-db-sharding.yaml` | chat-db-app-shard | db_sharding — 2M messages on constrained PG, requires horizontal sharding (2 trials, 15min timeout) |
| `coding/chatdb-shard-baseline.yaml` | chat-db-app-shard | db_sharding baseline prompt — passive "consider horizontal scaling" (2 trials, 15min timeout) |
| `coding/chatdb-shard-nudge.yaml` | chat-db-app-shard | db_sharding_nudge — narrative prompt that closes code escape hatches (2 trials, 15min timeout) |
| `coding/chatdb-shard-direct.yaml` | chat-db-app-shard | db_sharding_direct — explicit "implement sharding" mission prompt (2 trials, 15min timeout) |

### Running any local campaign

```bash
cd eval
uv run eval run campaign campaigns/<campaign-file>.yaml
```

### Running a single trial

```bash
cd eval
uv run eval run --subject tikv --chaos node_kill --trials 1
```

## Running Cloud Campaigns (GCP)

Cloud campaigns provision GCP VMs, run trials there, and store results in a shared PostgreSQL database. See [CLOUD.md](CLOUD.md) for the full cloud architecture reference (terminology, Docker images, rebuild decision matrix).

### Cloud prerequisites

```bash
# Authenticate with GCP (tokens expire — re-run if needed)
gcloud auth login
gcloud compute instances list  # Verify auth works
```

Ensure `.env` at repo root has:

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Agent LLM calls |
| `EVAL_DATABASE_URL` | Cloud PostgreSQL for distributed execution |
| `GCP_PROJECT` | GCP project ID |
| `CHATDB_APP_IMAGE` | Chat DB App: pre-built app image |
| `CHATDB_LOADGEN_IMAGE` | Chat DB App: pre-built loadgen image |

### Enqueue a cloud campaign

```bash
cd eval
source ../.env

# TiKV cloud smoke test
uv run eval run campaign campaigns/smoke-tests/tikv-cloud-smoke.yaml --cloud=gcp

# Chat DB App debug test
uv run eval run campaign campaigns/coding/chatdb-cloud-debug-edit.yaml --cloud=gcp

# Chat DB App load stress test
uv run eval run campaign campaigns/coding/chatdb-cloud-load-stress.yaml --cloud=gcp
```

### Start a worker

```bash
cd eval
GIT_SHA=$(git rev-parse --short HEAD)
uv run eval worker start --cloud=gcp \
  --operator-image=us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}
```

The worker claims items from the queue, provisions VMs, runs trials, and records results.

#### Running concurrent campaigns

Use `--campaign` to scope workers to a specific campaign. This prevents workers from stealing work items from other campaigns running in parallel:

```bash
# Campaign A (terminal 1)
uv run eval run campaign campaigns/operations/tikv-all-chaos-cloud.yaml --cloud=gcp  # → campaign 109
uv run eval worker start --cloud=gcp --id=c109-1 --campaign=109 \
  --operator-image=us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}

# Campaign B (terminal 2)
uv run eval run campaign campaigns/coding/chatdb-cloud-all-defects.yaml --cloud=gcp  # → campaign 110
uv run eval worker start --cloud=gcp --id=c110-1 --campaign=110 \
  --operator-image=us-central1-docker.pkg.dev/${GCP_PROJECT}/eval/operator:${GIT_SHA}
```

Without `--campaign`, workers claim any pending work item (backward compatible for single-campaign use).

### Available cloud campaigns

| Campaign | Subject | What it tests |
|----------|---------|---------------|
| `smoke-tests/tikv-cloud-smoke.yaml` | tikv | node_kill (1 trial) |
| `coding/chatdb-cloud-debug-edit.yaml` | chat-db-app | debug_code_edit (1 trial) |
| `smoke-tests/chatdb-cloud-smoke.yaml` | chat-db-app | load_pressure (1 trial) |
| `operations/tikv-cloud-exotic-chaos.yaml` | tikv | process_pause, packet_loss, asymmetric_partition, pd_leader_kill, leader_concentration (3 trials each) |
| `operations/tikv-all-chaos-cloud.yaml` | tikv | All 10 chaos types incl. disk_pressure (3 trials each, + baseline) |
| `coding/chatdb-cloud-load-stress.yaml` | chat-db-app | load_pressure at 50 users / 0.6 stream ratio (5 trials) |
| `coding/chatdb-shard-gradient-cloud.yaml` | chat-db-app-shard | Prompt gradient A/B: db_sharding vs db_sharding_nudge vs db_sharding_direct (2 trials each, 15min timeout) |
| `coding/chatdb-shard-escalation-cloud.yaml` | chat-db-app-shard | Continuous 2-phase: db_sharding_direct (15min) → shard_fanout (30min) |
| `coding/chatdb-shard-escalation-opus-cloud.yaml` | chat-db-app-shard | Same as above but with Opus 4.6 variant for A/B comparison |

### Monitor cloud progress

```bash
cd eval

# Queue status
uv run eval worker status --remote

# Campaign details
uv run eval show <campaign_id> --remote

# Trial details
uv run eval show --trial <trial_id> --remote

# Web viewer
uv run eval viewer --remote
```

## Analysis

After campaigns complete, analyze and compare results:

```bash
cd eval

# List all campaigns
uv run eval list
uv run eval list --notable                      # Only notable campaigns

# Mark campaigns as notable (significant results worth revisiting)
uv run eval notable <campaign_id>
uv run eval notable <campaign_id> --clear       # Unmark

# Annotate campaigns with notes
uv run eval note <campaign_id> "Reference baseline for TiKV node_kill"
uv run eval note <campaign_id>                  # View current note
uv run eval note <campaign_id> --clear          # Clear

# Score a campaign
uv run eval analyze <campaign_id>
uv run eval analyze <campaign_id> --commands    # Include LLM command classification

# Compare two campaigns
uv run eval compare <id1> <id2>

# Compare agent vs auto-found baseline
uv run eval compare-baseline <campaign_id>

# Web UI
uv run eval viewer                              # http://127.0.0.1:8000
```

For cloud results, add `--remote` to commands above.

## Exporting Results

Export a campaign as a self-contained HTML file that can be opened in any browser — no server needed:

```bash
cd eval

# Export to default file (campaign-<id>.html)
uv run eval export <campaign_id>

# Custom output path
uv run eval export <campaign_id> -o results.html

# Export from cloud database
uv run eval export <campaign_id> --remote
```

The exported HTML includes campaign summary, trial table, reasoning timelines, code diffs, DB config changes, and topology diagrams — all embedded with no external dependencies.

## Publishing Results

Publish a campaign to the [operator-campaigns](https://github.com/pikehouse/operator-campaigns) repo with a single command. This exports the HTML, captures the subject's source code as an orphan branch, generates a README with links, and pushes to GitHub:

```bash
cd eval

# Publish from cloud database
uv run eval publish <campaign_id> --remote

# Dry run (commit locally, don't push)
uv run eval publish <campaign_id> --remote --dry-run

# Skip source branch or behavior classification
uv run eval publish <campaign_id> --remote --skip-source
uv run eval publish <campaign_id> --remote --skip-behavior
```

Requires `OPERATOR_RESULTS_REPO_LOCATION` in your `.env` (path to a local clone of the results repo). Re-publishing the same campaign updates the existing HTML and recreates the source branch.

## Campaign Config Reference

Campaign YAML files live in `eval/campaigns/` organized by category (`smoke-tests/`, `coding/`, `operations/`). Key fields:

```yaml
name: my-campaign
subjects: [tikv]                 # tikv or chat-db-app
chaos_types:
  - type: node_kill
  - type: latency
    params: { min_ms: 50, max_ms: 150 }
trials_per_combination: 3        # Repetitions per subject/chaos combo
parallel: 1                      # Parallel instances (isolated Docker projects)
cooldown_seconds: 10             # Wait between trials
include_baseline: false          # Run no-chaos baseline trials
continuous: false                # Skip reset between trials (stacking defects)
variant: default                 # Agent config variant (see eval/variants/)
cloud:                           # Omit for local campaigns
  provider: gcp
  operator:
    enabled: true
    image: us-central1-docker.pkg.dev/$GCP_PROJECT/eval/operator:${GIT_SHA}
```

## Chat-DB-App Chaos Types

Each chaos type targets a specific defect in the app by shaping load patterns:

| Type | What it triggers | Expected invariants |
|------|-----------------|---------------------|
| `missing_index` | Sequential scans on messages table (no index) | `high_latency` |
| `pool_exhaustion` | Unbounded pool hits max_connections | `pool_exhaustion`, `high_error_rate` |
| `streaming_txn` | Streaming holds transactions open 10-30s | `idle_in_transaction`, `pool_exhaustion` |
| `counter_race` | Concurrent writes race on token counter | `lock_contention` |
| `load_pressure` | Backward-compat alias for `pool_exhaustion` | (same as pool_exhaustion) |

## Recovering from Cloud Failures

```bash
# Release stale work items (worker crashed)
uv run eval worker release-stale --remote

# Check for orphaned VMs
gcloud compute instances list --filter="name~chatdb OR name~tikv-eval"

# Delete orphaned VMs
gcloud compute instances delete <name> --zone=us-central1-a --quiet
```

## Running Tests

```bash
cd eval
uv run pytest tests/
```
