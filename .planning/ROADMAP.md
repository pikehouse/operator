# Roadmap: Operator

## Milestones

- [x] **v1.0 MVP** - Phases 1-6 (shipped 2026-01-25)
- [x] **v1.1 TUI Demo** - Phases 7-11 (shipped 2026-01-25)
- [x] **v2.0 Agent Actions** - Phases 12-15 (shipped 2026-01-26)
- [x] **v2.1 Multi-Subject Support** - Phases 16-20 (shipped 2026-01-27)
- [x] **v2.2 Agentic Remediations Demo** - Phases 21-22 (shipped 2026-01-27)
- [ ] **v2.3 Infrastructure Actions & Script Execution** - Phases 23-26 (archived incomplete)
- [ ] **v3.0 Operator Laboratory** - Phases 30-32 (in progress)

## v3.0 Operator Laboratory

**Goal:** Give Claude autonomy and a well-equipped environment rather than constraining it to predefined actions. Safety via isolation (Docker container), not restrictions. Audit everything, approve nothing.

**Philosophy:** The difference between giving someone a menu of 10 dishes vs giving them a full kitchen. We want the kitchen.

**Phases:** 3
**Requirements:** Defined inline (simple milestone)

### Phase 30: Core Agent ✓

**Goal:** Agent container with shell tool and audit logging.

**Deliverables:**
- Agent container Dockerfile (Python 3.12, Docker CLI, curl, jq, standard Unix tools)
- `shell(command, reasoning)` — execute any command, log with reasoning
- Audit log format (JSON, per-session)

**Note:** Scope narrowed from original — no web_search or web_fetch tools. Claude uses curl directly.

**Plans:** 1 plan (1/1 complete)

Plans:
- [x] 30-01-PLAN.md — Agent Dockerfile, shell() tool, SessionAuditor

**Success Criteria:**
1. ✓ Agent container builds and runs with Docker socket access
2. ✓ shell() tool logs to audit format before and after execution
3. ✓ shell() can execute arbitrary commands with 120s timeout
4. ✓ SessionAuditor saves complete conversation history to JSON

**Completed:** 2026-01-28

### Phase 31: Agent Loop ✓

**Goal:** The ~200 line core loop that runs Claude.

**Deliverables:**
- Database polling for tickets (1-second interval)
- Claude conversation loop with tool_runner
- Haiku summarization of reasoning and tool outputs
- Database audit logging (not JSON files)
- System prompt for SRE agent

**Plans:** 2 plans (2/2 complete)

Plans:
- [x] 31-01-PLAN.md — Core agent loop with tool_runner, database polling, Haiku summarization
- [x] 31-02-PLAN.md — Tool call/result audit logging (gap closure)

**Success Criteria:**
1. ✓ Agent polls database for open tickets every 1 second
2. ✓ Claude receives ticket and can call shell tool
3. ✓ Tool results summarized by Haiku before logging
4. ✓ Complete audit trail stored in database
5. ✓ Core loop is < 200 lines (198 lines)

**Completed:** 2026-01-28

### Phase 32: Integration & Demo

**Goal:** End-to-end validation against real subjects.

**Deliverables:**
- Docker Compose with agent container alongside subjects
- Agent can reach Prometheus, subjects, internet
- TiKV failure scenario validated
- Audit log review tooling

**Success Criteria:**
1. Agent container runs alongside TiKV cluster in Docker Compose
2. Claude autonomously diagnoses TiKV failure (no predefined playbook)
3. Claude fixes issue using shell commands (docker restart, etc.)
4. Complete audit log shows reasoning chain
5. Environment recoverable via docker-compose down/up

---

## v2.3 Infrastructure Actions & Script Execution (Archived)

**Status:** Archived incomplete — superseded by v3.0 Operator Laboratory

**Reason:** Pivot to simpler philosophy. v2.3 built elaborate action framework with executors, approval workflows, and risk classification. v3.0 replaces this with "give Claude a shell and let it figure things out."

**Completed phases (23-26) remain in codebase but are not used by v3.0.**

