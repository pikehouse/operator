# Project State: Operator

## Current Position

**Milestone:** v2.3 Infrastructure Actions & Script Execution
**Phase:** Phase 25 - Host Actions (COMPLETE)
**Plan:** 03 of 3 complete
**Status:** Phase complete
**Last activity:** 2026-01-28 — Completed 25-03-PLAN.md (action registration)

Progress: [███████░░░] 43% (Phase 3 of 7 complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-27)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — and now infrastructure-level remediation with Docker control and script execution.

**Current focus:** v2.3 — expanding action capabilities to infrastructure control (Docker, host operations) and sandboxed script execution with iterative agent feedback.

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | SHIPPED | 2026-01-27 |
| v2.2 | SHIPPED | 2026-01-27 |
| v2.3 | IN PROGRESS | — |

See: .planning/MILESTONES.md

## v2.3 Phase Overview

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 23 | Safety Enhancement | SAFE-01 through SAFE-08 (8) | Complete ✓ |
| 24 | Docker Actions | DOCK-01 through DOCK-10 (10) | Complete ✓ |
| 25 | Host Actions | HOST-01 through HOST-07 (7) | Complete ✓ |
| 26 | Script Execution & Validation | SCRP-01 through SCRP-09, VALD-01 through VALD-06 (15) | Pending |
| 27 | Risk Classification | RISK-01 through RISK-06 (6) | Pending |
| 28 | Agent Integration | AGNT-01 through AGNT-04 (4) | Pending |
| 29 | Demo Scenarios | DEMO-01, DEMO-02 (2) | Pending |

**Total:** 7 phases, 52 requirements

## Performance Metrics

**v2.2 (most recent):**
- 2 phases, 3 plans
- 8 files modified
- ~400 lines added
- 25 commits
- 1 day from start to ship

**v2.1:**
- 5 phases, 21 plans
- 146 files changed
- ~18,000 lines added
- 87 commits
- 2 days from start to ship

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | v1.0 roadmap (6 phases) |
| milestones/v1.0-REQUIREMENTS.md | v1.0 requirements (19 total) |
| milestones/v1.1-ROADMAP.md | v1.1 roadmap (5 phases) |
| milestones/v1.1-REQUIREMENTS.md | v1.1 requirements (11 total) |
| milestones/v1.1-MILESTONE-AUDIT.md | v1.1 audit report |
| milestones/v2.0-ROADMAP.md | v2.0 roadmap (4 phases) |
| milestones/v2.0-REQUIREMENTS.md | v2.0 requirements (17 total) |
| milestones/v2.1-ROADMAP.md | v2.1 roadmap (5 phases) |
| milestones/v2.2-ROADMAP.md | v2.2 roadmap (2 phases) |

## Accumulated Context

**Decisions from prior milestones:**
- Observe-only first - proved AI diagnosis quality before action
- Protocol-based abstractions - Subject and DeploymentTarget extensible
- Subprocess isolation for TUI - daemons run as real processes
- httpx, Pydantic, aiosqlite stack - proven across 5 milestones

**Key decisions from v2.0:**
- Pydantic BaseModel for action types (validation + serialization)
- Default to OBSERVE mode (safe by default, explicit opt-in for execution)
- Kill switch cancels pending AND switches to OBSERVE mode
- Fire-and-forget action semantics for PD API calls
- Tools use same ActionDefinition model with action_type=ActionType.TOOL

**Key decisions from v2.1:**
- Protocol-based abstractions (SubjectProtocol, InvariantCheckerProtocol) in zero-dependency operator-protocols package
- Factory returns tuple[Subject, Checker] for convenience
- Lazy import in subject_factory.py prevents loading operator-ratelimiter unless needed
- TiKVHealthPoller and RateLimiterHealthPoller return generic dict for framework flexibility
- Both demos use same TUI layout (5 panels) via TUIDemoController
- Monitor/agent subprocesses use --subject flag for subject selection

**Key decisions from v2.2 (Phase 21):**
- Fixed 5s delay for verification (not adaptive polling) - sufficient for demo
- Simplified verification logs success if metrics observed (full invariant re-check is future work)
- Propose -> Validate -> Execute -> Verify agentic flow in AgentRunner
- Environment variables for mode configuration (OPERATOR_SAFETY_MODE, OPERATOR_APPROVAL_MODE)
- SubprocessManager.spawn() accepts env dict, merges with os.environ

**Key decisions from v2.2 (Phase 22):**
- Renamed "AI Diagnosis" stages to "AI Remediation" to reflect full agentic loop
- Explicit action names in narratives (transfer_leader, reset_counter) for viewer understanding
- Consistent narration pattern: "Watch Agent panel for complete agentic loop" + numbered steps

