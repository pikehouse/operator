# Summary: Quick Task 001 - Remove demo logic from operator-core

## What Was Done

Cleaned up operator-core to remove all demo-specific logic:

1. **Removed `operator_core/demo/` directory**
   - Deleted `__init__.py` and `chaos.py` (TiKV-specific chaos demo)

2. **Removed demo CLI command**
   - Deleted `cli/demo.py`
   - Removed `demo_app` from `cli/main.py`

3. **Removed demo-specific TUI modules**
   - Deleted `tui/chapters.py` (demo chapter state machine)
   - Deleted `tui/fault.py` (TiKV fault injection)
   - Deleted `tui/controller.py` (TUIController)
   - Deleted `tui/health.py` (TiKV-specific ClusterHealthPoller)
   - Deleted `tui/workload.py` (TiKV workload tracking)

4. **Updated TUI `__init__.py`**
   - Now only exports reusable components:
     - `OutputBuffer` - ring buffer for subprocess output
     - `create_layout`, `make_panel`, `make_cluster_panel`, `make_workload_panel` - panel helpers
     - `ManagedProcess`, `SubprocessManager` - subprocess lifecycle
     - `KeyboardTask` - non-blocking keyboard input

5. **Updated legacy scripts**
   - `run-tui.sh` now redirects to `./scripts/run-demo.sh tikv`
   - Deleted `tui_main.py` (no longer needed)

## Files Changed

Deleted:
- `packages/operator-core/src/operator_core/demo/__init__.py`
- `packages/operator-core/src/operator_core/demo/chaos.py`
- `packages/operator-core/src/operator_core/cli/demo.py`
- `packages/operator-core/src/operator_core/tui/chapters.py`
- `packages/operator-core/src/operator_core/tui/controller.py`
- `packages/operator-core/src/operator_core/tui/fault.py`
- `packages/operator-core/src/operator_core/tui/health.py`
- `packages/operator-core/src/operator_core/tui/workload.py`
- `scripts/tui_main.py`

Modified:
- `packages/operator-core/src/operator_core/cli/main.py`
- `packages/operator-core/src/operator_core/tui/__init__.py`
- `scripts/run-tui.sh`

## Verification

- `ls packages/operator-core/src/operator_core/demo/` → No such file or directory ✓
- `from operator_core.tui import OutputBuffer, SubprocessManager, KeyboardTask, create_layout` → OK ✓
- `from operator_core.tui import TUIController` → ImportError ✓ (correctly removed)
- `from operator_core.cli.main import app` → OK ✓

## Result

Clean separation achieved:
- **operator-core**: Generic, reusable components only
- **demo/**: Subject-specific demo logic (TiKV and rate limiter)
