# Plan 35-04 Summary: CLI with run command

## Status: COMPLETE

## What Was Built

Implemented the `eval` CLI with run command for single-trial execution, providing the developer interface for running evaluations against TiKV subjects.

## Files Changed

| File | Change | Commit |
|------|--------|--------|
| eval/src/eval/cli.py | Created CLI with run command | f463ce9 |
| eval/src/eval/__init__.py | Updated exports | 1600ac8 |

## Key Deliverables

### eval CLI (CLI-01, CLI-02)

- `eval run --subject tikv --chaos node_kill` - Run single trial
- `eval run --baseline` - Run without agent (self-healing test)
- `eval run --trials N` - Run N trials as campaign
- `--db` option for custom database path
- `--operator-db` option for command extraction

### Implementation Highlights

- Uses Typer for CLI framework
- Asyncio bridge via `asyncio.run()` for async harness
- Auto-detects operator.db if not specified
- Validates chaos type against subject's available types
- Single trial creates 1-trial campaign for consistency

### Package Exports

Updated `eval/__init__.py` to export:
- Types: EvalSubject, ChaosType, Campaign, Trial
- Runner: EvalDB, run_trial, run_campaign

## Verification

Human verification confirmed:
- TiKV cluster starts successfully
- `eval run --baseline` executes full trial sequence
- Trial data persists to eval.db with all timing fields
- Campaign and trial records visible in database

## Success Criteria

- [x] eval CLI installs via pyproject.toml scripts entry
- [x] `eval run --subject tikv --chaos node_kill` runs single trial
- [x] `eval run --baseline` runs trial without agent waiting
- [x] Trial data persists to eval.db with all timing fields
- [x] CLI validates chaos type against subject's available types
- [x] Human verification confirms end-to-end flow works
