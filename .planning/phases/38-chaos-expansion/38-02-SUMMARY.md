---
phase: 38-chaos-expansion
plan: 02
subsystem: eval-runner
tags: [yaml, pyyaml, asyncio, semaphore, parallel-execution, campaign-matrix]

# Dependency graph
requires:
  - phase: 38-01
    provides: Extended chaos types (latency, disk_pressure, network_partition) with cleanup protocol
  - phase: 35-runner-layer
    provides: Core harness (run_trial, run_campaign) and database schema
provides:
  - YAML-based campaign configuration with Pydantic validation
  - Matrix expansion (subjects x chaos_types x trials_per_combination)
  - Parallel trial execution with semaphore control
  - Chaos cleanup protocol integration in trial runner
  - CLI campaign subcommand for batch evaluation
affects: [39-config-variants, future-multi-subject-campaigns]

# Tech tracking
tech-stack:
  added: [pyyaml>=6.0]
  patterns:
    - Campaign matrix expansion via itertools.product
    - Parallel execution control via asyncio.Semaphore
    - Chaos cleanup after final_state capture for state consistency

key-files:
  created:
    - eval/src/eval/runner/campaign.py
  modified:
    - eval/pyproject.toml
    - eval/src/eval/runner/harness.py
    - eval/src/eval/cli.py

key-decisions:
  - "Campaign matrix expansion uses Cartesian product for subjects x chaos_types"
  - "Chaos cleanup placed AFTER final_state capture to preserve during-chaos state snapshot"
  - "run_campaign_from_config() is NEW function - existing run_campaign() unchanged for backward compatibility"
  - "Semaphore limits concurrency per config.parallel setting"
  - "Failed trials logged but campaign continues (fail gracefully)"

patterns-established:
  - "YAML campaigns define matrix configuration, runtime expands to trial specs"
  - "Cleanup metadata returned from inject_chaos() enables stateless cleanup"
  - "Trial execution sequence: reset -> inject -> wait -> final_state -> cleanup -> return Trial"

# Metrics
duration: 4min
completed: 2026-01-30
---

# Phase 38 Plan 02: Campaign YAML Configuration Summary

**YAML-based campaign runner with parallel execution, matrix expansion, and chaos cleanup protocol**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-30T00:02:44Z
- **Completed:** 2026-01-30T00:06:47Z
- **Tasks:** 3
- **Files modified:** 3 (1 created)

## Accomplishments
- Campaign YAML configuration with Pydantic validation (CampaignConfig, ChaosSpec models)
- Matrix expansion generating trial specs from subjects x chaos_types Cartesian product
- Parallel trial runner with asyncio.Semaphore respecting config.parallel setting
- Chaos cleanup integrated into run_trial() after final_state capture
- CLI campaign subcommand enabling batch evaluation workflows

## Task Commits

Each task was committed atomically:

1. **Task 1: Add PyYAML dependency and create campaign config module** - `b418e02` (feat)
2. **Task 2: Update harness with parallel campaign runner** - `54d37a2` (feat)
3. **Task 3: Add CLI campaign subcommand** - `c906a97` (feat)

## Files Created/Modified
- `eval/pyproject.toml` - Added pyyaml>=6.0 dependency
- `eval/src/eval/runner/campaign.py` - YAML config loader, Pydantic models (CampaignConfig, ChaosSpec), matrix expansion
- `eval/src/eval/runner/harness.py` - Added chaos_params parameter to run_trial(), cleanup_chaos() call after final_state, NEW run_campaign_from_config() function
- `eval/src/eval/cli.py` - Added campaign subcommand to run_app with config validation and auto-detection

## Decisions Made

**Campaign matrix expansion approach:**
- Use itertools.product for Cartesian product (subjects x chaos_types)
- Generate trial specs with chaos_params dict for per-chaos configuration
- Include optional baseline trials (one per subject, no chaos)

**Chaos cleanup protocol:**
- Place cleanup_chaos() call AFTER final_state capture, BEFORE Trial construction
- Ensures final_state reflects during-chaos conditions
- Handle exceptions gracefully (container may be killed/restarted in node_kill scenario)

**Backward compatibility:**
- run_campaign_from_config() is NEW function for YAML campaigns
- Existing run_campaign() function UNCHANGED for CLI backward compatibility
- Both functions coexist in harness.py

**Parallel execution control:**
- asyncio.Semaphore limits concurrent trials to config.parallel value
- Valid range: 1-10 (enforced by Pydantic validator)
- Cooldown (asyncio.sleep) between trials respects config.cooldown_seconds

**Failure handling:**
- Failed trials logged but campaign continues
- Completed/failed counts reported at end
- Exceptions caught per-trial, not campaign-level

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all verifications passed:
- PyYAML installed successfully
- Campaign module imports work
- Matrix expansion generates correct trial specs
- Both run_campaign functions available (backward compatibility verified)
- CLI help displays correctly with example YAML config

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Phase 39 (Config Variants):
- Campaign YAML infrastructure complete
- Matrix expansion supports parameterized chaos types
- Parallel execution framework ready for config variant testing
- Database schema supports arbitrary chaos_params in chaos_metadata JSON field

No blockers. Campaign runner can now execute batch evaluations with:
- Multiple chaos types per campaign
- Per-chaos-type parameter configuration
- Controlled parallelism and cooldown
- Resumable state tracking in database

---
*Phase: 38-chaos-expansion*
*Completed: 2026-01-30*
