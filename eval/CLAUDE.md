# Eval System - Claude Context

This is a chaos engineering evaluation framework that tests how an autonomous operator system detects and resolves infrastructure issues. It orchestrates campaigns of trials where chaos is injected into a test subject (TiKV cluster), and an agent attempts to diagnose and fix the problem.

## Quick Orientation

```
eval/
├── src/eval/
│   ├── cli.py              # Main CLI entry point (typer app)
│   ├── types.py            # Core data models (Campaign, Trial, EvalSubject, VariantConfig)
│   ├── variants.py         # Variant configuration loading
│   ├── runner/
│   │   ├── campaign.py     # Campaign matrix expansion and config schema
│   │   ├── harness.py      # Trial execution engine
│   │   ├── db.py           # AsyncSQLite persistence (EvalDB)
│   │   └── operator.py     # Operator subprocess management
│   ├── analysis/
│   │   ├── types.py        # TrialScore, CampaignSummary models
│   │   ├── scoring.py      # Trial scoring (time-to-detect, time-to-resolve)
│   │   ├── comparison.py   # Campaign comparisons (baseline, variant)
│   │   └── commands.py     # LLM-based command classification
│   ├── subjects/
│   │   └── tikv/
│   │       ├── subject.py  # TiKVEvalSubject implementation
│   │       └── chaos.py    # Chaos injection (node_kill, latency, partition)
│   └── viewer/             # Web UI for browsing campaigns/trials
├── campaigns/              # Campaign YAML configs
├── variants/               # Agent configuration variants
└── eval.db                 # SQLite database (auto-created)
```

## Key Concepts

### Campaign
A structured test execution that runs multiple trials. Defined via YAML with:
- `subjects` - Systems to test (`tikv`, `chat-db-app`)
- `chaos_types` - List of chaos types with optional params
- `trials_per_combination` - Repetitions per subject/chaos combo
- `variant` - Agent configuration to use
- `include_baseline` - Whether to run baseline (no-chaos) trials

### Trial
A single execution cycle:
1. Reset subject to clean state
2. Capture initial state
3. Inject chaos → record `chaos_injected_at`
4. Wait for agent to detect (`ticket_created_at`) and resolve (`resolved_at`)
5. Capture final state and commands
6. Cleanup chaos (always runs)

### Analysis
Computes metrics from trials:
- **Time-to-detect**: `chaos_injected_at` → `ticket_created_at`
- **Time-to-resolve**: `chaos_injected_at` → `resolved_at`
- **Win rate**: successful resolutions / total trials
- **Command analysis**: count, unique, destructive (via LLM classification)

## CLI Commands

```bash
# Run single trial
eval run --subject tikv --chaos node_kill --trials 1

# Run campaign from YAML
eval run campaign campaigns/full-chaos.yaml

# With external operator (not managed)
eval run campaign config.yaml --operator-running

# Override model
eval run campaign config.yaml --model claude-opus-4-20250514

# Analyze campaign
eval analyze 1              # Campaign ID 1
eval analyze 1 --commands   # Include LLM command classification

# Compare campaigns
eval compare 1 2                        # Two campaigns
eval compare-baseline 1                 # Agent vs auto-found baseline
eval compare-variants tikv node_kill    # All variants for subject/chaos

# List and view
eval list                   # List all campaigns
eval show 1                 # Campaign details
eval show --trial 5         # Trial details

# Web UI
eval viewer                 # http://127.0.0.1:8000
```

## Data Models

### Campaign (types.py)
```python
@dataclass
class Campaign:
    id: int | None
    subject_name: str      # "tikv"
    name: str              # Campaign suite name (e.g., "my-chaos-suite" or "tikv/node_kill")
    trial_count: int
    baseline: bool = False
    variant_name: str = "default"
    created_at: str        # ISO8601
```

### Trial (types.py)
```python
@dataclass
class Trial:
    id: int | None
    campaign_id: int
    started_at: str           # ISO8601
    chaos_injected_at: str    # When chaos was injected
    ticket_created_at: str | None  # When agent detected issue
    resolved_at: str | None   # When agent resolved issue
    ended_at: str
    initial_state: str        # JSON
    final_state: str          # JSON
    chaos_metadata: str       # JSON (for cleanup)
    commands_json: str        # JSON array of agent commands
```

