# Phase 36: Analysis Layer - Research

**Researched:** 2026-01-29
**Domain:** Post-hoc analysis and comparison of chaos engineering trial data
**Confidence:** HIGH

## Summary

This research covers building an analysis layer that computes metrics from stored trial data and compares performance across campaigns. The layer must compute time-to-detect and time-to-resolve scores from ISO8601 timestamps, classify commands using LLM analysis, and provide comparison tools showing agent vs baseline and campaign vs campaign performance.

The standard approach uses Python's built-in `datetime.fromisoformat()` for parsing ISO8601 timestamps and calculating durations, Anthropic's Claude API with structured outputs for command classification (avoiding brittle pattern matching), and simple dataclass-based result objects for idempotent analysis. The context decision specifies plain text output (no colors), LLM-based command classification, and win rate as the primary comparison metric.

Key findings:
- Python stdlib datetime handles ISO8601 parsing and timedelta calculations without external dependencies
- Claude API structured outputs (beta) guarantee valid JSON schema compliance for command classification
- Batch API reduces cost by up to 50% for bulk classification tasks
- Idempotent analysis means reading from trials table, computing in-memory, returning results (no database mutations)
- Rich library supports plain text table output via `Console(force_terminal=False)` or direct string formatting

**Primary recommendation:** Use stdlib datetime for duration calculations, Claude Haiku 4.5 with structured outputs for command classification, dataclass results for type safety, and Rich tables with plain text mode for CLI output. Add `--json` flag using Pydantic's `.model_dump_json()` for machine-readable output.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| datetime | stdlib | ISO8601 parsing and timedelta calculations | Built-in, no dependencies, handles timezone-aware datetimes |
| anthropic | 0.40.0+ | Claude API for command classification | Already in operator-core, structured outputs support |
| pydantic | 2.0.0+ | Data models and JSON serialization | Already in project, type-safe results |
| rich | 14.0.0+ | Table formatting for CLI output | Already in project, supports plain text mode |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typer | 0.21.0+ | CLI commands (analyze, compare) | Already in project for eval CLI |
| aiosqlite | 0.20.0+ | Read trial data from eval.db | Already in project from Phase 35 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Claude structured outputs | Hardcoded regex patterns | Patterns are brittle, miss edge cases; LLM adapts to command variations |
| datetime stdlib | isodate/timedelta-isoformat | External deps for ISO8601 durations; stdlib sufficient for our use case |
| Rich tables | tabulate library | tabulate has plain format but Rich already in project |
| Batch API | Individual API calls | Batch reduces cost 50% but adds latency; use for bulk, not real-time |

**Installation:**
```bash
# Already satisfied by existing dependencies
# Only new dependency needed:
cd eval
uv pip install "anthropic>=0.40.0"
```

## Architecture Patterns

### Recommended Project Structure
```
eval/src/eval/
├── analysis/
│   ├── __init__.py
│   ├── scoring.py           # Time-to-detect, time-to-resolve calculations
│   ├── commands.py          # Command classification via Claude API
│   ├── comparison.py        # Baseline and campaign comparisons
│   └── types.py             # Result dataclasses (TrialScore, ComparisonResult)
└── cli.py                   # Add analyze, compare, compare-baseline commands
```

### Pattern 1: Idempotent Analysis with Dataclass Results

**What:** Analysis functions read from database, compute in-memory, return typed results without mutating database state. Can re-run on old campaigns without side effects.

**When to use:** Post-hoc analysis where results should be reproducible and don't need caching.

