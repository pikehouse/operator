---
phase: 19-operator-ratelimiter
plan: 01
subsystem: observability
tags: [httpx, redis, prometheus, pydantic, rate-limiting]

# Dependency graph
requires:
  - phase: 16-core-abstraction-refactoring
    provides: operator-core package, operator-protocols package
  - phase: 17-ratelimiter-service
    provides: Rate limiter service API endpoints and response models
provides:
  - operator-ratelimiter package with HTTP, Redis, and Prometheus clients
  - Pydantic models matching ratelimiter-service API responses
  - Client infrastructure for RateLimiterSubject observation
affects: [19-02, 19-03, 19-04, 19-05, ratelimiter-subject, ratelimiter-invariants]

# Tech tracking
tech-stack:
  added: [operator-ratelimiter package, redis>=7.0.0]
  patterns: [dataclass clients with injected httpx/redis, Pydantic response validation]

key-files:
  created:
    - packages/operator-ratelimiter/pyproject.toml
    - packages/operator-ratelimiter/src/operator_ratelimiter/types.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/redis_client.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/prom_client.py
  modified: []

key-decisions:
  - "Pydantic model_validate() for response parsing (not **response.json())"
  - "Redis client returns raw ZCARD count (not cleaned - use RateLimiterClient for accurate counts)"
  - "Prometheus string-to-float conversion handled in get_metric_value()"
  - "Fire-and-forget reset_counter operation"
  - "decode_responses=True assumed for Redis client (string returns)"

patterns-established:
  - "Dataclass pattern with injected httpx.AsyncClient and redis.Redis clients"
  - "raise_for_status() after HTTP requests (fail loudly)"
  - "Graceful fallback for missing Prometheus metrics (return 0/None)"
  - "Prefixed Redis keys (ratelimit:{key})"

# Metrics
duration: 3min
completed: 2026-01-27
---

# Phase 19 Plan 01: Package Foundation Summary

**operator-ratelimiter package with HTTP, Redis, and Prometheus clients for rate limiter cluster observation**

## Performance

- **Duration:** 3 min 8 sec
- **Started:** 2026-01-27T01:48:37Z
- **Completed:** 2026-01-27T01:51:45Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Created operator-ratelimiter package installable via pip with httpx, redis, pydantic dependencies
- Implemented RateLimiterClient for management API (/api/nodes, /api/counters, /api/limits, /api/blocks)
- Implemented RedisClient for direct Redis state inspection (ping, counter values, key scanning)
- Implemented PrometheusClient for latency metrics (P99 histogram_quantile) and allowed request counts
- Established Pydantic models matching ratelimiter-service API responses exactly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create package structure and types** - `ce31174` (feat)
2. **Task 2: Create HTTP and Redis clients** - `c74d7c9` (feat)
3. **Task 3: Create Prometheus client** - `211905b` (feat)

## Files Created/Modified

- `packages/operator-ratelimiter/pyproject.toml` - Package configuration with dependencies
- `packages/operator-ratelimiter/src/operator_ratelimiter/__init__.py` - Package root (empty for now)
- `packages/operator-ratelimiter/src/operator_ratelimiter/types.py` - Pydantic models (NodeInfo, CounterInfo, LimitsResponse, BlockedKeyInfo)
- `packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py` - HTTP client for management API
- `packages/operator-ratelimiter/src/operator_ratelimiter/redis_client.py` - Redis client for state inspection
- `packages/operator-ratelimiter/src/operator_ratelimiter/prom_client.py` - Prometheus client for metrics

## Decisions Made

1. **Pydantic model_validate() for response parsing** - Following operator-tikv pattern, using model_validate(response.json()) instead of **response.json() for explicit validation
2. **Redis client returns raw ZCARD count** - RedisClient.get_counter_value() returns raw count without cleaning expired entries (use RateLimiterClient.get_counters() for accurate counts)
3. **Prometheus value conversion** - get_metric_value() handles string-to-float conversion automatically (Prometheus returns ["timestamp", "string_value"])
4. **Fire-and-forget reset_counter** - POST /api/counters/{key}/reset returns immediately after service accepts request (no confirmation wait)
5. **Graceful Prometheus fallback** - Missing metrics return 0/None instead of raising (don't block observation on missing data)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all imports successful, package installs cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Phase 19 Plan 02 (RateLimiterSubject implementation):
- Package infrastructure complete
- Clients follow operator-tikv patterns
- Pydantic models match ratelimiter-service API exactly
- All imports verified working

No blockers. Proceeding to subject implementation next.

---
*Phase: 19-operator-ratelimiter*
*Completed: 2026-01-27*
