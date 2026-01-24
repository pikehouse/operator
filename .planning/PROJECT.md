# Operator

## What This Is

An AI-powered operator for distributed systems. It monitors multi-node clusters, diagnoses issues, and either takes corrective action or creates tickets with detailed reasoning for human review. The core is service-agnostic; TiKV is the first "subject" (the system being operated). Built to test whether AI can genuinely reason about distributed systems in production scenarios, and to create a compelling demo for technical audiences.

## Core Value

AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Service-agnostic operator core with subject adapter pattern
- [ ] TiKV subject: adapter for PD API, Prometheus metrics, log parsing
- [ ] Docker Compose local cluster: 3 TiKV nodes, 3 PD nodes, Prometheus, Grafana
- [ ] Monitor: checks cluster invariants, detects anomalies
- [ ] AI diagnosis: analyzes violations, creates tickets with structured reasoning
- [ ] Chaos injection toolkit: fault injection for demo scenarios
- [ ] Structured decision logs: observation → diagnosis → options → decision → rationale

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

### Demo Scenarios (Inform Requirements)

1. **Hot region**: Traffic concentrates on one key range → detect → split or transfer leader
2. **Node death**: Store goes offline → observe recovery → intervene or wait
3. **Disk pressure**: Uneven data distribution → migrate regions proactively
4. **Ambiguous slowness**: Subtle latency issues → correlate metrics → diagnose root cause

These test different cognitive skills: reactive optimization, judgment about intervention, proactive migration, diagnostic reasoning under uncertainty.

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
- **First milestone**: Observe-only — diagnosis and tickets, no automated actions yet
- **Target audience**: Technical — engineers, conference talks, technical blogs

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clean subject separation | Enables future subjects (Kafka, etc.) without rewriting core | — Pending |
| Docker Compose over tiup playground | Full control over chaos injection, reproducible | — Pending |
| Observe-only first | Get perception/diagnosis right before action; safer iteration | — Pending |
| Python | Anthropic SDK, matches prior art, fast iteration | — Pending |

---
*Last updated: 2026-01-24 after initialization*