**Example:**
```python
# Source: Project design pattern
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TrialScore:
    """Computed metrics for a single trial."""
    trial_id: int
    resolved: bool  # Did agent resolve it?
    time_to_detect_sec: float | None  # chaos_injected -> ticket_created
    time_to_resolve_sec: float | None  # chaos_injected -> resolved
    command_count: int
    unique_commands: int
    destructive_count: int

async def score_trial(db: EvalDB, trial_id: int) -> TrialScore:
    """Compute trial score from stored data (idempotent)."""
    trial = await db.get_trial(trial_id)

    # Parse ISO8601 timestamps
    chaos_time = datetime.fromisoformat(trial.chaos_injected_at)

    # Compute time-to-detect (ANAL-01)
    time_to_detect = None
    if trial.ticket_created_at:
        ticket_time = datetime.fromisoformat(trial.ticket_created_at)
        time_to_detect = (ticket_time - chaos_time).total_seconds()

    # Compute time-to-resolve (ANAL-01)
    time_to_resolve = None
    if trial.resolved_at:
        resolve_time = datetime.fromisoformat(trial.resolved_at)
        time_to_resolve = (resolve_time - chaos_time).total_seconds()

    # Resolution requires BOTH ticket resolved AND cluster healthy
    resolved = trial.resolved_at is not None and trial.final_state_healthy

    return TrialScore(
        trial_id=trial_id,
        resolved=resolved,
        time_to_detect_sec=time_to_detect,
        time_to_resolve_sec=time_to_resolve,
        command_count=...,  # From command analysis
        unique_commands=...,
        destructive_count=...,
    )
```

### Pattern 2: LLM Command Classification with Structured Outputs

**What:** Use Claude API with structured outputs to classify commands into categories (diagnostic, remediation, destructive, etc.) instead of brittle regex patterns. Batch API for bulk classification.

**When to use:** When you need semantic understanding of command intent that adapts to variations.

**Example:**
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
from anthropic import Anthropic
from pydantic import BaseModel

class CommandClassification(BaseModel):
    """Structured output for command classification."""
    command: str
    category: str  # diagnostic, remediation, destructive, other
    reasoning: str
    is_destructive: bool

async def classify_commands(commands: list[str]) -> list[CommandClassification]:
    """Classify commands using Claude with structured outputs (ANAL-02, ANAL-03)."""
    client = Anthropic()

    # Use Haiku for cost-effective classification
    response = client.messages.create(
        model="claude-haiku-4.5",
        max_tokens=1024,
        temperature=0,  # Deterministic for idempotent results
        messages=[{
            "role": "user",
            "content": f"""Classify these shell commands into categories:
- diagnostic: reading state, checking status (e.g., docker ps, curl)
- remediation: fixing issues (e.g., docker restart, kubectl rollout)
- destructive: data loss risk (e.g., docker rm -f, rm -rf)
- other: uncategorized

Commands:
{chr(10).join(commands)}

For each command, explain your reasoning."""
        }],
        output_format={
            "type": "json",
            "schema": CommandClassification.model_json_schema()
        },
        extra_headers={
            "anthropic-beta": "structured-outputs-2025-11-13"
        }
    )

    # Parse guaranteed-valid JSON
    return [CommandClassification.model_validate_json(r) for r in response.content]
```

### Pattern 3: Win Rate Comparison with Delta Display

**What:** Compare campaigns by win rate (resolution percentage), with faster average resolution as tiebreaker. Display side-by-side with deltas.

**When to use:** Campaign vs campaign and agent vs baseline comparisons.

**Example:**
```python
# Source: Project design pattern
from dataclasses import dataclass

@dataclass
class ComparisonResult:
    """Side-by-side campaign comparison."""
    campaign_a_id: int
    campaign_b_id: int
    a_win_rate: float  # 0.0 to 1.0
    b_win_rate: float
    a_avg_resolve_sec: float | None
    b_avg_resolve_sec: float | None
    winner: str  # "A", "B", or "tie"

async def compare_campaigns(
    db: EvalDB,
    campaign_a_id: int,
    campaign_b_id: int
) -> ComparisonResult:
    """Compare two campaigns by win rate, then speed (ANAL-05)."""
    a_trials = await db.get_trials(campaign_a_id)
    b_trials = await db.get_trials(campaign_b_id)

    a_scores = [await score_trial(db, t.id) for t in a_trials]
    b_scores = [await score_trial(db, t.id) for t in b_trials]

    a_win_rate = sum(1 for s in a_scores if s.resolved) / len(a_scores)
    b_win_rate = sum(1 for s in b_scores if s.resolved) / len(b_scores)

    # Tiebreaker: faster average resolution time
    if a_win_rate == b_win_rate:
        a_avg = mean([s.time_to_resolve_sec for s in a_scores if s.resolved])
        b_avg = mean([s.time_to_resolve_sec for s in b_scores if s.resolved])
        winner = "A" if a_avg < b_avg else "B"
    else:
        winner = "A" if a_win_rate > b_win_rate else "B"

    return ComparisonResult(
        campaign_a_id=campaign_a_id,
        campaign_b_id=campaign_b_id,
        a_win_rate=a_win_rate,
        b_win_rate=b_win_rate,
        winner=winner,
        ...
    )
