# Phase 36: Analysis Layer - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Compute scores and compare performance across trials/campaigns. Developer can analyze a campaign, compare agent to baseline, and compare two campaigns. Analysis is post-hoc (runs on stored trial data). Web UI and advanced visualization belong in Phase 37.

</domain>

<decisions>
## Implementation Decisions

### Scoring metrics
- Primary metric: **Resolution** — did the agent resolve it?
- Resolution requires BOTH: ticket marked resolved in operator.db AND cluster healthy (subject.wait_healthy() true)
- Track **detection time** as secondary metric (chaos injection → ticket created)
- Trial outcomes in three categories: **success**, **failure**, **timeout** (distinct, not binary)

### Command analysis
- Track: total command count, unique commands, destructive commands
- Use **LLM classification** to categorize commands (diagnostic, remediation, destructive, etc.)
- No hardcoded pattern matching — Claude analyzes each command and classifies it
- Comparison output focuses on timing/resolution only — command analysis is available but not in default comparison

### Comparison output
- Agent vs baseline: **full breakdown** — all metrics side-by-side with delta
- Campaign vs campaign: primary metric is **win rate** (which resolved more?)
- Tiebreaker: **faster wins** (lower average resolution time breaks equal win rates)

### CLI output format
- Default: **plain text** (no colors, easy to pipe/grep)
- Add `--json` flag for programmatic/machine-readable output
- No color highlighting — keep output simple
- Verbosity: **moderate by default** — summary + key metrics breakdown (no -v flag needed)

### Claude's Discretion
- Thrashing detection heuristic (what counts as repeated similar commands)
- Exact command classification categories
- How to display deltas in comparison output
- Statistical significance thresholds (if any)

</decisions>

<specifics>
## Specific Ideas

- "The LLM should decide" for command classification — don't try to enumerate patterns
- Win rate is the intuitive metric for campaign comparison
- Analysis should be idempotent — can re-run on old campaigns

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 36-analysis-layer*
*Context gathered: 2026-01-29*