**Goal:** The action agent can remediate issues by controlling Docker infrastructure, modifying host processes, and generating/executing custom scripts in sandboxed containers — with output fed back for iterative reasoning.

**Phases:** 7 (4 complete, 3 superseded)
**Requirements:** 52 total
**Coverage:** 52/52 mapped (100%)

### Phase 23: Safety Enhancement ✓

**Goal:** Existing safety controls enhanced to handle TOCTOU races, agent identity confusion, and multi-step attack chains before infrastructure actions are enabled.

**Dependencies:** None (foundation for all infrastructure capabilities)

**Requirements:** SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05, SAFE-06, SAFE-07, SAFE-08 (8)

**Plans:** 4 plans (4/4 complete)

Plans:
- [x] 23-01-PLAN.md — Identity & dual authorization foundation (requester_id, agent_id fields)
- [x] 23-02-PLAN.md — Secret redaction in audit logs (detect-secrets integration)
- [x] 23-03-PLAN.md — TOCTOU-resistant approval workflow with token expiration
- [x] 23-04-PLAN.md — Session risk tracking & enhanced kill switch

**Success Criteria:**
1. ✓ User approves action, system state changes, approval workflow detects mismatch and blocks execution (TOCTOU resistance verified)
2. ✓ Audit logs show both requester identity and agent identity for all actions
3. ✓ Approval tokens expire after 60 seconds, preventing stale approvals
4. ✓ Session-level cumulative risk tracking identifies suspicious multi-action patterns
5. ✓ Kill switch force-terminates in-flight Docker operations (not just pending actions)

**Completed:** 2026-01-28

### Phase 24: Docker Actions ✓

**Goal:** Agent can control Docker container lifecycle, access logs, and manage network connections for remediation scenarios.

**Dependencies:** Phase 23 (safety controls must be enhanced first)

**Requirements:** DOCK-01, DOCK-02, DOCK-03, DOCK-04, DOCK-05, DOCK-06, DOCK-07, DOCK-08, DOCK-09, DOCK-10 (10)

**Plans:** 3 plans (3/3 complete)

Plans:
- [x] 24-01-PLAN.md — DockerActionExecutor with container lifecycle (start/stop/restart/inspect)
- [x] 24-02-PLAN.md — Logs, network, and exec operations
- [x] 24-03-PLAN.md — Tool registration and framework integration

**Success Criteria:**
1. ✓ Agent can start/stop/restart containers with outcomes logged and verified
2. ✓ Agent can retrieve container logs with tail limits (max 10000 lines)
3. ✓ Agent can inspect container status without modifying state (read-only operation)
4. ✓ Agent can connect/disconnect containers from networks with dependency validation
5. ✓ Agent can execute commands in containers with output capture
6. ✓ All Docker actions execute asynchronously using run_in_executor pattern

**Completed:** 2026-01-28

### Phase 25: Host Actions ✓

**Goal:** Agent can control systemd services and send signals to processes for host-level remediation.

**Dependencies:** Phase 23 (safety controls must be enhanced first)

**Requirements:** HOST-01, HOST-02, HOST-03, HOST-04, HOST-05, HOST-06, HOST-07 (7)

**Plans:** 3 plans (3/3 complete)

Plans:
- [x] 25-01-PLAN.md — HostActionExecutor with systemd service methods and ServiceWhitelist validation
- [x] 25-02-PLAN.md — Process kill with graceful SIGTERM -> SIGKILL escalation and PID validation
- [x] 25-03-PLAN.md — Tool registration and framework integration

**Success Criteria:**
1. ✓ Agent can start/stop/restart systemd services with validation
2. ✓ Agent can send graceful SIGTERM to processes, escalating to SIGKILL after 5s if needed
3. ✓ Service name whitelist prevents operations on unauthorized services
4. ✓ PID validation prevents operations on PID 1 or kernel threads
5. ✓ All host actions use asyncio.create_subprocess_exec without shell=True (command injection prevented)

**Completed:** 2026-01-28