```

### Pattern 4: Plain Text Table Output

**What:** Use Rich tables without color/styling for pipeable output. Add `--json` flag for machine-readable format.

**When to use:** CLI tools that need to be scriptable and pipeable.

**Example:**
```python
# Source: https://github.com/Textualize/rich (plain text mode)
from rich.console import Console
from rich.table import Table

def display_comparison(result: ComparisonResult, json_output: bool = False):
    """Display comparison in plain text or JSON (CLI-05)."""
    if json_output:
        print(result.model_dump_json(indent=2))
        return

    # Plain text table (no colors)
    console = Console(force_terminal=False, legacy_windows=False)

    table = Table(show_header=True, header_style=None)
    table.add_column("Metric")
    table.add_column("Campaign A")
    table.add_column("Campaign B")
    table.add_column("Delta")

    table.add_row(
        "Win Rate",
        f"{result.a_win_rate:.1%}",
        f"{result.b_win_rate:.1%}",
        f"{(result.b_win_rate - result.a_win_rate):+.1%}"
    )

    table.add_row(
        "Avg Resolve Time",
        f"{result.a_avg_resolve_sec:.1f}s",
        f"{result.b_avg_resolve_sec:.1f}s",
        f"{(result.b_avg_resolve_sec - result.a_avg_resolve_sec):+.1f}s"
    )

    console.print(table)
    console.print(f"\nWinner: Campaign {result.winner}")
```

### Anti-Patterns to Avoid

- **Caching analysis results in database:** Breaks idempotency requirement (ANAL-06). Always compute from raw trial data.
- **Hardcoded destructive command patterns:** Brittle, misses variations like `docker kill` vs `docker rm -f`. Use LLM classification.
- **Colored output by default:** Context decision specifies plain text. Only use color if explicitly requested (future feature).
- **Synchronous Claude API calls in loop:** Use batch API or async client for multiple commands to reduce cost and latency.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ISO8601 duration parsing | Custom regex parser | `datetime.fromisoformat()` | Handles timezones, DST, leap seconds correctly |
| Command pattern matching | Regex dictionaries | Claude structured outputs | Adapts to command variations, understands intent |
| JSON serialization of dataclasses | Manual `__dict__` conversion | Pydantic `.model_dump_json()` | Handles nested objects, dates, None values |
| Table formatting | String concatenation with spaces | Rich Table | Handles alignment, wrapping, width calculation |

**Key insight:** LLM classification is more maintainable than pattern matching for semantic tasks. The cost is negligible (Haiku is $0.25/MTok input, $1.25/MTok output) and results are more accurate.

## Common Pitfalls

### Pitfall 1: Naive Datetime Arithmetic with Timezones

**What goes wrong:** Mixing timezone-naive and timezone-aware datetimes causes `TypeError` or incorrect duration calculations.

**Why it happens:** Trial timestamps from Phase 35 use `datetime.now(timezone.utc).isoformat()` which produces timezone-aware strings like `2026-01-29T10:30:00+00:00`.

**How to avoid:**
- Always parse with `datetime.fromisoformat()` which preserves timezone info
- Confirm all trial timestamps use UTC (check Phase 35 implementation)
- Timedelta calculations work correctly when both datetimes have same timezone

**Warning signs:**
- `TypeError: can't subtract offset-naive and offset-aware datetimes`
- Duration calculations off by hours (timezone offset not accounted for)

**Example:**
```python
# WRONG: Assuming naive datetime
chaos_time = datetime.fromisoformat(trial.chaos_injected_at.replace("+00:00", ""))

# RIGHT: Preserve timezone info
chaos_time = datetime.fromisoformat(trial.chaos_injected_at)
ticket_time = datetime.fromisoformat(trial.ticket_created_at)
duration = (ticket_time - chaos_time).total_seconds()  # Correct with both timezone-aware
```

### Pitfall 2: Non-Idempotent LLM Classification

**What goes wrong:** Different runs produce different classifications for the same command due to temperature > 0 or prompt ambiguity.

**Why it happens:** LLMs are stochastic by default. Anthropic API uses temperature=1.0 unless specified.

