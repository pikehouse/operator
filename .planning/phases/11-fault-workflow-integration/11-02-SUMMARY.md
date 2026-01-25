# Phase 11 Plan 02: Fault Workflow Integration Summary

**One-liner:** FaultWorkflow module with countdown display, Docker-based node kill/recovery, and chapter callback integration for end-to-end demo automation.

## What Was Built

### FaultWorkflow Module (`fault.py`)
- Created `FaultWorkflow` dataclass with async methods for countdown, fault injection, and recovery
- Implements countdown with `asyncio.wait_for` pattern for interruptible 1-second ticks
- Uses `python-on-whales` DockerClient for container operations (adapted from chaos.py)
- Stores killed container name for recovery
- Simulates workload degradation (80% -> 20% of baseline) and recovery (30% -> 100%)
- Provides `establish_baseline` method for configurable baseline ops/sec

### Chapter Callback Extension (`chapters.py`)
- Extended `Chapter` dataclass with `on_enter`, `auto_advance`, and `blocks_advance` fields
- Added `create_fault_chapter` helper for fault injection with blocking behavior
- Added `create_recovery_chapter` helper for recovery with auto-advance
- Maintains backward compatibility with existing chapters (defaults for new fields)

### TUIController Integration (`controller.py`)
- Added `compose_file` constructor parameter for fault injection configuration
- Creates `FaultWorkflow` instance during `run()` initialization
- Replaces fault injection chapter (index 3) with callback version at runtime
- Inserts recovery chapter before "Demo Complete" (index 6)
- Seeds workload tracker with baseline values (10000 ops/sec)
- Updated `_handle_key` to:
  - Check `blocks_advance` before allowing chapter advancement
  - Execute `on_enter` callbacks as async tasks
  - Track fault task for blocking behavior
- Added helper methods:
  - `_update_narration_text`: Direct narration panel update for countdown
  - `_execute_chapter_callback`: Async callback executor with auto-advance
  - `_run_fault_sequence`: Countdown -> kill -> degradation sequence
  - `_run_recovery_sequence`: Restart -> recovery sequence

## Key Implementation Details

### Countdown Pattern
```python
for i in range(seconds, 0, -1):
    self.on_narration_update(f"[bold yellow]Injecting fault in {i}...[/bold yellow]")
    try:
        await asyncio.wait_for(self.shutdown_event.wait(), timeout=1.0)
        return False  # Interrupted
    except asyncio.TimeoutError:
        continue  # Normal tick
```

### Chapter Callback Flow
1. User presses advance key (SPACE/ENTER/RIGHT)
2. `_handle_key` checks if current chapter `blocks_advance`
3. If blocked and task running, ignore keypress
4. Otherwise advance and check new chapter for `on_enter`
5. If callback exists, create task and track in `_fault_task`
6. Callback executes async (countdown, kill, degradation)
7. If `auto_advance`, automatically move to next chapter

### Container Recovery
- Extracts service name from Docker container name
- Container names include project prefix: "operator-tikv-tikv0-1" -> "tikv0"
- Uses `compose.start(services=[service_name])` for restart

## Files Modified

| File | Changes |
|------|---------|
| `tui/fault.py` | New: FaultWorkflow class (159 lines) |
| `tui/chapters.py` | Extended Chapter, added helper functions |
| `tui/controller.py` | FaultWorkflow integration, callback execution |
| `tui/__init__.py` | Export FaultWorkflow |

## Commits

| Hash | Description |
|------|-------------|
| 3c9b68f | feat(11-02): create FaultWorkflow module |
| 82c1fbf | feat(11-02): extend Chapter dataclass |
| a317700 | feat(11-02): integrate FaultWorkflow into TUIController |

## Verification Results

1. FaultWorkflow imports correctly
2. Chapter accepts on_enter callback (lambda test passed)
3. TUIController accepts compose_file parameter
4. fault.py has 159 lines (exceeds 80-line minimum)
5. All key patterns present in controller.py (FaultWorkflow, on_enter, etc.)

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Fulfilled

- **DEMO-03:** Countdown display before fault injection (3... 2... 1...)
- **DEMO-04:** Recovery chapter restarts killed node

## Duration

Approximately 15 minutes

## Next Plan Readiness

Ready for 11-03-PLAN.md (End-to-end integration testing if applicable).

The fault workflow is now fully integrated:
- Key press on fault chapter triggers countdown sequence
- Countdown displays in narration panel
- Node kill occurs after countdown
- Workload degradation simulated
- Recovery chapter restarts node
- Workload recovery simulated
