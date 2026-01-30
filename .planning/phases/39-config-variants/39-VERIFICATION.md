---
phase: 39-config-variants
verified: 2026-01-30T01:54:48Z
status: passed
score: 9/9 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 8/9
  gaps_closed:
    - "Trial runner uses variant config for agent execution"
  gaps_remaining: []
  regressions: []
---

# Phase 39: Config Variants Verification Report

**Phase Goal:** Developer can test different agent configurations and compare performance
**Verified:** 2026-01-30T01:54:48Z
**Status:** PASSED
**Re-verification:** Yes — after gap closure via plan 39-04

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Developer can load a variant YAML file and get validated config | ✓ VERIFIED | VariantConfig model exists, load_variant_config() works |
| 2 | Developer can list available variants via CLI | ✓ VERIFIED | list-variants command exists and displays variants |
| 3 | Default variant exists with current agent configuration | ✓ VERIFIED | eval/variants/default.yaml exists with claude-opus-4-20250514 |
| 4 | Campaign YAML can specify variant field | ✓ VERIFIED | CampaignConfig has variant field (default: "default") |
| 5 | Campaigns table stores variant_name | ✓ VERIFIED | Database schema has variant_name column, migration works |
| 6 | Trial runner uses variant config for agent | ✓ VERIFIED | Variant flows: harness → tickets table → agent loop |
| 7 | Campaign omitting variant uses 'default' | ✓ VERIFIED | Default value "default" in CampaignConfig and Campaign |
| 8 | Developer can run compare-variants CLI command | ✓ VERIFIED | compare-variants command exists with help text |
| 9 | Comparison shows aggregate metrics per variant | ✓ VERIFIED | VariantComparison model with aggregated metrics |

**Score:** 9/9 truths verified

**Gap Closure:** Truth #6 was PARTIAL in previous verification. Plan 39-04 closed the gap by implementing the complete data flow from harness through tickets table to agent execution.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `eval/src/eval/types.py` | VariantConfig Pydantic model | ✓ VERIFIED | Contains class VariantConfig with name, model, system_prompt, tools_config fields |
| `eval/src/eval/variants.py` | Variant loading/discovery functions | ✓ VERIFIED | Exports load_variant_config, load_all_variants, get_variant |
| `eval/variants/default.yaml` | Default variant with current config | ✓ VERIFIED | Contains name: default, model: claude-opus-4-20250514, system_prompt, tools_config |
| `eval/src/eval/cli.py` | list-variants command | ✓ VERIFIED | Function list_variants_cmd exists |
| `eval/src/eval/runner/campaign.py` | CampaignConfig with variant field | ✓ VERIFIED | variant field exists with default "default" |
| `eval/src/eval/runner/db.py` | Schema migration for variant_name | ✓ VERIFIED | migrate_schema() method exists, variant_name column in SCHEMA_SQL |
| `eval/src/eval/runner/harness.py` | Variant integration in trial runner | ✓ VERIFIED | Loads variant_config AND passes to run_trial() |
| `eval/src/eval/types.py` | Campaign with variant_name field | ✓ VERIFIED | variant_name field with default "default" |
| `eval/src/eval/analysis/comparison.py` | VariantMetrics and VariantComparison | ✓ VERIFIED | Both classes exist with expected fields |
| `eval/src/eval/analysis/comparison.py` | compare_variants function | ✓ VERIFIED | async def compare_variants exists |
| `eval/src/eval/cli.py` | compare-variants command | ✓ VERIFIED | compare_variants_cmd exists |
| **NEW:** `packages/operator-core/src/operator_core/db/schema.py` | Variant columns in tickets table | ✓ VERIFIED | variant_model, variant_system_prompt, variant_tools_config columns exist |
| **NEW:** `packages/operator-core/src/operator_core/monitor/types.py` | Ticket with variant fields | ✓ VERIFIED | Ticket dataclass has variant_model, variant_system_prompt, variant_tools_config fields |
| **NEW:** `packages/operator-core/src/operator_core/agent_lab/loop.py` | process_ticket uses variant config | ✓ VERIFIED | Reads ticket.variant_model and ticket.variant_system_prompt, uses in API call |
| **NEW:** `eval/src/eval/runner/harness.py` | update_ticket_variant function | ✓ VERIFIED | Function exists, writes variant config to tickets table via SQL UPDATE |

