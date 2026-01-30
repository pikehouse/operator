# Phase 39: Config Variants - Research

**Researched:** 2026-01-29
**Domain:** Configuration management, A/B testing, YAML validation
**Confidence:** HIGH

## Summary

This phase adds agent configuration variants to enable A/B testing different models, system prompts, and tool configurations across chaos scenarios. The implementation follows established Python patterns: Pydantic models for YAML validation, SQLite schema migration for variant tracking, and CLI commands for variant comparison.

The current codebase already has strong foundations: Pydantic-based campaign YAML loading, Rich library for table output, and comparison infrastructure for campaigns. The variant system extends these patterns by storing variant configs as YAML files in `eval/variants/`, adding a `variant` field to campaign YAML, and creating a comparison command that aggregates metrics across all trials for each variant.

**Primary recommendation:** Use Pydantic BaseModel for variant validation, store one YAML file per variant in `eval/variants/`, add `variant_name` column to campaigns table with migration support, and create `compare-variants` CLI command using existing Rich Table formatting.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pydantic | 2.x | YAML validation & schema definition | Industry standard for Python config validation, already used in codebase for CampaignConfig |
| PyYAML | 6.x | YAML parsing | Python standard library companion, safe_load prevents security vulnerabilities |
| SQLite3 | 3.x (built-in) | Database for variant tracking | Already used for campaigns/trials, zero additional dependencies |
| Rich | 13.x+ | Table formatting for comparisons | Already used in codebase, superior terminal rendering vs tabulate |
| Typer | 0.x | CLI framework | Already used for eval CLI, provides clean argument parsing |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib | built-in | File path handling | Always - safer than os.path for YAML file discovery |
| glob | built-in | Pattern matching for YAML files | Loading all variants from directory |
| aiosqlite | current | Async SQLite operations | Already used in EvalDB, maintain consistency |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic | dataclasses + manual validation | Pydantic provides better error messages, automatic coercion |
| Rich | tabulate | Rich already in codebase, better formatting capabilities |
| SQLite column | JSON config in existing field | Column migration simpler, enables SQL filtering by variant |

**Installation:**
No new dependencies required - all libraries already in use.

## Architecture Patterns

### Recommended Project Structure
```
eval/
├── variants/               # Variant YAML files
│   ├── default.yaml       # Current agent config
│   ├── haiku-minimal.yaml # Example variant
│   └── opus-verbose.yaml  # Example variant
└── src/eval/
    ├── types.py           # Add VariantConfig model
    ├── runner/
    │   ├── campaign.py    # Add variant field to CampaignConfig
    │   ├── db.py          # Add schema migration for variant_name column
    │   └── harness.py     # Apply variant config when running trials
    ├── analysis/
    │   ├── comparison.py  # Add compare_variants function
    │   └── commands.py    # No changes needed
    └── cli.py             # Add list-variants, compare-variants commands
```

### Pattern 1: Pydantic Variant Model
**What:** Define variant schema with validation
**When to use:** Loading and validating variant YAML files
**Example:**
```python
# Source: Codebase analysis + Pydantic docs
# eval/src/eval/types.py

from pydantic import BaseModel, Field, field_validator

class VariantConfig(BaseModel):
    """Agent configuration variant schema."""
    name: str = Field(..., min_length=1, description="Human-readable variant name")
    model: str = Field(..., description="Anthropic model ID (e.g., claude-opus-4-20250514)")
    system_prompt: str = Field(..., min_length=1, description="System prompt text (inline)")
    tools_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool configuration (tool_choice, specific tools to enable)"
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        valid_models = [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-5-20241022"
        ]
        if v not in valid_models:
            raise ValueError(f"Invalid model: {v}. Must be one of {valid_models}")
        return v

def load_variant_config(path: Path) -> VariantConfig:
    """Load and validate variant from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return VariantConfig.model_validate(data)
```

### Pattern 2: Schema Migration with IF NOT EXISTS
**What:** Add variant_name column to campaigns table safely
**When to use:** Database schema evolution without breaking existing installations
**Example:**
```python
# Source: SQLite ALTER TABLE best practices
# eval/src/eval/runner/db.py

SCHEMA_SQL = """
-- Campaign table
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_name TEXT NOT NULL,
    chaos_type TEXT NOT NULL,
    trial_count INTEGER NOT NULL,
    baseline INTEGER NOT NULL DEFAULT 0,
    variant_name TEXT DEFAULT 'default',  -- Add with default for existing rows
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_campaigns_variant ON campaigns(variant_name);
"""

async def migrate_add_variant_column(self) -> None:
    """Add variant_name column if not exists (migration for Phase 39)."""
    async with aiosqlite.connect(self.db_path) as db:
        # Check if column exists
        cursor = await db.execute("PRAGMA table_info(campaigns)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if "variant_name" not in column_names:
            await db.execute(
                "ALTER TABLE campaigns ADD COLUMN variant_name TEXT DEFAULT 'default'"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_campaigns_variant ON campaigns(variant_name)"
            )
            await db.commit()
```

