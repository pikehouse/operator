# Roadmap: Operator

## Milestones

- [x] **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- [x] **v1.1 TUI Demo** - Phases 7-11 (shipped 2026-01-25)
- [x] **v2.0 Agent Actions** - Phases 12-15 (shipped 2026-01-26)
- [x] **v2.1 Multi-Subject Support** - Phases 16-20 (shipped 2026-01-27)
- [x] **v2.2 Agentic Remediations Demo** - Phases 21-22 (shipped 2026-01-27)
- [ ] **v2.3 Infrastructure Actions & Script Execution** - Phases 23-29 (in progress)

## v2.3 Infrastructure Actions & Script Execution

**Goal:** The action agent can remediate issues by controlling Docker infrastructure, modifying host processes, and generating/executing custom scripts in sandboxed containers — with output fed back for iterative reasoning.

**Phases:** 7
**Requirements:** 52 total
**Coverage:** 52/52 mapped (100%)

### Phase 23: Safety Enhancement

**Goal:** Existing safety controls enhanced to handle TOCTOU races, agent identity confusion, and multi-step attack chains before infrastructure actions are enabled.

**Dependencies:** None (foundation for all infrastructure capabilities)

**Requirements:** SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05, SAFE-06, SAFE-07, SAFE-08 (8)

**Success Criteria:**
1. User approves action, system state changes, approval workflow detects mismatch and blocks execution (TOCTOU resistance verified)
2. Audit logs show both requester identity and agent identity for all actions
3. Approval tokens expire after 60 seconds, preventing stale approvals
4. Session-level cumulative risk tracking identifies suspicious multi-action patterns
5. Kill switch force-terminates in-flight Docker operations (not just pending actions)

### Phase 24: Docker Actions

**Goal:** Agent can control Docker container lifecycle, access logs, and manage network connections for remediation scenarios.

**Dependencies:** Phase 23 (safety controls must be enhanced first)

**Requirements:** DOCK-01, DOCK-02, DOCK-03, DOCK-04, DOCK-05, DOCK-06, DOCK-07, DOCK-08, DOCK-09, DOCK-10 (10)

**Success Criteria:**
1. Agent can start/stop/restart containers with outcomes logged and verified
2. Agent can retrieve container logs with tail limits (max 10000 lines)
3. Agent can inspect container status without modifying state (read-only operation)
4. Agent can connect/disconnect containers from networks with dependency validation
5. Agent can execute commands in containers with output capture
6. All Docker actions execute asynchronously using run_in_executor pattern

### Phase 25: Host Actions

**Goal:** Agent can control systemd services and send signals to processes for host-level remediation.

**Dependencies:** Phase 23 (safety controls must be enhanced first)

**Requirements:** HOST-01, HOST-02, HOST-03, HOST-04, HOST-05, HOST-06, HOST-07 (7)

**Success Criteria:**
1. Agent can start/stop/restart systemd services with validation
2. Agent can send graceful SIGTERM to processes, escalating to SIGKILL after 5s if needed
3. Service name whitelist prevents operations on unauthorized services
4. PID validation prevents operations on PID 1 or kernel threads
5. All host actions use asyncio.create_subprocess_exec without shell=True (command injection prevented)

### Phase 26: Script Execution & Validation

**Goal:** Agent can generate Python/bash scripts, validated through multi-layer pipeline, executed in sandboxed containers, with output captured for iterative refinement.

**Dependencies:** Phase 24 (requires Docker executor for sandbox containers)

**Requirements:** SCRP-01, SCRP-02, SCRP-03, SCRP-04, SCRP-05, SCRP-06, SCRP-07, SCRP-08, SCRP-09, VALD-01, VALD-02, VALD-03, VALD-04, VALD-05, VALD-06 (15)

**Success Criteria:**
1. Agent-generated Python scripts validated with ast.parse() before execution
2. Agent-generated bash scripts validated with bash -n before execution
3. Scripts scanned for secrets (API_KEY=, password=, token= patterns) and dangerous commands (eval, exec, os.system)
4. Scripts execute in isolated containers with no network access, 512MB RAM limit, 1 CPU limit, 100 PID limit
5. Scripts run as non-root user (nobody) with read-only root filesystem
6. Script output (stdout/stderr) and exit code captured and returned to agent
7. Scripts automatically timeout after 60s with forced cleanup
8. Validation failures block execution with descriptive errors

### Phase 27: Risk Classification

**Goal:** Actions classified by risk level (LOW/MEDIUM/HIGH/CRITICAL) with approval mode configurable per level.

**Dependencies:** Phases 24, 25, 26 (requires all action types defined)

