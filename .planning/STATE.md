# Project State: Operator

## Current Position

**Phase:** 5 of 6 (AI Diagnosis)
**Plan:** 1 of 4 in Phase 5
**Status:** In progress
**Last activity:** 2026-01-25 - Completed 05-01-PLAN.md

**Progress:** [#################] ~92% (Phase 1-4 complete, Phase 5 plan 1 complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

**Current focus:** Phase 5 - AI Diagnosis (data models complete)

## Progress

| Phase | Status | Plans |
|-------|--------|-------|
| 1 - Foundation | ✓ Complete | 4/4 |
| 2 - TiKV Subject | ✓ Complete | 5/5 |
| 3 - Local Cluster | ✓ Complete | 4/4 |
| 4 - Monitor Loop | ✓ Complete | 3/3 |
| 5 - AI Diagnosis | In progress | 1/4 |
| 6 - Chaos Demo | Pending | 0/? |

## Session Continuity

**Last session:** 2026-01-25T01:51:54Z
**Stopped at:** Completed 05-01-PLAN.md
**Resume file:** None

## Key Decisions

| Decision | Phase | Rationale |
|----------|-------|-----------|
| Use workspace source config for automatic package installation | 01-01 | Required for `uv sync` to install workspace packages without extra flags |
| No build-system at workspace root | 01-01 | Workspace root is coordinator only, not a buildable package |
| Protocol not runtime_checkable - static typing only | 01-03 | Clean interface for deployment abstraction |
| LocalDeployment lazy validates compose file | 01-03 | python-on-whales behavior - validates on operations |
| Use @dataclass for internal types, Pydantic for API/config | 01-02 | Internal types don't need validation overhead |
| All Subject methods async | 01-02 | Non-blocking I/O with httpx clients |
| Subject Protocol uses @runtime_checkable | 01-02 | Enables isinstance() checks for debugging |
| Subject defaults to 'tikv' in CLI commands | 01-04 | Per CONTEXT.md - tikv is primary subject |
| Stub docker-compose uses nginx:alpine placeholder | 01-04 | Phase 1 testing - real TiKV in Phase 3 |
| Pydantic for API response types, dataclass for internal types | 02-01 | External data needs validation, internal types don't |
| Helper methods on Prometheus response models | 02-01 | get_single_value() handles string-to-float conversion pattern |
| Naive datetime for log timestamps | 02-04 | Timezone handling deferred per RESEARCH.md Pitfall 5 |
| Skip log lines without region_id | 02-04 | Not useful for diagnosis context |
| PDClient receives injected httpx.AsyncClient | 02-02 | Per RESEARCH.md Pattern 1 - enables connection pooling |
| PrometheusClient uses address pattern escaping | 02-03 | Colon -> .* for flexible instance label matching |
| Latency converted from seconds to milliseconds | 02-03 | StoreMetrics uses ms per established convention |
| Store down has no grace period | 02-05 | Critical issue, immediate alerting needed |
| High latency has 60s grace period | 02-05 | Allows transient spikes without alerting |
| Actions raise NotImplementedError | 02-05 | Deferred to Phase 5 |
| Use multi-arch images instead of -arm64 variants | 03-01 | pingcap/*:v8.5.5 is multi-arch, -arm64 images outdated |
| Use curl for Docker healthchecks | 03-01 | Better handling of JSON and empty responses than wget |
| Prometheus waits for tikv0 healthy before starting | 03-02 | Ensures cluster ready before scraping |
| Grafana datasource provisioned via file mount | 03-02 | No manual setup required |
| Raw TiKV mode for YCSB | 03-03 | Simpler key-value operations without transaction overhead |
| Docker Compose profiles for ycsb | 03-03 | On-demand service doesn't start with default 'up' |
| Smaller workload config (10k records) | 03-03 | Suitable for local testing scenarios |
| Use uv for Python package management in container | 03-04 | Consistent with workspace tooling, fast installs |
| Profile-based operator activation | 03-04 | Service doesn't start by default, run with --profile operator |
| Environment variables for endpoints | 03-04 | PD_ENDPOINT and PROMETHEUS_URL configurable per deployment |
| Use aiosqlite for non-blocking SQLite operations | 04-01 | Per RESEARCH.md - ensures async event loop not blocked by DB |
| violation_key = invariant_name:store_id for deduplication | 04-01 | Consistent key format for ticket deduplication |
| asyncio.Event for shutdown coordination | 04-02 | Per RESEARCH.md - not busy polling, allows immediate signal response |
| TicketDB wraps entire daemon loop | 04-02 | Single connection open for duration, consistent state |
| Lazy import for MonitorLoop in monitor/__init__.py | 04-03 | Breaks circular import chain with db.tickets |
| Direct submodule imports in CLI | 04-03 | Avoid __init__.py triggers that cause circular imports |
| Field descriptions guide Claude structured output | 05-01 | Pydantic Field(description=...) serves dual purpose |
| Markdown as diagnosis storage format | 05-01 | Human-readable first per CONTEXT.md |
| Status transitions to 'diagnosed' when AI attaches analysis | 05-01 | Clear state machine for ticket lifecycle |

## Open Issues

*None*

---
*State updated: 2026-01-25T01:51:54Z*