### Pattern 3: Variant Discovery with Glob
**What:** Load all variant files from directory
**When to use:** CLI commands that list or load all available variants
**Example:**
```python
# Source: Python glob best practices
# eval/src/eval/cli.py

from pathlib import Path
import glob

def load_all_variants(variants_dir: Path = Path("eval/variants")) -> dict[str, VariantConfig]:
    """Load all variant configs from directory.

    Returns:
        Dict mapping variant name to VariantConfig
    """
    variants = {}

    for yaml_file in variants_dir.glob("*.yaml"):
        try:
            variant = load_variant_config(yaml_file)
            variants[variant.name] = variant
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load {yaml_file}: {e}[/yellow]")

    return variants
```

### Pattern 4: Rich Table for Comparison Output
**What:** Balanced scorecard table showing all metrics
**When to use:** CLI output for variant comparison
**Example:**
```python
# Source: Existing codebase patterns + Rich documentation
# eval/src/eval/cli.py

from rich.table import Table
from rich.console import Console

def display_variant_comparison(comparison: VariantComparison) -> None:
    """Display variant comparison as Rich table."""
    console = Console()

    table = Table(title=f"Variant Comparison: {comparison.subject_name}/{comparison.chaos_type}")

    table.add_column("Variant", style="cyan")
    table.add_column("Trials", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Avg TTD", justify="right")
    table.add_column("Avg TTR", justify="right")
    table.add_column("Commands", justify="right")

    for variant_name, metrics in comparison.variants.items():
        table.add_row(
            variant_name,
            str(metrics.trial_count),
            f"{metrics.win_rate:.1%}",
            f"{metrics.avg_time_to_detect:.1f}s" if metrics.avg_time_to_detect else "N/A",
            f"{metrics.avg_time_to_resolve:.1f}s" if metrics.avg_time_to_resolve else "N/A",
            str(metrics.avg_commands),
        )

    console.print(table)
```

### Anti-Patterns to Avoid
- **Complex variant inheritance:** Don't support variant inheritance/merging - keep each variant fully self-contained
- **Variant validation at runtime:** Validate variant YAML at campaign start, not during trials
- **Per-chaos-type comparisons:** User wanted aggregate only - don't break down by chaos type
- **Auto-ranking variants:** No "best" determination - show balanced scorecard, user decides

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML validation | Manual dict checking | Pydantic BaseModel | Automatic type coercion, clear error messages, already in codebase |
| Table formatting | String concatenation | Rich Table | Handles column alignment, colors, borders automatically |
| SQLite migrations | Direct ALTER TABLE | Check column exists first | Prevents errors on re-run, idempotent migrations |
| File path handling | String manipulation | pathlib.Path | Handles OS differences, safer operations |
| Async database ops | Sync sqlite3 | aiosqlite | Already used in codebase, prevents blocking |

**Key insight:** The codebase already has strong patterns for each component. Extend existing patterns rather than introducing new libraries or approaches.

## Common Pitfalls

### Pitfall 1: SQLite ALTER TABLE Restrictions
**What goes wrong:** SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN, causing errors on migration re-runs
**Why it happens:** Unlike CREATE TABLE IF NOT EXISTS, ALTER TABLE requires manual existence checking
**How to avoid:** Query PRAGMA table_info() first, only add column if not present
**Warning signs:** "duplicate column name" error when running migrations multiple times

### Pitfall 2: tools_config Structure Undefined
**What goes wrong:** The Anthropic API doesn't have a parameter called `tools_config` - this is a custom abstraction
**Why it happens:** User requirement CONF-01 specified tools_config without defining structure
**How to avoid:** Define tools_config as dict with keys: tool_choice (str), enabled_tools (list[str])
**Warning signs:** Confusion about what fields tools_config should contain

