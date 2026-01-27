# Project Milestones: Operator

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
