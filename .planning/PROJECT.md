# Operator

## What This Is

An AI-powered operator for distributed systems that monitors clusters, diagnoses issues with Claude, and autonomously executes remediation actions. v3.0 pivoted to "Operator Laboratory" — give Claude a full shell and let it figure things out, with safety via container isolation rather than action restrictions.

## Core Value

AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one." And now: autonomous action without predefined playbooks.

## Current State

**Shipped:** v3.1 (2026-01-29)
**Code:** ~21,500 lines Python across 5 packages (operator-core, operator-protocols, operator-tikv, operator-ratelimiter, ratelimiter-service)
**Tech stack:** Python, Typer CLI, SQLite, Claude API, Docker Compose, TiKV/PD, Redis, FastAPI, Rich TUI, Pydantic

### What Works

- `./scripts/run-demo.sh tikv` — TiKV demo with autonomous agent diagnosis and remediation
- `operator monitor run --subject tikv|ratelimiter` — Continuous invariant checking
- `operator audit list/show` — Review agent sessions and conversation logs
- Agent container with Docker socket access for controlling sibling containers
- 6-node TiKV/PD cluster with Prometheus + Grafana in Docker
- 3-node rate limiter cluster with Redis and Prometheus in Docker

### v3.0 Capabilities

- **Autonomous Shell Access**: Claude has full shell() tool — execute any command
- **Container Isolation**: Safety via Docker, not action restrictions
- **Audit Everything**: Complete reasoning chain with tool calls and results
- **Haiku Summarization**: Concise audit logs via claude-haiku
- **198-line Core Loop**: Simple polling, tool_runner, ticket updates
- **CLI Audit Review**: operator audit list/show for session inspection

### v2.x Capabilities (Retained)

- **Protocol-based Abstractions**: SubjectProtocol and InvariantCheckerProtocol
- **Multi-Subject Support**: TiKV and custom rate limiter
- **TUI Demo**: Rich-based live dashboard with real subprocess management

## Requirements

### Validated

**v1.0:**
- Subject adapter interface — v1.0 (Protocol-based, runtime_checkable)
- TiKV subject: PD API, Prometheus metrics, log parsing — v1.0
- Docker Compose local cluster: 3 TiKV nodes, 3 PD nodes — v1.0
- Containerized observability: Prometheus + Grafana — v1.0
- Monitor loop: checks cluster invariants, detects anomalies — v1.0
- AI diagnosis: structured reasoning with alternatives considered — v1.0
- Chaos injection: node kill via Docker — v1.0

**v1.1:**
- TUI-based demo with live multi-panel dashboard — v1.1
- Real monitor and agent daemons running as subprocesses — v1.1
- Cluster status panel showing node health with color indicators — v1.1
- Workload panel with ops/sec sparkline — v1.1
- Key-press driven demo chapters with countdown fault injection — v1.1

**v2.0:**
- Action framework with multiple sources (subject, tools, workflows) — v2.0
- Subject-defined actions (TiKV transfer-leader, transfer-peer, drain-store) — v2.0
- General tools beyond subject actions (wait, log_message) — v2.0
- Action proposal from diagnosis — v2.0
- Parameter validation before execution — v2.0
- Action result tracking — v2.0
- Audit logging for all actions — v2.0
- Kill switch for pending/in-progress actions — v2.0
- Observe-only mode — v2.0
- Configurable approval workflow — v2.0
- CLI approve/reject commands — v2.0
- Workflow chaining — v2.0
- Scheduled action execution — v2.0
- Retry with exponential backoff — v2.0

**v2.1:**
- Protocol-based abstractions (SubjectProtocol, InvariantCheckerProtocol) — v2.1
- Zero-dependency operator-protocols package — v2.1
- Custom distributed rate limiter (3+ nodes, Redis backend) — v2.1
- Docker Compose environment for rate limiter cluster — v2.1
- operator-ratelimiter package implementing Subject Protocol — v2.1
- 5 rate limiter invariants (node_down, redis_disconnected, high_latency, counter_drift, ghost_allowing) — v2.1
- Rate limiter actions (reset_counter, update_limit) — v2.1
- Multi-subject CLI with --subject flag — v2.1
- Unified demo framework for both subjects — v2.1
- AI diagnosis for out-of-distribution system (validated) — v2.1

