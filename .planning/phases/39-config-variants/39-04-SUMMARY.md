---
phase: 39-config-variants
plan: 04
subsystem: eval-harness
tags: [variant-config, eval, trials, database, agent-loop, a-b-testing]

# Dependency graph
requires:
  - phase: 39-config-variants/39-02
    provides: Database schema migration for variant_name column
  - phase: 39-config-variants/39-01
    provides: VariantConfig type and YAML loading
provides:
  - Variant config flows from harness through tickets table to agent
  - Agent reads variant_model and variant_system_prompt from ticket record
  - Harness writes variant config via SQL UPDATE after ticket creation
  - Complete A/B testing infrastructure for agent configurations
affects: [future-eval-campaigns, agent-optimization, performance-testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cross-process config via database: variant config stored in tickets table, read by agent polling loop"
    - "Variant override pattern: ticket.variant_model || default, ticket.variant_system_prompt || SYSTEM_PROMPT"

key-files:
  created: []
  modified:
    - packages/operator-core/src/operator_core/db/schema.py
    - packages/operator-core/src/operator_core/monitor/types.py
    - packages/operator-core/src/operator_core/db/tickets.py
    - packages/operator-core/src/operator_core/agent_lab/ticket_ops.py
    - packages/operator-core/src/operator_core/agent_lab/loop.py
    - eval/src/eval/runner/harness.py

key-decisions:
  - "Store variant config in tickets table (not env vars) for cross-process communication"
  - "Harness writes variant via SQL UPDATE after ticket creation, not via monitor loop"
  - "Agent reads variant from ticket.variant_model/variant_system_prompt, backward compatible fallbacks"
  - "Timing: write variant config after chaos injection, before agent polls"

patterns-established:
  - "Database as config channel: operator.db mediates between harness and agent process"
  - "Graceful fallback: variant fields are optional, defaults preserve existing behavior"

# Metrics
duration: 3min
completed: 2026-01-30
---

# Phase 39 Plan 04: Gap Closure Summary

**Variant config flows from campaign YAML through harness SQL UPDATE into tickets table, read by agent loop to override model and system prompt for A/B testing**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-30T01:47:23Z
- **Completed:** 2026-01-30T01:50:38Z
- **Tasks:** 4
- **Files modified:** 6

## Accomplishments

- Gap closed: variant_config loaded but not applied → now flows through database to agent
- Agent reads variant_model and variant_system_prompt from ticket record
- Harness writes variant config to ticket via SQL UPDATE after chaos injection
- Complete end-to-end A/B testing infrastructure for agent configurations

## Task Commits

Each task was committed atomically:

1. **Task 1: Add variant columns to tickets table schema** - `3a7721f` (feat)
2. **Task 2: Update ticket DB classes to read variant fields** - `9e288eb` (feat)
3. **Task 3: Update process_ticket to use variant config from ticket** - `b60bba1` (feat)
4. **Task 4: Harness writes variant config to ticket after creation** - `ec9d029` (feat)

## Files Created/Modified

- `packages/operator-core/src/operator_core/db/schema.py` - Added variant_model, variant_system_prompt, variant_tools_config columns to tickets table
- `packages/operator-core/src/operator_core/monitor/types.py` - Added variant fields to Ticket dataclass
- `packages/operator-core/src/operator_core/db/tickets.py` - Updated _row_to_ticket() to read variant fields
- `packages/operator-core/src/operator_core/agent_lab/ticket_ops.py` - Updated poll_for_open_ticket() to read variant fields
- `packages/operator-core/src/operator_core/agent_lab/loop.py` - process_ticket reads variant_model and variant_system_prompt from ticket
- `eval/src/eval/runner/harness.py` - Added variant_config parameter to run_trial(), update_ticket_variant() function

## Decisions Made

**Store variant config in tickets table**
- Rationale: Agent runs in separate process, polls operator.db for tickets. Environment variables won't work across process boundary. Tickets table is existing communication channel (subject_context pattern).

**Harness writes via direct SQL UPDATE**
- Rationale: Variant config is eval-harness-specific, not part of monitor loop. Direct SQL UPDATE keeps monitor unchanged, writes early after chaos injection so agent picks it up when polling.

**Graceful fallback to defaults**
- Rationale: `ticket.variant_model or "claude-opus-4-20250514"` preserves backward compatibility. Existing tickets without variant fields use hardcoded defaults, new tickets from harness use variant config.

**Timing: write after chaos injection, before agent polls**
- Rationale: 2-second sleep after chaos injection gives monitor time to create ticket. Update before agent polls ensures variant config is present when agent reads ticket.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## Next Phase Readiness

- Phase 39 (Config Variants) complete - all 4 plans delivered
- Ready for v3.2 milestone audit
- A/B testing infrastructure fully operational: variant YAML → harness → tickets table → agent
- Future campaigns can now test different models, system prompts, and tools configs

---
*Phase: 39-config-variants*
*Completed: 2026-01-30*