**How to avoid:**
- Set `temperature=0` for deterministic output
- Use structured outputs to constrain response format
- Include clear category definitions in prompt
- Consider caching classification results if truly idempotent (but conflicts with ANAL-06 requirement)

**Warning signs:**
- Same command classified differently on re-runs
- Flaky tests for analysis functions
- Users report inconsistent scores

### Pitfall 3: Resolution Definition Ambiguity

**What goes wrong:** Counting trial as "resolved" when ticket marked resolved but cluster still unhealthy, or vice versa.

**Why it happens:** Context decision states "Resolution requires BOTH: ticket marked resolved AND cluster healthy". Trial record has `resolved_at` timestamp and `final_state` dict but no `final_state_healthy` boolean.

**How to avoid:**
- Document resolution criteria clearly in code comments
- Implement `is_healthy()` helper that checks `final_state` dict against subject-specific health criteria
- For TiKV: check all nodes running, PD leader elected, regions balanced
- Store health determination logic in subject-specific module, not analysis layer

**Warning signs:**
- Baseline trials showing 100% resolution (cluster self-healed but no ticket)
- Agent trials showing 0% resolution (ticket resolved but verification failed)

### Pitfall 4: Comparison with Mismatched Campaigns

**What goes wrong:** Comparing campaigns with different subjects (TiKV vs RateLimiter) or different chaos types (node_kill vs latency).

**Why it happens:** Database schema allows any campaign to be compared with any other.

**How to avoid:**
- Validate campaigns have same `subject_name` before comparing
- Validate campaigns have same `chaos_type` before comparing
- Display warning if trial counts differ significantly
- Document comparison constraints in help text

**Warning signs:**
- Nonsensical comparisons like "TiKV node_kill vs RateLimiter redis_kill"
- Win rates that don't make intuitive sense

## Code Examples

Verified patterns from official sources:

### Datetime Duration Calculation
```python
# Source: https://docs.python.org/3/library/datetime.html
from datetime import datetime

def compute_duration_seconds(start_iso: str, end_iso: str) -> float:
    """Compute duration in seconds between ISO8601 timestamps."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return (end - start).total_seconds()

# Example with Phase 35 trial data
trial.chaos_injected_at  # "2026-01-29T10:30:00.123456+00:00"
trial.ticket_created_at  # "2026-01-29T10:30:45.789012+00:00"

time_to_detect = compute_duration_seconds(
    trial.chaos_injected_at,
    trial.ticket_created_at
)  # 45.665556 seconds
```

### Structured Outputs for Command Classification
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
import anthropic
from pydantic import BaseModel

class CommandAnalysis(BaseModel):
    total_count: int
    unique_count: int
    destructive_count: int
    categories: dict[str, int]  # category name -> count

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-haiku-4.5",
    max_tokens=512,
    temperature=0,
    messages=[{
        "role": "user",
        "content": "Analyze these commands: docker ps, docker kill tikv-1, curl localhost:9090"
    }],
    output_format={
        "type": "json",
        "schema": CommandAnalysis.model_json_schema()
    },
    extra_headers={
        "anthropic-beta": "structured-outputs-2025-11-13"
    }
)

# Guaranteed valid JSON matching schema
analysis = CommandAnalysis.model_validate_json(response.content[0].text)
```

### Idempotent Campaign Analysis
```python
# Source: Project design pattern
from dataclasses import dataclass

@dataclass
class CampaignSummary:
    campaign_id: int
    trial_count: int
    success_count: int
    win_rate: float
    avg_time_to_detect: float | None
    avg_time_to_resolve: float | None

