# Operator

Autonomous observe-detect-fix loop for distributed systems, evaluated via chaos engineering campaigns.

Read the blog post: [Building an Autonomous Database Operator with Claude](https://pike-house.com/remarks/claude-shard-database)

## How It Works

<p align="center">
  <img src="docs/diagrams/operator-loop.svg" alt="Operator loop: observe, detect violations, create tickets, agent fixes" width="700">
</p>

A **monitor** observes a subject (any distributed system) on a schedule. An **invariant checker** detects violations — node down, high latency, pool exhaustion, missing index. Violations create **tickets**. An **agent** (Claude with shell access) reads tickets, diagnoses the problem, and fixes it.

The operator is subject-agnostic. Adding a new subject means implementing two methods: `observe()` returns system state, `check()` returns violations. Everything else — monitoring, ticketing, agent reasoning — works automatically.

## Evaluation

<p align="center">
  <img src="docs/diagrams/eval-trial.svg" alt="Trial lifecycle: reset, inject chaos, detect, resolve, score" width="700">
</p>

**Campaigns** run structured trials against subjects. Each trial resets the subject, injects chaos, and measures how quickly the operator detects and resolves the problem. Campaigns produce metrics like time-to-detect, time-to-resolve, and win rate.

See [`eval/README.md`](eval/README.md) for the full eval reference.

## Subjects

| Subject | Category | What the operator monitors |
|---------|----------|---------------------------|
| **TiKV** | Operations | Distributed KV store — node health, region balance, latency, leader distribution |
| **Chat-DB-App** | Coding | FastAPI + PostgreSQL — connection pool, query performance, schema, race conditions |
| **Chat-DB-App-Shard** | Coding | Sharded variant — horizontal scaling, fanout queries, blob storage, online migration |
| **Rate Limiter** | Operations | Token bucket service — Redis health, rate accuracy |

## Project Structure

```
packages/
├── operator-core/          # Monitor loop, agent, CLI, ticket DB
└── operator-protocols/     # SubjectProtocol, InvariantCheckerProtocol (zero deps)

subjects/
├── tikv/                   # TiKV subject (Docker Compose cluster)
├── chat-db-app/            # Chat DB App subject (FastAPI + PostgreSQL)
└── ratelimiter/            # Rate limiter subject

eval/                       # Chaos engineering eval framework
├── campaigns/              # Campaign YAML configs
├── variants/               # Agent configuration variants
└── src/eval/               # Runner, analysis, subjects, viewer

demo/                       # Interactive TUI demo
scripts/                    # Helper scripts
```

## Quick Start

```bash
# Install dependencies
uv sync

# Set API key
export ANTHROPIC_API_KEY=your_key

# Run the TiKV demo (interactive TUI)
./scripts/run-demo.sh tikv

# Run an eval smoke test
cd eval
uv run eval run campaign campaigns/smoke-tests/tikv-smoke.yaml
```

### Requirements

- Docker and Docker Compose
- Python 3.12+
- `uv` package manager
- `ANTHROPIC_API_KEY` in environment
