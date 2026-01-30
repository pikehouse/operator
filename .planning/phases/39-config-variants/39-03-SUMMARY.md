---
phase: 39
plan: 03
subsystem: eval-harness
tags: [variants, comparison, analysis, cli, balanced-scorecard]
requires: [39-02]
provides:
  - compare_variants function for A/B testing variants
  - VariantComparison and VariantMetrics models
  - compare-variants CLI command with Rich table output
affects: []
tech-stack:
  added: []
  patterns:
    - Balanced scorecard comparison pattern (no winner determination)
    - Aggregate metrics across multiple campaigns per variant
    - Rich Table formatting for variant comparison output
decisions:
  - Balanced scorecard approach shows all metrics equally
  - No automated winner determination - user interprets tradeoffs
  - Sort variants by name for consistent output
  - Filter non-baseline campaigns only for variant comparison
key-files:
  created: []
  modified:
    - eval/src/eval/analysis/comparison.py: Added VariantMetrics, VariantComparison, compare_variants
    - eval/src/eval/analysis/__init__.py: Exported variant comparison types and function
    - eval/src/eval/cli.py: Added compare-variants CLI command
duration: 165s
completed: 2026-01-30
---

# Phase 39 Plan 03: Variant Comparison Analysis Summary

**Developer can compare agent performance across variants with balanced scorecard showing aggregate metrics.**

## Performance

- **Duration:** 2m 45s
- **Started:** 2026-01-30T01:02:23Z
- **Completed:** 2026-01-30T01:05:08Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- VariantMetrics model aggregates trial_count, success_count, win_rate, avg_time_to_detect_sec, avg_time_to_resolve_sec, avg_commands per variant
- VariantComparison model provides balanced scorecard for multiple variants
- compare_variants function queries by subject/chaos, groups by variant, aggregates CampaignSummary metrics
- compare-variants CLI command displays Rich table with all metrics equally weighted
- No winner determination - balanced scorecard approach lets user interpret tradeoffs

## Task Commits

Each task was committed atomically:

1. **Task 1: Add VariantMetrics and VariantComparison models** - `fbfce52` (feat)
2. **Task 2: Implement compare_variants function** - `fcdd1f0` (feat)
3. **Task 3: Add compare-variants CLI command** - `8f6bd4d` (feat)

## Files Created/Modified

- `eval/src/eval/analysis/comparison.py` - Added VariantMetrics and VariantComparison Pydantic models, compare_variants async function with schema compatibility check
- `eval/src/eval/analysis/__init__.py` - Exported VariantMetrics, VariantComparison, compare_variants
- `eval/src/eval/cli.py` - Added compare-variants command with subject/chaos/variants arguments, Rich table output, JSON support

## Decisions Made

### Technical Decisions

1. **Balanced scorecard approach**
   - Rationale: User requirement specified no winner determination, show all metrics equally
   - Impact: Developers interpret tradeoffs based on their priorities (speed vs reliability, commands vs time)
   - Aligns with CONF-03 requirement for A/B comparison without automated ranking

2. **Filter non-baseline campaigns**
   - Rationale: Baseline campaigns test self-healing, not agent variants
   - Impact: Comparison focuses on agent performance differences only
   - Query: `WHERE subject_name = ? AND chaos_type = ? AND baseline = 0`

3. **Sort variants by name**
   - Rationale: Consistent output order for reproducible comparisons
   - Impact: Same variant always appears in same table position
   - Pattern: `for variant_name in sorted(result.variants.keys())`

4. **Aggregate across campaigns**
   - Rationale: Single variant may have multiple campaigns (re-runs, different dates)
   - Impact: Total trials across all campaigns, weighted average for metrics
   - Pattern: Sum trial_count and success_count, average time metrics

### User Experience Decisions

1. **Rich Table formatting**
   - Rationale: Existing codebase uses Rich for tables, better than plain text
   - Impact: Color-coded columns, clean alignment, professional output
   - Columns: Variant, Trials, Success Rate, Avg TTD, Avg TTR, Avg Commands

2. **Abbreviations explained**
   - Rationale: TTD and TTR are concise but not immediately obvious
   - Impact: Footer text explains: "TTD = Time to Detect, TTR = Time to Resolve"
   - Enhancement: User-friendly without verbose column headers

3. **Optional variant filtering**
   - Rationale: Large databases may have many variants, filter to specific comparison
   - Impact: `--variants haiku-v1,sonnet-v1` compares only specified variants
   - Default: All variants for the subject/chaos combination

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all verification checks passed on first attempt.

## Next Phase Readiness

**Blockers:** None

**Phase 39 Complete:** All 3 plans finished (variant schema, campaign integration, comparison analysis)

**v3.2 Milestone Complete:** Phase 39 was the final phase for v3.2 Evaluation Harness

**Integration Points:**
- compare-variants command ready for developer use
- Variant comparison data available via JSON output for external analysis
- Balanced scorecard approach validated with all expected columns

**Open Questions:**
- Should we add statistical significance testing for variant comparisons? (not in scope for v3.2)
- Should we support multi-chaos variant comparison (aggregate across all chaos types)? (future enhancement)
- Should we add visualization (charts) for variant comparison trends? (future enhancement)

## Knowledge for Future Phases

1. **Balanced scorecard pattern:**
   - No winner determination keeps analysis objective
   - Display all metrics with equal weight
   - User interprets based on their priorities (reliability, speed, efficiency)
   - Pattern applicable to other comparison contexts

2. **Aggregate metrics calculation:**
   - Sum trial_count and success_count across campaigns
   - Calculate win_rate from aggregated totals (not average of averages)
   - Use _safe_avg helper for time metrics (handles None values)
   - Pattern: filter None, then average remaining values

3. **Rich Table column styling:**
   - `header_style="dim"` de-emphasizes secondary metrics (TTD, TTR)
   - `justify="right"` for numeric columns improves readability
   - `style="cyan"` highlights primary identifier (variant name)
   - Sort data before adding rows for consistent output

4. **Schema compatibility checks:**
   - PRAGMA table_info checks column existence before querying
   - Raises clear ValueError if schema migration needed
   - Pattern: backward compatible with pre-variant databases
   - Future: could auto-run migration instead of raising error

5. **CLI argument parsing:**
   - Comma-separated string → list[str] via split(",") and strip()
   - Optional filtering via `variant_names: list[str] | None = None`
   - Pass None to compare_variants for "all variants" behavior
   - Pattern: flexible filtering without complex CLI syntax

---

**Phase:** 39-config-variants
**Plan:** 03
**Status:** ✅ COMPLETE
**Completed:** 2026-01-30
