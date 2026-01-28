---
phase: 32
plan: 01
subsystem: infrastructure
tags: [docker, compose, networking, agent-container]
requires: [31-02]
provides:
  - agent-compose-config
  - agent-network-integration
  - agent-module-entrypoint
affects: [32-02, 32-03]
tech-stack:
  added: []
  patterns:
    - docker-compose-external-networks
    - docker-socket-mounting
    - python-module-entrypoint
key-files:
  created:
    - docker/agent/docker-compose.yml
    - packages/operator-core/src/operator_core/agent_lab/__main__.py
  modified:
    - docker/agent/Dockerfile
decisions:
  - decision: Use tikv_default external network
    rationale: TiKV compose creates default network named {project}_default, agent joins this existing network
    alternatives: [create-shared-network, use-host-network]
  - decision: Mount Docker socket for container control
    rationale: Agent needs to manage sibling containers (stop TiKV nodes for chaos scenarios)
    alternatives: [docker-api-client, kubernetes]
  - decision: Mount ~/.operator for shared database
    rationale: Host and container both need access to tickets.db for ticket creation and processing
    alternatives: [network-database, api-gateway]
  - decision: Install operator-protocols and operator-core in Dockerfile
    rationale: Agent loop depends on operator_core.agent_lab modules and operator-protocols is a dependency
    alternatives: [pip-install-from-pypi, mount-packages-as-volume]
metrics:
  tasks: 3
  duration: 2 minutes
  commits: 3
completed: 2026-01-28
---

# Phase 32 Plan 01: Agent Container Configuration Summary

**One-liner:** Docker Compose configuration for agent container with TiKV network integration, Docker socket access, and operator-core package installation.

## Objective Completion

Created Docker Compose file for agent container that:
- Joins TiKV subject network (tikv_default external network)
- Has Docker socket access for container control
- Shares ~/.operator directory with host for tickets.db
- Includes operator-core and operator-protocols packages
- Can run agent loop via python module entry point

## What Was Built

### 1. Agent Docker Compose File
**File:** `docker/agent/docker-compose.yml`

- Service named `agent` with build context pointing to repository root
- External network reference to `tikv_default` (created by TiKV compose)
- Volume mounts:
  - `/var/run/docker.sock:/var/run/docker.sock` - Docker control
  - `${HOME}/.operator:/root/.operator` - Shared database
- Environment variables:
  - `ANTHROPIC_API_KEY` - API authentication
  - `OPERATOR_SAFETY_MODE=execute` - No approval needed in lab
  - `PROMETHEUS_URL=http://prometheus:9090` - TiKV stack Prometheus
  - `PYTHONUNBUFFERED=1` - Streaming output
- Command: `python -m operator_core.agent_lab /root/.operator/tickets.db`

### 2. Agent Loop Module Entry Point
**File:** `packages/operator-core/src/operator_core/agent_lab/__main__.py`

- Enables `python -m operator_core.agent_lab` invocation
- Default database path: `~/.operator/tickets.db`
- Command line override support: `python -m operator_core.agent_lab /custom/path/tickets.db`
- Calls `run_agent_loop(db_path)` from loop.py

### 3. Agent Dockerfile Updates
**File:** `docker/agent/Dockerfile`

- Copy operator-protocols package (dependency)
- Copy operator-core package
- Install both packages in development mode with `pip install -e`
- Ensures agent container can import and run agent_lab modules

## Network Architecture

The agent container joins the TiKV network via external network reference:

```
tikv_default network (created by subjects/tikv/docker-compose.yaml):
  - pd0, pd1, pd2 (PD cluster)
  - tikv0, tikv1, tikv2 (TiKV cluster)
  - prometheus (metrics collection)
  - grafana (visualization)
  - agent (new - this plan)
```

Agent can now:
- Reach PD cluster: `curl pd0:2379/pd/api/v1/health`
- Query Prometheus: `curl prometheus:9090/api/v1/query`
- Control containers: `docker stop tikv0` (via mounted socket)
- Access internet: `curl google.com` (default Docker networking)

## Decisions Made