### Phase 26: Script Execution & Validation ✓

**Goal:** Agent can generate Python/bash scripts, validated through multi-layer pipeline, executed in sandboxed containers, with output captured for iterative refinement.

**Dependencies:** Phase 24 (requires Docker executor for sandbox containers)

**Requirements:** SCRP-01, SCRP-02, SCRP-03, SCRP-04, SCRP-05, SCRP-06, SCRP-07, SCRP-08, SCRP-09, VALD-01, VALD-02, VALD-03, VALD-04, VALD-05, VALD-06 (15)

**Plans:** 3 plans (3/3 complete)

Plans:
- [x] 26-01-PLAN.md — Script validation module with patterns and ScriptValidator
- [x] 26-02-PLAN.md — ScriptExecutor with sandbox Docker execution
- [x] 26-03-PLAN.md — Tool registration and framework integration

**Success Criteria:**
1. ✓ Agent-generated Python scripts validated with ast.parse() before execution
2. ✓ Agent-generated bash scripts validated with bash -n before execution
3. ✓ Scripts scanned for secrets (API_KEY=, password=, token= patterns) and dangerous commands (eval, exec, os.system)
4. ✓ Scripts execute in isolated containers with no network access, 512MB RAM limit, 1 CPU limit, 100 PID limit
5. ✓ Scripts run as non-root user (nobody) with read-only root filesystem
6. ✓ Script output (stdout/stderr) and exit code captured and returned to agent
7. ✓ Scripts automatically timeout after 60s with forced cleanup
8. ✓ Validation failures block execution with descriptive errors

**Completed:** 2026-01-28

### Phase 27-29: Superseded

**Status:** Not implemented — superseded by v3.0

Phases 27 (Risk Classification), 28 (Agent Integration), and 29 (Demo Scenarios) were planned but never started. The v3.0 pivot renders them unnecessary:

- Risk classification → v3.0 has no approval workflow
- Agent integration → v3.0 uses direct Claude tool calling
- Demo scenarios → v3.0 Phase 32 covers end-to-end validation

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

**Summary:** 2 phases, 3 plans total. Complete agentic loop (detect -> diagnose -> act -> verify), parameter inference fallback, EXECUTE mode configuration, demo narratives updated for remediation flow.

</details>

<details>
<summary>v2.3 Infrastructure Actions (Phases 23-26) - ARCHIVED INCOMPLETE 2026-01-28</summary>

Archived in milestones/v2.3-ROADMAP.md

**Summary:** 4 of 7 phases complete, 13 plans total. Built DockerActionExecutor, HostActionExecutor, ScriptExecutor with safety controls, approval workflows, and sandboxed execution. Phases 27-29 (Risk Classification, Agent Integration, Demo Scenarios) superseded by v3.0 pivot.

**Reason for archive:** Philosophy pivot. v3.0 "Operator Laboratory" replaces the action framework approach with "give Claude a shell and let it figure things out."

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 | 22/22 | Complete | 2026-01-25 |
| 7-11 | v1.1 | 9/9 | Complete | 2026-01-25 |
| 12-15 | v2.0 | 12/12 | Complete | 2026-01-26 |
| 16-20 | v2.1 | 21/21 | Complete | 2026-01-27 |
| 21-22 | v2.2 | 3/3 | Complete | 2026-01-27 |
| 23-26 | v2.3 | 13/13 | Archived | 2026-01-28 |
| 27-29 | v2.3 | — | Superseded | — |
| 30 | v3.0 | 1/1 | Complete | 2026-01-28 |
| 31 | v3.0 | 2/2 | Complete | 2026-01-28 |
| 32 | v3.0 | 0/? | Pending | — |

---
*Roadmap created: 2026-01-25*
*v1.0 archived: 2026-01-25*
*v1.1 archived: 2026-01-25*
*v2.0 archived: 2026-01-26*
*v2.1 archived: 2026-01-27*
*v2.2 archived: 2026-01-27*
*v2.3 archived incomplete: 2026-01-28*
*v3.0 created: 2026-01-28*