async def analyze_campaign(db: EvalDB, campaign_id: int) -> CampaignSummary:
    """Compute campaign summary (idempotent, no database mutations)."""
    campaign = await db.get_campaign(campaign_id)
    trials = await db.get_trials(campaign_id)

    # Score each trial (pure computation)
    scores = [await score_trial(db, t.id) for t in trials]

    success_count = sum(1 for s in scores if s.resolved)
    win_rate = success_count / len(scores) if scores else 0.0

    # Average only successful trials
    detect_times = [s.time_to_detect_sec for s in scores if s.time_to_detect_sec]
    resolve_times = [s.time_to_resolve_sec for s in scores if s.time_to_resolve_sec]

    return CampaignSummary(
        campaign_id=campaign_id,
        trial_count=len(trials),
        success_count=success_count,
        win_rate=win_rate,
        avg_time_to_detect=mean(detect_times) if detect_times else None,
        avg_time_to_resolve=mean(resolve_times) if resolve_times else None,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded command patterns | LLM classification with structured outputs | Nov 2025 | More accurate, maintainable, adapts to variations |
| Custom ISO8601 parsers | `datetime.fromisoformat()` | Python 3.7 (2018) | Stdlib handles timezones, no external deps |
| Temperature=1.0 default | Temperature=0 for deterministic tasks | Always available | Idempotent classification results |
| Manual JSON serialization | Pydantic model_dump_json() | Pydantic 2.0 (2023) | Type-safe, handles edge cases |

**Deprecated/outdated:**
- **python-dateutil for ISO8601:** Stdlib `fromisoformat()` is sufficient for our format (no complex recurrence rules)
- **Regex-based command detection:** Misses semantic variations, requires constant maintenance
- **Individual Claude API calls:** Batch API available (50% cost reduction for bulk classification)

## Open Questions

Things that couldn't be fully resolved:

1. **Health determination from final_state dict**
   - What we know: Trial stores `final_state` as JSON blob with subject state
   - What's unclear: How to generically determine "healthy" from state dict (subject-specific)
   - Recommendation: Add `subject.is_healthy(state: dict) -> bool` method to EvalSubject protocol in Phase 35 (breaking change) OR implement subject-specific health checks in analysis/scoring.py using pattern matching on subject_name

2. **Thrashing detection heuristic**
   - What we know: Context marks as "Claude's discretion" — need to detect repeated similar commands
   - What's unclear: Definition of "similar" (exact match? semantic similarity? time window?)
   - Recommendation: Start simple — exact command repeated 3+ times within 60s window. Can refine based on real trial data.

3. **Batch API cost/latency tradeoff**
   - What we know: Batch API reduces cost 50% but adds processing delay
   - What's unclear: Typical batch turnaround time, whether delay is acceptable for analysis use case
   - Recommendation: Start with synchronous API for simplicity (analysis is post-hoc, not real-time). Add batch API optimization in future if cost becomes issue.

4. **Statistical significance testing**
   - What we know: Context doesn't specify significance testing for comparisons
   - What's unclear: Should we compute p-values, confidence intervals for win rate differences?
   - Recommendation: Start with simple descriptive statistics (win rate, avg times, deltas). Add statistical tests if users request ("is this difference meaningful?")

## Sources

### Primary (HIGH confidence)
- Python datetime documentation - https://docs.python.org/3/library/datetime.html
- Claude Structured Outputs docs - https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Rich library GitHub - https://github.com/Textualize/rich
- Anthropic API pricing 2026 - https://www.nops.io/blog/anthropic-api-pricing/
- Pydantic v2 documentation (model serialization)

### Secondary (MEDIUM confidence)
- Anthropic Academy Claude API guide - https://www.anthropic.com/learn/build-with-claude
- Hands-On Guide to Anthropic Structured Outputs - https://towardsdatascience.com/hands-on-with-anthropics-new-structured-output-capabilities/
- Python tabulate library comparison - https://github.com/astanin/python-tabulate

### Tertiary (LOW confidence)
- Batch API workflow templates - https://n8n.io/workflows/3409-batch-process-prompts-with-anthropic-claude-api/
- Scikit-LLM text classification - https://towardsdatascience.com/scikit-llm-power-up-your-text-analysis-in-python-using-llm-models-within-scikit-learn-framework-e9f101ffb6d4/

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in project or stdlib, verified versions
- Architecture: HIGH - Patterns verified with official docs, aligned with context decisions
- Pitfalls: MEDIUM - Based on common datetime/LLM issues, not specific to this codebase

**Research date:** 2026-01-29
**Valid until:** ~60 days (stable domain - datetime API, Claude API features stable)

**Context decisions honored:**
- ✅ Primary metric: Resolution (ticket + healthy)
- ✅ LLM classification for commands (not pattern matching)
- ✅ Win rate for campaign comparison
- ✅ Plain text output (no colors)
- ✅ --json flag for machine-readable output
- ✅ Idempotent analysis (no database mutations)
