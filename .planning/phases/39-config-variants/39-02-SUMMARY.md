---
phase: 39
plan: 02
subsystem: eval-harness
tags: [campaign, variants, database, migration, yaml]
requires: [39-01]
provides:
  - Campaign YAML with variant field
  - Database schema with variant_name column and migration
  - Variant integration in trial runner and CLI
affects: [39-03]
tech-stack:
  added: []
  patterns:
    - Database schema migration pattern with PRAGMA checks
    - Variant field propagation through matrix expansion
    - CLI table formatting with variant display
decisions:
  - Use migrate_schema() pattern for backward compatible schema changes
  - Variant defaults to "default" when omitted from YAML
  - Display variant during campaign startup for visibility
key-files:
  created: []
  modified:
    - eval/src/eval/types.py: Added variant_name field to Campaign
    - eval/src/eval/runner/campaign.py: Added variant field to CampaignConfig
    - eval/src/eval/runner/db.py: Schema migration for variant_name column
    - eval/src/eval/runner/harness.py: Variant loading and Campaign integration
    - eval/src/eval/cli.py: Variant display in list and run commands
duration: 189s
completed: 2026-01-30
---

# Phase 39 Plan 02: Config Variants Integration Summary

**Campaign YAML accepts variant field, database stores variant_name with backward-compatible migration, harness loads variant config for trial execution.**

## Performance

- **Duration:** 3m 9s
- **Started:** 2026-01-30T03:02:45Z
- **Completed:** 2026-01-30T03:05:54Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Campaign and CampaignConfig have variant fields with "default" fallback
- Database schema migration adds variant_name column idempotently
- Harness loads and displays variant configuration during campaign startup
- CLI shows variant in campaign list and run summary

## Task Commits

Each task was committed atomically:

1. **Task 1: Add variant field to Campaign and CampaignConfig** - `61b4cfe` (feat)
2. **Task 2: Add variant_name column to database schema** - `b682947` (feat)
3. **Task 3: Integrate variant into harness and CLI** - `7fb091c` (feat)

## Files Created/Modified

- `eval/src/eval/types.py` - Added variant_name field to Campaign dataclass (default: "default")
- `eval/src/eval/runner/campaign.py` - Added variant field to CampaignConfig, pass through matrix expansion
- `eval/src/eval/runner/db.py` - Added variant_name column with migration, updated CRUD operations
- `eval/src/eval/runner/harness.py` - Import and load variant config, store in Campaign record
- `eval/src/eval/cli.py` - Display variant in campaign summary and list output

## Decisions Made

### Technical Decisions

1. **Schema migration pattern**
   - Rationale: Use PRAGMA table_info to check column existence before ALTER TABLE
   - Impact: Idempotent migrations safe to run multiple times
   - Pattern: Can be extended for future schema changes

2. **Variant defaults to "default"**
   - Rationale: Backward compatibility with existing campaigns and YAMLs
   - Impact: Campaigns omitting variant field use default variant automatically
   - Aligns with 39-01 design (default.yaml as working example)

3. **Variant loading in harness**
   - Rationale: Load variant early to fail fast if variant not found
   - Impact: Clear error messages before trial execution starts
   - Display variant name/model for visibility during campaign runs

4. **Defensive variant_name reads**
   - Rationale: Use getattr() fallback for compatibility with old databases
   - Impact: Works with databases created before variant_name column added
   - Pattern: Safe migration path for existing users

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all verification checks passed on first attempt.

## Next Phase Readiness

**Blockers:** None

**For 39-03 (Variant Comparison Analysis):**
- Database stores variant_name for filtering trials by variant
- Campaign records include variant for comparison queries
- CLI infrastructure ready for variant comparison commands

**Integration Points:**
- Analysis queries can filter by variant_name using idx_campaigns_variant index
- Comparison logic can group campaigns by variant for A/B testing metrics
- Variant config loaded during campaign execution (ready for agent loop integration)

**Open Questions:**
- How to pass variant config to agent loop? (env vars, function params, or config file)
- Should variant comparison be a new CLI command or extend existing compare?
- What metrics are most valuable for variant A/B testing? (win rate, TTR, TTD, command count)

## Knowledge for Future Phases

1. **Database migration pattern:**
   - migrate_schema() called automatically by ensure_schema()
   - PRAGMA table_info() checks column existence before ALTER TABLE
   - Pattern is idempotent and backward compatible

2. **Variant propagation:**
   - CampaignConfig.variant → trial specs → Campaign.variant_name
   - Matrix expansion includes variant in each trial spec dict
   - Variant config loaded once per campaign, not per trial

3. **CLI variant display:**
   - Plain text table uses fixed-width columns (truncate at 10 chars)
   - JSON output includes full variant_name via getattr() fallback
   - Header width adjusted from 58 to 70 chars to accommodate variant column

4. **Backward compatibility:**
   - Old databases without variant_name column work via migration
   - Old Campaign objects without variant_name use getattr() fallback
   - Default variant ensures campaigns without explicit variant still work

---

**Phase:** 39-config-variants
**Plan:** 02
**Status:** ✅ COMPLETE
**Completed:** 2026-01-30