### TrialScore (analysis/types.py)
```python
class TrialScore(BaseModel):
    trial_id: int
    outcome: TrialOutcome     # SUCCESS | FAILURE | TIMEOUT
    resolved: bool
    time_to_detect_sec: float | None
    time_to_resolve_sec: float | None
    command_count: int
    unique_commands: int
    destructive_count: int
```

## Chaos Types

### TiKV

| Type | Implementation | Parameters |
|------|----------------|------------|
| `node_kill` | SIGKILL TiKV container | None |
| `latency` | tc netem on TiKV | `min_ms`, `max_ms` |
| `network_partition` | iptables block TiKV ↔ peers and TiKV ↔ PD | None |
| `process_pause` | SIGSTOP/SIGCONT (freeze process) | None |
| `packet_loss` | tc netem intermittent failures | `percent` |
| `asymmetric_partition` | Block traffic to one peer only | None |
| `pd_leader_kill` | Kill random PD control plane node | None |
| `leader_concentration` | Concentrate all region leaders on one store | None |
| `disk_pressure` | Fill tmpfs (cloud only) | None |

### Chat-DB-App

| Type | Implementation | Parameters |
|------|----------------|------------|
| `load_pressure` | Increase loadgen intensity | `NUM_USERS`, `REQUEST_DELAY`, `STREAM_RATIO` |
| `db_disconnect` | Block VM ↔ Cloud SQL traffic (cloud only) | None |
| `debug_code_edit` | Inject subtle bugs into app code (cloud only) | None |

## Variants

Agent configuration for A/B testing (`eval/variants/*.yaml`):

```yaml
name: default
model: claude-sonnet-4-5-20250929
system_prompt: |
  You are an SRE operator...
tools_config:
  tool_choice: auto
  enabled_tools:
    - shell
```

## Campaign Config Example

```yaml
name: full-chaos-campaign
subjects: [tikv]
chaos_types:
  - type: node_kill
  - type: latency
    params:
      min_ms: 50
      max_ms: 150
trials_per_combination: 3
parallel: 1
cooldown_seconds: 10
include_baseline: true
variant: "default"
```

## Database Schema

**campaigns table:**
- `id`, `subject_name`, `chaos_type` (deprecated), `name`, `trial_count`, `baseline`, `variant_name`, `created_at`

**trials table:**
- `id`, `campaign_id`, `started_at`, `chaos_injected_at`, `ticket_created_at`, `resolved_at`, `ended_at`
- `initial_state`, `final_state`, `chaos_metadata`, `commands_json`

## Key Files for Common Tasks

| Task | File |
|------|------|
| Add new chaos type | `subjects/tikv/chaos.py`, `subject.py` |
| Modify trial execution | `runner/harness.py` |
| Change scoring logic | `analysis/scoring.py` |
| Add comparison metric | `analysis/comparison.py` |
| New CLI command | `cli.py` |
| New subject | Create `subjects/newsubject/` with `subject.py` implementing `EvalSubject` |

## EvalSubject Protocol

All subjects must implement:

```python
class EvalSubject(Protocol):
    async def reset(self) -> None: ...
    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool: ...
    async def capture_state(self) -> dict[str, Any]: ...
    def get_chaos_types(self) -> list[str]: ...
    async def inject_chaos(self, chaos_type: str, **params) -> dict[str, Any]: ...
    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None: ...
```

## Parallel Execution

`SubjectPool` enables parallel trials with isolated Docker Compose projects:
- Each instance_id gets unique ports: `base_port + (id × 10,000)`
- Instance 0: ports 2379, 20160...
- Instance 1: ports 12379, 30160...

## Operator Integration

In managed mode, `OperatorProcesses` context manager:
1. Resets subject cluster
2. Removes old operator.db
3. Starts monitor subprocess (`operator monitor run --interval 5`)
4. Starts agent subprocess (`operator agent start`)
5. Trials run while operator active
6. Terminates both on exit

Commands extracted from `operator.db` via SQL query on `agent_log_entries` table.

## Documentation

`eval/README.md` is the user-facing source of truth for how to run campaigns. Keep it in sync when changing:

- CLI commands or flags
- Campaign YAML files (add/remove entries in the campaign tables)
- Supported subjects or chaos types
- Prerequisites or environment variables
- Analysis commands

The root `README.md` links to `eval/README.md` for eval details — don't duplicate instructions there.

## Running Tests

```bash
cd eval
uv run pytest tests/
```
