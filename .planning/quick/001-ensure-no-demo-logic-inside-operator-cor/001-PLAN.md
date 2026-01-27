---
phase: quick
plan: 001
type: execute
wave: 1
depends_on: []
files_modified:
  - packages/operator-core/src/operator_core/demo/__init__.py
  - packages/operator-core/src/operator_core/demo/chaos.py
  - packages/operator-core/src/operator_core/cli/demo.py
  - packages/operator-core/src/operator_core/cli/main.py
  - packages/operator-core/src/operator_core/tui/__init__.py
  - packages/operator-core/src/operator_core/tui/chapters.py
  - packages/operator-core/src/operator_core/tui/controller.py
  - packages/operator-core/src/operator_core/tui/fault.py
  - scripts/run-tui.sh
  - scripts/tui_main.py
autonomous: true

must_haves:
  truths:
    - "No demo/ directory exists in operator-core"
    - "No demo CLI command exists in operator-core"
    - "TUI module only exports reusable components (layout, buffer, subprocess, keyboard)"
    - "Old TUI scripts redirect to new demo framework"
  artifacts: []
  key_links: []
---

<objective>
Remove demo-specific logic from operator-core, keeping only reusable TUI components.

The new demo framework at project root (`demo/`) handles both TiKV and rate limiter demos.
The old TiKV-specific demo code in operator-core is no longer needed.

Output: Clean separation - operator-core has generic components, demo logic lives in demo/ module.
</objective>

<tasks>

<task id="1" type="code" autonomy="full">
  <title>Remove operator_core/demo/ directory</title>
  <why>TiKV-specific chaos demo is now handled by demo/tikv.py</why>
  <what>
    - Delete packages/operator-core/src/operator_core/demo/__init__.py
    - Delete packages/operator-core/src/operator_core/demo/chaos.py
    - Remove the demo/ directory
  </what>
  <done>demo/ directory no longer exists in operator-core</done>
</task>

<task id="2" type="code" autonomy="full">
  <title>Remove demo CLI command</title>
  <why>operator demo chaos is TiKV-specific and replaced by ./scripts/run-demo.sh</why>
  <what>
    - Delete packages/operator-core/src/operator_core/cli/demo.py
    - Update packages/operator-core/src/operator_core/cli/main.py to remove demo_app import and registration
  </what>
  <done>operator demo command no longer exists</done>
</task>

<task id="3" type="code" autonomy="full">
  <title>Remove demo-specific TUI modules</title>
  <why>TUIController, chapters.py, fault.py are TiKV-specific demo code</why>
  <what>
    - Delete packages/operator-core/src/operator_core/tui/chapters.py
    - Delete packages/operator-core/src/operator_core/tui/fault.py
    - Delete packages/operator-core/src/operator_core/tui/controller.py
    - Update packages/operator-core/src/operator_core/tui/__init__.py to only export reusable components:
      - OutputBuffer, ManagedProcess, SubprocessManager (subprocess management)
      - create_layout, make_panel, make_cluster_panel, make_workload_panel (layout)
      - KeyboardTask (keyboard handling)
      - Keep health.py but remove TiKV-specific parts if any
  </what>
  <done>TUI module only has reusable components</done>
</task>

<task id="4" type="code" autonomy="full">
  <title>Update old TUI scripts</title>
  <why>run-tui.sh and tui_main.py should use new demo framework</why>
  <what>
    - Update scripts/run-tui.sh to call ./scripts/run-demo.sh tikv
    - Delete scripts/tui_main.py (no longer needed)
  </what>
  <done>Old scripts redirect to new framework</done>
</task>

<task id="5" type="verify" autonomy="full">
  <title>Verify cleanup</title>
  <what>
    - Confirm no demo logic in operator-core
    - Confirm operator CLI still works (minus demo command)
    - Confirm ./scripts/run-demo.sh tikv still works
  </what>
  <done>Clean separation verified</done>
</task>

</tasks>

<verification>
1. `ls packages/operator-core/src/operator_core/demo/` returns error (doesn't exist)
2. `grep -r "demo" packages/operator-core/src/operator_core/cli/` returns no demo.py
3. `python -c "from operator_core.tui import TUIController"` fails (removed)
4. `python -c "from operator_core.tui import OutputBuffer, SubprocessManager, KeyboardTask, create_layout"` succeeds
5. `./scripts/run-demo.sh tikv` works
</verification>
