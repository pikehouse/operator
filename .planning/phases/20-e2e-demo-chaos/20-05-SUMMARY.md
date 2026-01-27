# Summary: 20-05 E2E Validation

## What Was Done

Human verification of both demos completed successfully:

1. **Rate limiter demo** — Both chaos scenarios work:
   - Counter drift chaos (Redis PAUSE) triggers violations
   - Ghost allowing chaos (burst traffic) triggers violations
   - AI diagnosis identifies anomaly types correctly

2. **TiKV demo** — Still works after refactoring:
   - Node kill causes store_down violation
   - AI diagnosis identifies affected store
   - Recovery restarts the node

3. **AI diagnosis quality** — Meets quality bar:
   - No rate-limiter-specific prompts in operator-core
   - Subject-specific context comes from observation dict
   - Structured reasoning for both subjects

## Improvements Made During Verification

- Enhanced agent panel output (severity, root cause, recommendation summary)
- Full diagnosis saved to `/tmp/diagnosis-{ticket}-{invariant}-{timestamp}.md`
- Auto-stop conflicting cluster before starting demo (port 9090)
- Load generators cleaned up on demo exit (YCSB for TiKV, loadgen for rate limiter)

## Verification Results

| Checkpoint | Status |
|------------|--------|
| Rate limiter demo runs | ✓ Approved |
| TiKV demo runs | ✓ Approved |
| AI diagnosis quality | ✓ Approved |

## Files Modified

- `packages/operator-core/src/operator_core/agent/runner.py` — Enhanced diagnosis output
- `demo/tui_integration.py` — Load generator cleanup on exit
- `scripts/run-demo.sh` — Always stop conflicting cluster

## Commits

- `fix(20): enhance agent diagnosis output with summary and file link`
- `fix(20): cleanup load generators on demo exit`
- `fix(20): always stop conflicting cluster before demo start`

## Phase 20 Complete

All 5 plans executed:
- 20-01: Shared demo infrastructure
- 20-02: TiKV demo integration
- 20-03: Rate limiter demo integration
- 20-04: TUI integration
- 20-05: E2E validation (human verified)

**Phase goal achieved:** AI diagnoses rate limiter anomalies without system-specific prompts, using the same patterns as TiKV.