### Pitfall 3: Variant Name Mismatches
**What goes wrong:** Campaign references variant "haiku-v1" but file is named "haiku_v1.yaml"
**Why it happens:** Variant name in YAML doesn't match filename or campaign reference
**How to avoid:** Enforce that variant.name field matches filename (minus .yaml extension)
**Warning signs:** FileNotFoundError or variant not found errors

### Pitfall 4: Default Variant Missing
**What goes wrong:** Campaigns with no variant field fail because "default" variant doesn't exist
**Why it happens:** Campaign YAML allows omitting variant field, expects default.yaml to exist
**How to avoid:** Ensure default.yaml exists with current agent configuration, validate in CLI
**Warning signs:** "default variant not found" when running old campaigns

### Pitfall 5: Comparing Campaigns with Different Chaos Types
**What goes wrong:** User compares variants across campaigns with different chaos_types, getting meaningless results
**Why it happens:** Variant comparison doesn't validate that campaigns share same subject/chaos_type
**How to avoid:** Filter campaigns by subject_name and chaos_type before aggregating, or warn user
**Warning signs:** Comparison shows wildly different metrics because chaos types differ

### Pitfall 6: Inline String Prompt Escaping
**What goes wrong:** Multi-line system prompts in YAML have indentation/escaping issues
**Why it happens:** YAML string handling requires proper | or > block scalar syntax
**How to avoid:** Use | for literal block scalars to preserve newlines and indentation
**Warning signs:** System prompt has extra indentation or missing newlines

## Code Examples

Verified patterns from official sources:

### YAML Block Scalar for System Prompt
```yaml
# Source: YAML specification + Python YAML best practices
# eval/variants/default.yaml
name: default
model: claude-opus-4-20250514
system_prompt: |
  You are an SRE operator responsible for diagnosing and fixing infrastructure issues.

  You will receive a ticket describing an issue. Your job is to investigate and resolve it.

  You have shell access to the host machine. Services run in Docker containers.

  Note: The ticket message includes the container hostname (e.g., "at tikv0:20160").

  Trust your judgment. When you've resolved the issue or determined you cannot fix it,
  clearly state your conclusion and what was done.
tools_config:
  tool_choice: auto
  enabled_tools:
    - shell
```

### Loading Variant in Campaign Runner
```python
# Source: Codebase analysis
# eval/src/eval/runner/harness.py

async def run_trial_with_variant(
    variant: VariantConfig,
    subject: EvalSubject,
    chaos_type: str,
    campaign_id: int,
    baseline: bool = False,
    operator_db_path: Path | None = None,
) -> Trial:
    """Run trial with specific variant configuration.

    Applies variant's model, system_prompt, and tools_config to agent.
    """
    # Apply variant config to agent client
    # Note: This requires modifying process_ticket in agent_lab/loop.py
    # to accept variant parameters instead of hardcoded values

    return await run_trial(
        subject=subject,
        chaos_type=chaos_type,
        campaign_id=campaign_id,
        baseline=baseline,
        operator_db_path=operator_db_path,
        # Pass variant config to be applied in agent loop
        agent_config={
            "model": variant.model,
            "system_prompt": variant.system_prompt,
            "tool_choice": variant.tools_config.get("tool_choice", "auto"),
        }
    )
```