**v2.2:**
- Complete agentic loop (detect → diagnose → act → verify) — v2.2
- Agent executes actions immediately after diagnosis — v2.2
- Agent verifies fix after 5s delay — v2.2
- EXECUTE mode for autonomous demo execution — v2.2
- Parameter inference fallback for TiKV/rate limiter actions — v2.2
- Updated demo narratives for agentic flow — v2.2

**v3.0:**
- Agent container with Python 3.12, Docker CLI, SRE tools — v3.0
- shell(command, reasoning) tool with 120s timeout — v3.0
- Core agent loop (198 lines) with tool_runner — v3.0
- Database audit logging with reasoning, tool_call, tool_result entries — v3.0
- Haiku summarization for concise audit trail — v3.0
- Docker Compose integration with TiKV network — v3.0
- Docker socket access for sibling container control — v3.0
- CLI audit commands (operator audit list/show) — v3.0
- Autonomous diagnosis and remediation (no playbook) — v3.0

**v3.1:**
- TUI demo works with v3.0 agent_lab architecture — v3.1
- TicketOpsDB context manager with automatic schema initialization — v3.1
- Agent subprocess graceful SIGTERM shutdown — v3.1
- Both TiKV and ratelimiter demos functional end-to-end — v3.1
- Demo chapters flow correctly with new architecture — v3.1

### Active

**v3.2 Evaluation Harness:**
- Standalone eval/ harness for chaos experimentation
- Three-layer architecture: Runner → Analysis → Viewer
- Subject-agnostic (TiKV, rate limiter, future subjects)
- Post-hoc scoring and baseline comparison
- Config variants for testing different agent configurations

### Future

- Cloud API actions (AWS/GCP/Azure)
- Production approval layer (lab → prod: propose → approve → execute)
- Additional subject integrations (Kafka, Postgres)

### Out of Scope

- TiKV source code in this repo — we orchestrate, not fork
- Production AWS deployment — local simulation first
- Complex rate limiter features — intentionally simple to prove abstraction
- Web dashboard — CLI and logs

## Context

### v3.0 Philosophy Shift

> "Give Claude a full kitchen, not a menu of 10 dishes."

The v2.x approach built elaborate action frameworks with executors, approval workflows, and risk classification. v3.0 pivots to radical simplicity:

- **One tool**: shell(command, reasoning)
- **Safety via isolation**: Container boundary, not action restrictions
- **Audit everything**: Complete reasoning chain captured
- **Approve nothing**: Let Claude cook, review afterward

**What was eliminated:**
- ActionRegistry, action definitions, parameter validation
- DockerExecutor, HostExecutor, ScriptExecutor
- Approval workflows, risk classification
- Structured DiagnosisOutput schemas

**What was kept:**
- Audit logging (now database-based with Haiku summaries)
- Monitor/alerting (need to know something's wrong)
- Docker Compose environment (the lab itself)
- Prometheus (metrics Claude can query)

### Path to Production

Lab → Production: shell(cmd) → propose(cmd) → approve() → shell(cmd)

The audit layer carries forward unchanged. Production adds an approval gate before execution.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clean subject separation | Enables future subjects (Kafka, etc.) without rewriting core | Good — Protocol-based abstraction works cleanly |
| Docker Compose over tiup playground | Full control over chaos injection, reproducible | Good — Reliable 6-node cluster |
| Observe-only first (v1.0) | Get perception/diagnosis right before action | Good — AI diagnosis quality validated |
| Protocol-based abstractions | Subject and DeploymentTarget as Protocols | Good — Clean extensibility |
| Pydantic for structured outputs | Schema validation for Claude responses | Good — Reliable diagnosis format |
| v3.0 shell-only approach | Simpler than action framework, more flexible | Good — 198 lines vs ~10K lines |
| Haiku summarization | Keep audit logs concise and readable | Good — Database queries fast |
| Container isolation as safety | Simpler than approval workflows | Good — docker-compose down resets |
| Database audit over JSON files | Better queryability, CLI integration | Good — operator audit commands work |

---
*Last updated: 2026-01-29 after v3.1 milestone shipped*
