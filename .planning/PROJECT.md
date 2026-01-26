# Operator

## What This Is

An AI-powered operator for distributed systems that monitors TiKV clusters, diagnoses issues with Claude, and can now execute remediation actions via PD API. The core is service-agnostic with TiKV as the first subject. v2.0 adds action execution with safety controls, approval workflows, and workflow chaining.

## Core Value

AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one." And now: "here's what I recommend doing about it."

## Current State

**Shipped:** v2.0 (2026-01-26)
**Code:** ~12,200 lines Python across 2 packages (operator-core, operator-tikv)
**Tech stack:** Python, Typer CLI, SQLite, Claude API, Docker Compose, TiKV/PD, Rich TUI, Pydantic

### What Works

- `./scripts/run-tui.sh` — Rich TUI demo with live panels, key-press chapters, fault injection
- `operator demo chaos` — Full E2E demo with fault injection and AI diagnosis
- `operator monitor run` — Continuous invariant checking with ticket creation
- `operator agent start` — AI diagnosis daemon processing tickets (can propose actions)
- `operator tickets list/show/resolve/hold` — Ticket management CLI
- `operator actions list/show/approve/reject` — Action management CLI
- 6-node TiKV/PD cluster with Prometheus + Grafana in Docker
- go-ycsb load generator for traffic simulation

### v2.0 Capabilities

- **Action Framework**: Typed parameters, validation, 6-state lifecycle (proposed→validated→executing→completed/failed/cancelled)
- **TiKV Actions**: transfer-leader, transfer-peer, drain-store via PD API
- **Safety Controls**: Kill switch, observe-only mode, audit logging
- **Approval Workflow**: Configurable human approval gate (default: autonomous)
- **Workflow Chaining**: Multi-action sequences with dependencies
- **Scheduled Actions**: Execute at future time
- **Retry Logic**: Exponential backoff with jitter

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

### Active

*No active requirements — planning next milestone*

### Out of Scope

- TiKV source code in this repo — we orchestrate, not fork
- Production AWS deployment — local simulation first
- Other subjects (Kafka, Postgres) — TiKV first, extract patterns later
- Web dashboard — CLI and logs
- Free-form command execution — structured action types only

## Context

### Inspiration

Based on the service-harness-demo pattern:
- Monitor watches invariants, creates tickets on violations
- AI agent picks up tickets, diagnoses, takes action
- Structured logging of reasoning for transparency

The leap here is **single service → distributed system**. A rate limiter has one process. TiKV has nodes, regions, leaders, replication, Raft consensus. The reasoning is fundamentally more complex.

### TiKV Concepts

- **Store**: A TiKV node (physical server or container)
- **Region**: A contiguous key range, replicated across 3 stores
- **Leader**: The store that handles reads/writes for a region
- **PD (Placement Driver)**: Cluster brain — scheduling, metadata, load balancing
- **Raft**: Consensus protocol for region replication

### Evaluation Criteria (What "Good" Looks Like)

| Metric | Measures |
|--------|----------|
| Time to detect | How long after injection until AI notices |
| Diagnosis accuracy | Did it correctly identify root cause |
| Action appropriateness | Was the recommendation reasonable |
| Explanation quality | Could a human follow the reasoning |
| Action success rate | Did executed actions achieve intended outcome |

## Constraints

- **Language**: Python — matches harness-demo, good Anthropic SDK support
- **Local env**: Docker Compose — reproducible, scriptable chaos injection
- **Target audience**: Technical — engineers, conference talks, technical blogs

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clean subject separation | Enables future subjects (Kafka, etc.) without rewriting core | Good — Protocol-based abstraction works cleanly |
| Docker Compose over tiup playground | Full control over chaos injection, reproducible | Good — Reliable 6-node cluster |
| Observe-only first | Get perception/diagnosis right before action; safer iteration | Good — AI diagnosis quality validated |
| Python | Anthropic SDK, matches prior art, fast iteration | Good — 12K LOC in 3 milestones |
| Protocol-based abstractions | Subject and DeploymentTarget as Protocols | Good — Clean extensibility |
| aiosqlite for database | Non-blocking operations in async event loop | Good — No blocking issues |
| Pydantic for structured outputs | Schema validation for Claude responses and action types | Good — Reliable diagnosis and action format |
| Active invariant checking in demo | Don't passively poll, actively check | Good — Detection within 2-4 seconds |
| Safety-first action design | Kill switch, observe mode, approval gates | Good — Safe action execution |
| Fire-and-forget PD API calls | Return on success, don't poll for completion | Good — Simple, PD handles async |
| Exponential backoff with jitter | Prevent thundering herd on retries | Good — Robust retry behavior |

---
*Last updated: 2026-01-26 after completing v2.0 milestone*