**Artifact Status:** 15/15 verified (4 new artifacts added in gap closure)

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| eval/src/eval/variants.py | eval/src/eval/types.py | imports VariantConfig | ✓ WIRED | from eval.types import VariantConfig |
| eval/src/eval/cli.py | eval/src/eval/variants.py | imports load_all_variants | ✓ WIRED | from eval.variants import load_all_variants |
| eval/src/eval/runner/harness.py | eval/src/eval/variants.py | imports get_variant | ✓ WIRED | from eval.variants import get_variant |
| eval/src/eval/runner/db.py | eval/src/eval/types.py | Campaign with variant_name | ✓ WIRED | variant_name read/written correctly |
| eval/src/eval/cli.py | eval/src/eval/analysis/comparison.py | imports compare_variants | ✓ WIRED | from eval.analysis import compare_variants |
| **FIXED:** eval/src/eval/runner/harness.py | run_trial() | passes variant_config | ✓ WIRED | variant_config passed to run_trial() at line 380 |
| **NEW:** eval/src/eval/runner/harness.py | operator.db tickets table | writes variant via SQL UPDATE | ✓ WIRED | update_ticket_variant() at line 73-94 |
| **NEW:** operator-core agent_lab/loop.py | tickets table | reads variant from ticket | ✓ WIRED | ticket.variant_model, ticket.variant_system_prompt at lines 46, 49 |
| **NEW:** operator-core agent_lab/loop.py | Claude API | uses variant model/prompt | ✓ WIRED | effective_model and effective_system_prompt passed to client.beta.messages.tool_runner at lines 56, 59 |

**Key Link Status:** 9/9 wired (3 new links added, 1 fixed)

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| CONF-01: Config variants define model, system_prompt, tools_config | ✓ SATISFIED | None |
| CONF-02: Campaigns can specify which variant to use | ✓ SATISFIED | None |
| CONF-03: Analysis compares performance across variants | ✓ SATISFIED | None |

**Requirements Status:** 3/3 satisfied

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None detected | - | - | - | - |

**Anti-Pattern Status:** Clean - no TODO/FIXME/placeholders in any modified files

### Gap Closure Verification

**Previous Gap:** Variant infrastructure complete but variant config not passed to agent during trial execution

**Resolution:** Plan 39-04 implemented complete data flow:

1. **Schema changes:** Added variant_model, variant_system_prompt, variant_tools_config columns to tickets table
2. **Harness integration:** run_trial() accepts variant_config parameter, update_ticket_variant() writes to database
3. **Agent integration:** process_ticket() reads variant fields from ticket record, uses for API call
4. **Data flow verification:**
   - Campaign YAML → CampaignConfig.variant field
   - Harness loads variant via get_variant(config.variant)
   - Harness passes variant_config to run_trial()
   - run_trial() writes variant to tickets table via SQL UPDATE
   - Agent polls tickets table, reads variant fields
   - Agent uses ticket.variant_model and ticket.variant_system_prompt in Claude API call

**Integration test passed:** Created temp database, inserted ticket with variant config, verified TicketOpsDB reads variant fields correctly.

**Backward compatibility:** Graceful fallback pattern ensures existing code works:
- `ticket.variant_model or "claude-opus-4-20250514"` — defaults to current model if variant not set
- `ticket.variant_system_prompt or SYSTEM_PROMPT` — defaults to current prompt if variant not set

### End-to-End Data Flow

```
Campaign YAML (variant: "sonnet-test")
    ↓
CampaignConfig.variant = "sonnet-test"
    ↓
get_variant("sonnet-test") → VariantConfig
    ↓
run_trial(variant_config=VariantConfig(...))
    ↓
update_ticket_variant() → SQL UPDATE tickets SET variant_model=?, variant_system_prompt=?
    ↓
operator.db tickets table (variant_model, variant_system_prompt columns)
    ↓
TicketOpsDB.poll_for_open_ticket() → Ticket with variant fields
    ↓
process_ticket(ticket) → effective_model = ticket.variant_model or default
    ↓
client.beta.messages.tool_runner(model=effective_model, system=effective_system_prompt)
    ↓
Agent executes with variant configuration
```

**Result:** Developer can now test different agent configurations automatically. No manual code changes required between test runs.

### Success Criteria Assessment

From ROADMAP.md Phase 39 success criteria:

| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. Config variants define model, system_prompt, tools_config | ✓ MET | VariantConfig has all three fields, YAML files work |
| 2. Campaign config can specify variant | ✓ MET | CampaignConfig.variant field, defaults to "default" |
| 3. Analysis compares performance across variants | ✓ MET | compare_variants() function, VariantComparison model |
| 4. Developer can see which configuration performs best | ✓ MET | compare-variants CLI command shows metrics per variant |

**All success criteria met.**

### Re-Verification Summary

**Previous verification (2026-01-29T18:45:00Z):**
- Status: gaps_found
- Score: 8/9 truths verified (1 partial)
- Issue: Variant config loaded but not applied during agent execution

**Current verification (2026-01-30T01:54:48Z):**
- Status: **PASSED**
- Score: 9/9 truths verified
- Gap closed: Variant config now flows from harness through tickets table to agent
- No regressions: All previously passing items still work

**Phase 39 COMPLETE.** All 4 plans delivered. A/B testing infrastructure fully operational.

---

_Verified: 2026-01-30T01:54:48Z_
_Verifier: Claude (gsd-verifier)_
_Re-verification: Yes — gap closure via plan 39-04_
