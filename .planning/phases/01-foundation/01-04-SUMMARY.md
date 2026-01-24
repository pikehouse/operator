---
phase: 01-foundation
plan: 04
subsystem: infra
tags: [typer, cli, docker-compose, deployment]

# Dependency graph
requires:
  - phase: 01-03
    provides: LocalDeployment implementation and DeploymentTarget Protocol
  - phase: 01-02
    provides: Subject Protocol (for future CLI expansion)
provides:
  - Typer CLI with deploy local subcommands
  - `operator` command entry point via pyproject.toml console_scripts
  - TiKV stub docker-compose.yaml for deployment testing
affects: [02-tikv, 03-local-cluster]

# Tech tracking
tech-stack:
  added: []
  patterns: [Typer subcommand nesting, CLI-to-implementation wiring]

key-files:
  created:
    - packages/operator-core/src/operator_core/cli/__init__.py
    - packages/operator-core/src/operator_core/cli/main.py
    - packages/operator-core/src/operator_core/cli/deploy.py
    - subjects/tikv/docker-compose.yaml
  modified:
    - packages/operator-core/pyproject.toml
    - packages/operator-core/src/operator_core/deploy.py

key-decisions:
  - "Subject defaults to 'tikv' in CLI commands per CONTEXT.md"
  - "Stub docker-compose uses nginx:alpine placeholder for Phase 1 testing"
  - "Port binding is dict not object in python-on-whales (bug fix in deploy.py)"

patterns-established:
  - "CLI structure: app.add_typer() for nested subcommand groups"
  - "Error handling: typer.Exit(1) for clean CLI failures with Rich output"

# Metrics
duration: 1min 55s
completed: 2026-01-24
---

# Phase 01 Plan 04: CLI Deploy Commands Summary

**Typer CLI with `operator deploy local up/down/status/logs/restart` commands wired to LocalDeployment, plus nginx stub for deployment testing**

## Performance

- **Duration:** 1 min 55 s
- **Started:** 2026-01-24T20:15:23Z
- **Completed:** 2026-01-24T20:17:18Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- Working `operator` CLI command with deploy subcommand structure
- All five deploy local commands implemented: up, down, status, logs, restart
- End-to-end deployment flow validated with Docker container lifecycle
- Subject defaults to "tikv" per CONTEXT.md decisions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CLI module with deploy commands** - `39cb36f` (feat)
2. **Task 2: Add CLI entry point to pyproject.toml** - `197e3d0` (feat)
3. **Task 3: Create stub TiKV docker-compose.yaml** - `08993b3` (feat)

## Files Created/Modified
- `packages/operator-core/src/operator_core/cli/__init__.py` - Package marker for cli module
- `packages/operator-core/src/operator_core/cli/main.py` - Typer app entry point
- `packages/operator-core/src/operator_core/cli/deploy.py` - Deploy local subcommands
- `packages/operator-core/pyproject.toml` - Added [project.scripts] for operator command
- `subjects/tikv/docker-compose.yaml` - Stub compose with nginx placeholder
- `packages/operator-core/src/operator_core/deploy.py` - Fixed port binding dict access

## Decisions Made
- Subject argument defaults to "tikv" in all deploy local commands (per CONTEXT.md)
- Used nginx:alpine as placeholder service for Phase 1 testing (real TiKV in Phase 3)
- Rich Console and Table for formatted CLI output

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed port binding attribute access in deploy.py**
- **Found during:** Task 3 (Testing full deployment cycle)
- **Issue:** `deploy.py` from Plan 03 accessed `binding.host_port` but python-on-whales returns port bindings as dicts with `HostPort` key
- **Fix:** Changed to `binding.get("HostPort") if isinstance(binding, dict) else binding.host_port` for compatibility
- **Files modified:** packages/operator-core/src/operator_core/deploy.py
- **Verification:** `operator deploy local up/status/down tikv` cycle works without error
- **Committed in:** `08993b3` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix necessary for deployment to work. No scope creep.

## Issues Encountered
None beyond the auto-fixed bug.

## User Setup Required
None - Docker must be running for deployment commands, but no external service configuration required.

## Next Phase Readiness
- DEPLOY-02 requirement satisfied: `operator deploy local up` is a working command
- Phase 1 Foundation complete: workspace, Subject Protocol, DeploymentTarget Protocol, CLI
- Ready for Phase 2 (TiKV Subject implementation) or Phase 3 (Local Cluster with real TiKV)

---
*Phase: 01-foundation*
*Completed: 2026-01-24*
