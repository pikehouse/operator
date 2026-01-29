# Project Milestones: Operator

## v3.1 Demo Update (Shipped: 2026-01-29)

**Delivered:** Fixed TUI demo to work with v3.0 agent_lab architecture. Both TiKV and ratelimiter demos run end-to-end with autonomous agent diagnosis and remediation.

**Phases completed:** 33-34 (5 plans total)

**Key accomplishments:**
- TicketOpsDB context manager with automatic schema initialization (no more "no such table" errors)
- Agent subprocess graceful SIGTERM shutdown (marks session escalated, cleans up)
- Ratelimiter demo counter persistence (heartbeat keeps counters alive, read-only get_counter)
- Compact workload panel with over-limit counters sorted first
- Demo management scripts (rebuild, reset-state commands)

**Stats:**
- 2 phases, 5 plans
- 11 requirements shipped
- 2 days from start to ship

**Git range:** Phase 33 commits → `5824cd0` (docs(34): mark phase complete)

**What's next:** Additional subjects, production approval layer, or v3.2 enhancements

---

## v3.0 Operator Laboratory (Shipped: 2026-01-28)

**Delivered:** Autonomous AI operator with full shell access, safety via container isolation, and complete audit trail. Claude autonomously diagnoses and fixes TiKV failures without predefined playbooks.

**Phases completed:** 30-32 (7 plans total)

**Key accomplishments:**
- Agent container with Python 3.12, Docker CLI, and standard SRE tools
- shell(command, reasoning) tool with 120s timeout — execute any command
- Core agent loop (198 lines) using tool_runner with @beta_tool decorator
- Database audit logging with reasoning, tool_call, and tool_result entries
- Haiku summarization for concise audit trail
- Docker Compose integration with TiKV network and Docker socket access
- CLI audit commands (operator audit list/show) for session review
- End-to-end validated: Claude diagnosed and fixed TiKV failure autonomously

**Stats:**
- 36 files modified
- ~4,600 lines added
- 3 phases, 7 plans
- 35 commits
- 4 days from v2.3 pivot to ship

**Git range:** `98aaaa7` (feat(30-01): create agent container) → `3e40f0b` (docs(phase-32): complete integration)

**Philosophy:** "Give Claude a full kitchen, not a menu of 10 dishes." Safety via container isolation, not action restrictions. Audit everything, approve nothing.

**What's next:** Additional subject integrations, production approval layer, or v3.1 enhancements

---

## v2.2 Agentic Remediations Demo (Shipped: 2026-01-27)

**Delivered:** Complete agentic loop in both demos — fault injection leads to AI detection, diagnosis, auto-execute remediation action, and verification that the fix resolved the issue.

**Phases completed:** 21-22 (3 plans total)

**Key accomplishments:**
- Complete agentic loop: diagnose → propose → validate → execute → verify
- Parameter inference when Claude returns empty params (TiKV drain_store, rate limiter reset_counter)
- EXECUTE mode environment configuration for demos
- Updated demo narratives for agentic remediation flow
- Prompt biased toward immediate action for demo responsiveness

**Stats:**
- 8 files modified
- ~400 lines added
- 2 phases, 3 plans
- 25 commits
- 1 day from v2.1 to ship

**Git range:** `23e3d72` (fix(21): revise plan) → `2a06043` (fix(agent): bias prompt toward immediate action)

**What's next:** Additional subjects, production hardening, or v2.3 with extended verification

---

## v2.1 Multi-Subject Support (Shipped: 2026-01-27)

**Delivered:** Protocol-based abstractions enabling any Subject to be monitored by the same operator-core. Second subject (custom distributed rate limiter) proves the AI can diagnose novel systems without system-specific prompts.

**Phases completed:** 16-20 (21 plans total)

