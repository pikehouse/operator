# Project State: Operator

## Current Position

**Phase:** 2 of 6 (TiKV Subject)
**Plan:** 4 of 5 in Phase 2
**Status:** In Progress
**Last activity:** 2026-01-24 - Completed 02-03-PLAN.md

**Progress:** [########________] ~50% (Phase 1 complete + 02-01 through 02-04)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-24)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one."

**Current focus:** Phase 2 - TiKV Subject

## Progress

| Phase | Status | Plans |
|-------|--------|-------|
| 1 - Foundation | ✓ Complete | 4/4 |
| 2 - TiKV Subject | In Progress | 4/5 |
| 3 - Local Cluster | Pending | 0/? |
| 4 - Monitor Loop | Pending | 0/? |
| 5 - AI Diagnosis | Pending | 0/? |
| 6 - Chaos Demo | Pending | 0/? |

## Session Continuity

**Last session:** 2026-01-24T21:07:41Z
**Stopped at:** Completed 02-03-PLAN.md
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

## Open Issues

*None*

---
*State updated: 2026-01-24T21:07:41Z*