**v2.3 Architecture (from research):**
- python-on-whales (existing) + asyncio.run_in_executor() pattern for async Docker operations
- aiofiles 25.1.0 (NEW) for async host file operations
- Three dedicated executor components: DockerActionExecutor, HostActionExecutor, ScriptSandbox
- All infrastructure actions integrate via ActionType.TOOL (no framework changes)
- Script execution two-phase: agent generates -> system validates -> sandbox executes -> output captured
- Multi-layer validation: syntax check, secrets scanning, dangerous command detection
- Sandbox isolation: --network=none, --memory=512m, --cpus=1.0, user=nobody, read-only FS
- Safety-first build order: Phase 23 (Safety) before infrastructure capabilities

**Key decisions from v2.3 (Phase 23):**
- Identity fields use sensible defaults (requester_id='unknown', requester_type='agent', agent_id=None) for backwards compatibility
- Default authorization checkers allow all requests (permissive for development, restrict in production)
- Authorization protocols (PermissionChecker, CapabilityChecker) enable pluggable implementations
- Database migration uses individual try/except per column for clean migration of existing databases
- OAuth delegation model: requester_id (resource owner) + agent_id (client acting on their behalf)
- Session risk scoring: 5-minute time window, 30-second rapid threshold, 1.5x frequency multiplier
- Four-tier risk levels: LOW (0-9), MEDIUM (10-24), HIGH (25-49), CRITICAL (50+)
- Overlapping pattern matches intentional (represent increasing risk)
- Force-terminate Docker via subprocess (asyncio.Task.cancel limitation workaround)
- Kill switch returns detailed dict instead of int (pending_proposals, docker_containers, asyncio_tasks)
- Redact secrets BEFORE json.dumps() and database write, not after retrieval (defense-in-depth)
- Structure-first processing in SecretRedactor: check dict/list types before key sensitivity
- Dual detection strategy: key-based (field names) + pattern-based (env vars, Bearer tokens)
- Double-check pattern for TOCTOU defense (pre-check, lock, re-check, atomic update)
- 60-second approval token expiration for stale approval prevention
- Optimistic locking via version field incremented on every update
- asyncio.Lock serializes execution attempts before atomic version-checked update

**Key decisions from v2.3 (Phase 24 Plan 01):**
- Default 10-second timeout for stop/restart operations (configurable via parameter)
- Idempotent operations: start on running container succeeds, stop on stopped container succeeds
- Exit code semantics: 143 = graceful SIGTERM shutdown, 137 = force killed (SIGKILL or OOM)
- Datetime fields serialized with .isoformat() for JSON compatibility
- Graceful handling of None values in optional fields (started_at)

**Key decisions from v2.3 (Phase 24 Plan 02):**
- Default tail 100 lines for get_container_logs (sufficient for most debugging)
- MAX_TAIL 10000 lines enforced silently (prevents memory exhaustion attacks)
- Never use follow=True in logs (blocks indefinitely, unsuitable for async)
- Always include timestamps in logs (essential for debugging)
- Network validation before connect (better error messages than docker exception)
- execute_command catches all exceptions (returns in error field, not raised)
- Non-interactive exec mode (tty=False, interactive=False for programmatic access)

**Key decisions from v2.3 (Phase 24 Plan 03):**
- Risk levels: LOW for read-only (logs, inspect), MEDIUM for state changes (start, network), HIGH for availability impact or arbitrary execution (stop, restart, exec)
- Lazy initialization of DockerActionExecutor in _get_docker_executor() to prevent circular import between tools.py and actions.py
- All Docker actions require approval except read-only operations (logs, inspect)
- Docker actions registered as ActionType.TOOL for agent discovery through get_general_tools()

**Key decisions from v2.3 (Phase 25 Plan 01):**
- FORBIDDEN_SERVICES take precedence over whitelist (even if manually added, is_allowed returns False)
- validate_service_name blocks path separators (/) and traversal (..) before whitelist check
- All service methods verify state after operation (systemctl is-active) for accurate success status
- Success requires both returncode=0 AND correct active state (start: active=True, stop: active=False)

**Key decisions from v2.3 (Phase 25 Plan 02):**
- PID < 300 threshold blocks kernel threads conservatively
- Signal 0 pre-validation confirms process existence and permission before actual signal
- Graceful timeout default 5s matches Docker/Kubernetes convention
- Escalation happens only after timeout loop completes (not partial)
- kill_process returns escalated=True only if SIGKILL was actually sent

**Key decisions from v2.3 (Phase 25 Plan 03):**
- Risk levels: MEDIUM for service start/restart (recoverable), HIGH for stop/kill_process (availability impact)
- Lazy initialization of HostActionExecutor in _get_host_executor() to prevent circular import between tools.py and actions.py
- All host actions require approval (no read-only host operations)
- Lambda wrappers map tool names to executor methods (host_service_start -> start_service)

## Session Continuity

**Last session:** 2026-01-28
**Stopped at:** Completed 25-03-PLAN.md (action registration) - Phase 25 complete
**Resume file:** None

## Open Issues

*None*

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Remove demo logic from operator-core | 2026-01-27 | 0770fee | [001-ensure-no-demo-logic-inside-operator-cor](./quick/001-ensure-no-demo-logic-inside-operator-cor/) |

---
*State updated: 2026-01-28 (Phase 25 complete)*