**Key accomplishments:**
- Protocol-based abstractions (SubjectProtocol, InvariantCheckerProtocol) in zero-dependency operator-protocols package
- Custom rate limiter service (3+ nodes, Redis backend, atomic Lua scripts, Prometheus metrics)
- operator-ratelimiter package with 5 invariant types (node_down, redis_disconnected, high_latency, counter_drift, ghost_allowing)
- Multi-subject CLI with --subject flag for selecting tikv or ratelimiter
- Unified demo framework with same TUI layout for both subjects
- AI diagnosis quality validated: Claude reasons about rate limiter anomalies without rate-limiter-specific prompts in operator-core

**Stats:**
- 146 files changed
- ~18,000 lines added (net)
- 5 phases, 21 plans
- 87 commits
- 2 days from start to ship

**Git range:** `bb2b7a9` (feat(16-01)) → `4711c78` (chore: remove debug prints)

**What's next:** Additional subjects, production hardening, or extended actions

---

## v2.0 Agent Actions (Shipped: 2026-01-26)

**Delivered:** Action execution framework enabling the AI agent to execute recommendations via PD API with safety controls, approval workflows, and workflow chaining.

**Phases completed:** 12-15 (12 plans total)

**Key accomplishments:**
- Action execution framework with typed parameters, validation, and 6-state lifecycle
- TiKV subject actions: transfer-leader, transfer-peer, drain-store via PD API
- Safety infrastructure: kill switch, observe-only mode, audit logging
- Configurable approval workflow with CLI approve/reject commands
- Workflow chaining for multi-action sequences
- Scheduled action execution and retry with exponential backoff

**Stats:**
- 52 files created/modified
- ~10,900 lines added
- 4 phases, 12 plans
- 3 days from start to ship

**Git range:** `feat(12-01)` → `docs(15)` (complete workflow-actions phase)

**What's next:** v2.1 with dry-run mode, risk-tiered approvals, and extended TiKV actions

---

## v1.1 TUI Demo (Shipped: 2026-01-25)

**Delivered:** Rich-based live dashboard demo with real daemon output, cluster health visualization, workload sparklines, and key-press driven demo chapters.

**Phases completed:** 7-11 (9 plans total)

**Key accomplishments:**
- Multi-panel TUI layout with 5 synchronized panels (cluster, monitor, agent, workload, narration)
- Real subprocess management — monitor and agent run as actual daemons with live output streaming
- Color-coded cluster health display with detection highlighting (green/red indicators)
- Workload sparkline visualization that turns red during degradation
- Key-press demo flow with 7 chapters and countdown-based fault injection

**Stats:**
- ~8,000 lines added across 37 files
- 5 phases, 9 plans
- 1 day from start to ship

**Git range:** `5e2588f` (docs(phase-7): complete TUI Foundation phase) → `7f37738` (docs(phase-11): complete Fault Workflow Integration phase)

**What's next:** v2.0 with agent action execution (currently observe-only)

---

## v1.0 MVP (Shipped: 2026-01-25)

**Delivered:** AI-powered distributed systems operator that monitors TiKV clusters, diagnoses issues with Claude, and demonstrates diagnostic reasoning through an end-to-end chaos demo.

**Phases completed:** 1-6 (22 plans total)

**Key accomplishments:**
- Service-agnostic operator core with Subject adapter pattern and deployment abstraction
- TiKV subject implementation with PD API client, Prometheus metrics, and invariant checking
- Fully containerized test environment (6-node TiKV/PD cluster, Prometheus, Grafana, load generator)
- SQLite-backed ticket system with automated monitor loop and violation deduplication
- AI diagnosis with Claude producing SRE-quality reasoning (root cause, alternatives considered, recommendations)
- End-to-end chaos demo with fault injection, live detection, and diagnostic reasoning display

**Stats:**
- 6,223 lines of Python across 2 packages
- 6 phases, 22 plans
- 99 commits
- 1 day from start to ship

**Git range:** `90b6641` (docs: initialize project) → `ec4aa1b` (docs(06): complete chaos-demo phase)

**What's next:** v1.1 enhancements (additional chaos scenarios, action execution, multi-subject support)

---