### Variant Comparison Query
```python
# Source: Existing comparison patterns in codebase
# eval/src/eval/analysis/comparison.py

async def compare_variants(
    db: EvalDB,
    subject_name: str,
    chaos_type: str,
    variant_names: list[str] | None = None,
) -> VariantComparison:
    """Compare performance across variants for same subject/chaos combination.

    Args:
        db: EvalDB instance
        subject_name: Filter by subject (e.g., "tikv")
        chaos_type: Filter by chaos type (e.g., "node_kill")
        variant_names: Optional list of variant names to include

    Returns:
        VariantComparison with aggregate metrics per variant
    """
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row

        # Get all campaigns matching criteria
        query = """
            SELECT id, variant_name
            FROM campaigns
            WHERE subject_name = ? AND chaos_type = ? AND baseline = 0
        """
        params = [subject_name, chaos_type]

        if variant_names:
            placeholders = ",".join("?" * len(variant_names))
            query += f" AND variant_name IN ({placeholders})"
            params.extend(variant_names)

        cursor = await conn.execute(query, params)
        campaigns = await cursor.fetchall()

    # Group by variant, aggregate metrics
    variant_metrics: dict[str, list[CampaignSummary]] = {}
    for campaign in campaigns:
        summary = await analyze_campaign(db, campaign["id"])
        variant_name = campaign["variant_name"]
        if variant_name not in variant_metrics:
            variant_metrics[variant_name] = []
        variant_metrics[variant_name].append(summary)

    # Aggregate across campaigns for each variant
    results = {}
    for variant_name, summaries in variant_metrics.items():
        results[variant_name] = VariantMetrics(
            trial_count=sum(s.trial_count for s in summaries),
            win_rate=sum(s.win_rate * s.trial_count for s in summaries) / sum(s.trial_count for s in summaries),
            avg_time_to_detect=_average([s.avg_time_to_detect_sec for s in summaries if s.avg_time_to_detect_sec]),
            avg_time_to_resolve=_average([s.avg_time_to_resolve_sec for s in summaries if s.avg_time_to_resolve_sec]),
            avg_commands=_average([s.total_commands / s.trial_count for s in summaries]),
        )

    return VariantComparison(
        subject_name=subject_name,
        chaos_type=chaos_type,
        variants=results,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded model in loop.py | Variant-based config | Phase 39 | Enables A/B testing different models |
| No system prompt variants | Inline prompt in YAML | Phase 39 | Test prompt engineering impact |
| Fixed tool configuration | tools_config dict | Phase 39 | Experiment with tool_choice settings |
| Manual config changes | YAML variant files | 2024+ standard | Declarative, version-controlled configs |

**Deprecated/outdated:**
- Direct config modification in code: Use YAML variants instead
- tools_config as undefined concept: Define as dict with tool_choice and enabled_tools

## Open Questions

Things that couldn't be fully resolved:

1. **tools_config structure**
   - What we know: Anthropic API supports `tools` (array) and `tool_choice` (string/object) parameters
   - What's unclear: User requirement says "tools_config" but doesn't define fields
   - Recommendation: Define as `{"tool_choice": "auto|any|tool|none", "enabled_tools": ["shell"]}` based on Anthropic API

2. **Agent loop integration**
   - What we know: Current agent loop has hardcoded model and system_prompt in loop.py
   - What's unclear: Best way to pass variant config to agent loop (env vars, function params, global config)
   - Recommendation: Modify run_agent_loop to accept optional variant_config parameter, default to current values

3. **Variant validation timing**
   - What we know: Pydantic validates on load, but agent might fail with invalid model later
   - What's unclear: Should we test agent startup with variant before running campaign
   - Recommendation: Add optional `--validate` flag to campaign run that does dry-run with variant

## Sources

### Primary (HIGH confidence)
- Existing codebase analysis - eval/src/eval/runner/campaign.py shows Pydantic CampaignConfig pattern
- Existing codebase analysis - eval/src/eval/runner/db.py shows SQLite schema and aiosqlite usage
- Existing codebase analysis - eval/src/eval/cli.py shows Rich table formatting and Typer CLI patterns
- [Anthropic Claude API tool_choice parameter](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use) - Official documentation on tool_choice options
- [SQLite ALTER TABLE documentation](https://sqlite.org/lang_altertable.html) - Official SQLite docs on column addition

### Secondary (MEDIUM confidence)
- [Pydantic YAML validation best practices](https://betterprogramming.pub/validating-yaml-configs-made-easy-with-pydantic-594522612db5) - Community guide on Pydantic + YAML
- [Python YAML configuration with Pydantic](https://medium.com/@jonathan_b/a-simple-guide-to-configure-your-python-project-with-pydantic-and-a-yaml-file-bef76888f366) - Medium article on config patterns
- [Rich Table documentation](https://rich.readthedocs.io/en/latest/tables.html) - Official Rich library docs
- [Python glob for YAML files](https://docs.python.org/3/library/glob.html) - Python stdlib docs on file pattern matching
- [SQLite migration best practices](https://www.sqlitetutorial.net/sqlite-alter-table/) - SQLite tutorial on ALTER TABLE

### Tertiary (LOW confidence)
- [A/B testing frameworks Python](https://www.kdnuggets.com/a-complete-guide-to-a-b-testing-in-python) - General A/B testing concepts, not specific to this use case
- [Python tabulate vs Rich](https://pypi.org/project/tabulate/) - Comparison marked LOW since codebase already uses Rich

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in codebase, no new dependencies
- Architecture: HIGH - Extends existing Pydantic/SQLite/Rich patterns
- Pitfalls: MEDIUM - tools_config structure needs clarification with user, agent loop integration has options

**Research date:** 2026-01-29
**Valid until:** 60 days (stable domain - config management patterns don't change rapidly)