**Requirements:** RISK-01, RISK-02, RISK-03, RISK-04, RISK-05, RISK-06 (6)

**Success Criteria:**
1. docker_inspect and docker_logs classified as LOW risk
2. docker_start, docker_restart, host_service_* classified as MEDIUM risk
3. docker_stop, docker_network_*, host_kill_process classified as HIGH risk
4. execute_script classified as CRITICAL risk
5. Approval mode per risk level configurable (AUTO/REQUIRE/DENY)
6. User can configure system to auto-approve LOW, require approval for MEDIUM/HIGH, deny CRITICAL

### Phase 28: Agent Integration

**Goal:** Agent can propose script generation, receive execution results, and iterate on failures based on output.

**Dependencies:** Phase 26 (requires script execution capability)

**Requirements:** AGNT-01, AGNT-02, AGNT-03, AGNT-04 (4)

**Success Criteria:**
1. Agent proposes execute_script with script_content parameter in diagnosis flow
2. Script execution result (output, exit code, timeout flag) returned to agent
3. Agent iterates on failed scripts based on stderr output and exit code
4. Agent prompt includes guidance on when to use scripts vs direct Docker/host actions
5. End-to-end flow validated: diagnosis -> generate script -> validate -> execute -> analyze result -> refine

### Phase 29: Demo Scenarios

**Goal:** Infrastructure actions validated through realistic demo scenarios showing container recovery and config repair.

**Dependencies:** Phases 24, 26, 28 (requires Docker actions, script execution, and agent integration)

**Requirements:** DEMO-01, DEMO-02 (2)

**Success Criteria:**
1. TiKV container recovery demo: crash detected -> docker_restart_container -> health verified
2. Config repair demo: misconfiguration detected -> execute_script (inspect + fix) -> resolution verified
3. Demo narratives updated to describe infrastructure action flows
4. Both demos executable via ./scripts/run-demo.sh with EXECUTE mode

## Archived Milestones

<details>
<summary>v1.0 MVP (Phases 1-6) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.0-ROADMAP.md

**Summary:** 6 phases, 22 plans total. Delivered end-to-end chaos demo with fault injection, live detection, and AI diagnosis.

</details>

<details>
<summary>v1.1 TUI Demo (Phases 7-11) - SHIPPED 2026-01-25</summary>

Archived in milestones/v1.1-ROADMAP.md

**Summary:** 5 phases, 9 plans total. Rich-based live dashboard with real daemon output, cluster health visualization, and key-press driven demo chapters.

</details>

<details>
<summary>v2.0 Agent Actions (Phases 12-15) - SHIPPED 2026-01-26</summary>

Archived in milestones/v2.0-ROADMAP.md

**Summary:** 4 phases, 12 plans total. Action execution framework with safety controls, approval workflows, TiKV actions, workflow chaining, scheduled execution, and retry logic.

</details>

<details>
<summary>v2.1 Multi-Subject Support (Phases 16-20) - SHIPPED 2026-01-27</summary>

Archived in milestones/v2.1-ROADMAP.md

**Summary:** 5 phases, 21 plans total. Protocol-based abstractions, custom rate limiter service, operator-ratelimiter package, multi-subject CLI, unified demo framework. AI diagnoses rate limiter anomalies without system-specific prompts.

</details>

<details>
<summary>v2.2 Agentic Remediations Demo (Phases 21-22) - SHIPPED 2026-01-27</summary>

Archived in milestones/v2.2-ROADMAP.md

**Summary:** 2 phases, 3 plans total. Complete agentic loop (detect → diagnose → act → verify), parameter inference fallback, EXECUTE mode configuration, demo narratives updated for remediation flow.

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7-11 | v1.1 | 9/9 | Complete | 2026-01-25 |
| 12-15 | v2.0 | 12/12 | Complete | 2026-01-26 |
| 16-20 | v2.1 | 21/21 | Complete | 2026-01-27 |
| 21-22 | v2.2 | 3/3 | Complete | 2026-01-27 |
| 23 | v2.3 | 0/? | Pending | — |
| 24 | v2.3 | 0/? | Pending | — |
| 25 | v2.3 | 0/? | Pending | — |
| 26 | v2.3 | 0/? | Pending | — |
| 27 | v2.3 | 0/? | Pending | — |
| 28 | v2.3 | 0/? | Pending | — |
| 29 | v2.3 | 0/? | Pending | — |

---
*Roadmap created: 2026-01-25*
*v1.0 archived: 2026-01-25*
*v1.1 archived: 2026-01-25*
*v2.0 archived: 2026-01-26*
*v2.1 archived: 2026-01-27*
*v2.2 archived: 2026-01-27*
*v2.3 phases added: 2026-01-27*