1. **External Network Reference**: Used `external: true` for tikv_default instead of creating a shared network. This is the standard Docker Compose pattern for connecting to networks created by other compose files.

2. **Docker Socket Mounting**: Mounted `/var/run/docker.sock` to give agent control over sibling containers. This is necessary for chaos scenarios (stopping TiKV nodes) and validates the "agent can control containers" requirement.

3. **Shared Database via Volume Mount**: Used `${HOME}/.operator` volume mount instead of network database. Simple, direct access for both host (ticket creation) and container (agent processing).

4. **Development Mode Installation**: Used `pip install -e` for operator packages to support development workflow. Changes to host packages reflect in container after rebuild.

## Task Breakdown

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Create agent Docker Compose file | a2438f0 | docker/agent/docker-compose.yml |
| 2 | Add agent loop entry point | c9c1d0d | agent_lab/__main__.py |
| 3 | Update Dockerfile for operator-core | 7bafeef | docker/agent/Dockerfile |

## Verification Results

All verification checks passed:
- ✓ Compose file validates: `docker compose -f docker/agent/docker-compose.yml config`
- ✓ Agent image builds: `docker build -f docker/agent/Dockerfile -t operator-agent:test .`
- ✓ Network reference correct: tikv_default with external: true
- ✓ Module entry point works: `python -m operator_core.agent_lab` imports successfully

## Deviations from Plan

**[Rule 3 - Blocking] Added operator-protocols to Dockerfile**
- **Found during:** Task 3 - Dockerfile build
- **Issue:** operator-core depends on operator-protocols, build failed with "No matching distribution found for operator-protocols"
- **Fix:** Added COPY and pip install for operator-protocols before operator-core
- **Files modified:** docker/agent/Dockerfile
- **Commit:** 7bafeef

This was a blocking issue (Rule 3) - couldn't complete task without fixing the missing dependency.

## Integration Points

### Upstream Dependencies
- Phase 31-02: Agent loop implementation (run_agent_loop function)
- Phase 30-01: Agent container base Dockerfile

### Downstream Enablement
- Phase 32-02: Demo script integration (can now run agent container)
- Phase 32-03: TiKV failure scenario validation (agent can reach TiKV network)

## Testing Evidence

```bash
# Compose validates
$ docker compose -f docker/agent/docker-compose.yml config
name: agent
services:
  agent:
    networks:
      tikv_default: null
networks:
  tikv_default:
    name: tikv_default
    external: true

# Image builds successfully
$ docker build -f docker/agent/Dockerfile -t operator-agent:test .
Successfully installed operator-protocols-0.1.0 operator-core-0.1.0 ...

# Module entry point works
$ python -c "from operator_core.agent_lab.__main__ import run_agent_loop; print('Import successful')"
Import successful
```

## Next Phase Readiness

**Phase 32 can proceed to Plan 02 (Demo Script Integration):**
- ✓ Agent container configured and builds
- ✓ Agent can join TiKV network
- ✓ Agent has Docker socket access
- ✓ Agent has shared database mount
- ✓ Agent can run via module entry point

**No blockers.** Ready for integration with demo script.

## Files Modified

```
docker/agent/docker-compose.yml (created)
  - Agent service configuration
  - External network reference
  - Volume mounts and environment variables

packages/operator-core/src/operator_core/agent_lab/__main__.py (created)
  - Module entry point for agent loop
  - Database path configuration

docker/agent/Dockerfile (modified)
  - Added operator-protocols package copy and install
  - Added operator-core package copy and install
```

## Commits

- `a2438f0` - feat(32-01): create agent Docker Compose file
- `c9c1d0d` - feat(32-01): add agent loop entry point
- `7bafeef` - feat(32-01): update agent Dockerfile for operator-core

## Lessons Learned

1. **External Networks Pattern**: Docker Compose external networks require the other compose file to be started first. Agent compose will fail if TiKV compose isn't running.

2. **Python Package Dependencies**: Local package dependencies need explicit COPY and install in Dockerfile. Pip won't find local packages automatically.

3. **Module Entry Points**: `__main__.py` is the standard pattern for making Python packages executable with `-m` flag.
