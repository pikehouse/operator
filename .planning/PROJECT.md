# Operator

## What This Is

An AI-powered operator for distributed systems that monitors TiKV clusters, diagnoses issues with Claude, and produces structured reasoning for human review. The core is service-agnostic with TiKV as the first subject. Shipped v1.0 with end-to-end chaos demo showing fault injection, live detection, and AI diagnosis.

## Core Value

AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

## Current State

**Shipped:** v1.0 (2026-01-25)
**Code:** 6,223 lines Python across 2 packages (operator-core, operator-tikv)
**Tech stack:** Python, Typer CLI, SQLite, Claude API, Docker Compose, TiKV/PD

### What Works

- `operator demo chaos` — Full E2E demo with fault injection and AI diagnosis
- `operator monitor run` — Continuous invariant checking with ticket creation
- `operator agent start` — AI diagnosis daemon processing tickets
- `operator tickets list/show/resolve/hold` — Ticket management CLI
- 6-node TiKV/PD cluster with Prometheus + Grafana in Docker
- go-ycsb load generator for traffic simulation

## Requirements

### Validated

- Subject adapter interface — v1.0 (Protocol-based, runtime_checkable)
- TiKV subject: PD API, Prometheus metrics, log parsing — v1.0
- Docker Compose local cluster: 3 TiKV nodes, 3 PD nodes — v1.0
- Containerized observability: Prometheus + Grafana — v1.0
- Monitor loop: checks cluster invariants, detects anomalies — v1.0
- AI diagnosis: structured reasoning with alternatives considered — v1.0
- Chaos injection: node kill via Docker — v1.0

### Active

- [ ] TUI-based demo with live multi-panel dashboard
- [ ] Real monitor and agent daemons running (not one-shot calls)
- [ ] Cluster status panel showing node health
- [ ] Workload panel with ops/sec histogram
- [ ] Key-press driven demo chapters (inject fault, recover)

## Current Milestone: v1.1 TUI Demo

**Goal:** Upgrade the demo to a Rich-based live dashboard showing the operator actually running.

**Target features:**
- Multi-panel TUI (cluster status, monitor, agent, workload, narration)
- Real daemons running as subprocesses with live output capture
- Workload histogram that turns red when degraded
- Key-press chapter progression (healthy → fault → diagnosis → recovery → exit)

### Out of Scope

- TiKV source code in this repo — we orchestrate, not fork
- Production AWS deployment in v1 — local simulation first
- Action execution in v1 — observe-only, tickets with recommendations
- Other subjects (Kafka, Postgres) — TiKV first, extract patterns later
- Web dashboard — CLI and logs for v1

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
| Python | Anthropic SDK, matches prior art, fast iteration | Good — 6K LOC in 1 day |
| Protocol-based abstractions | Subject and DeploymentTarget as Protocols | Good — Clean extensibility |
| aiosqlite for database | Non-blocking operations in async event loop | Good — No blocking issues |
| Pydantic for structured outputs | Schema validation for Claude responses | Good — Reliable diagnosis format |
| Active invariant checking in demo | Don't passively poll, actively check | Good — Detection within 2-4 seconds |

---
*Last updated: 2026-01-25 after starting v1.1 milestone*
