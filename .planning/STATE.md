# Project State: Operator

## Current Position

**Milestone:** v2.1 Multi-Subject Support (Rate Limiter)
**Phase:** 19 of 20 (operator-ratelimiter Package)
**Plan:** 03 of 05 completed
**Status:** In progress
**Last activity:** 2026-01-27 - Completed 19-03-PLAN.md (Management API actions)

Progress: [########..] 82% (4.4/5 phases complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-26)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — proving the abstraction works for novel, out-of-distribution systems.

**Current focus:** Phase 19 started - Building operator-ratelimiter package (1/5 plans complete)

## Milestones

| Version | Status | Date |
|---------|--------|------|
| v1.0 | SHIPPED | 2026-01-25 |
| v1.1 | SHIPPED | 2026-01-25 |
| v2.0 | SHIPPED | 2026-01-26 |
| v2.1 | IN PROGRESS | — |

See: .planning/MILESTONES.md

## v2.1 Phase Overview

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 16 | Core Abstraction Refactoring | CORE-01 through CORE-05 (5) | COMPLETE |
| 17 | Rate Limiter Service Foundation | RLSVC-01 through RLSVC-04 (4) | VERIFIED |
| 18 | Docker Compose Environment | RLSVC-05, DEMO-01 (2) | COMPLETE |
| 19 | operator-ratelimiter Package | RLPKG-*, MON-*, ACT-* (11) | IN PROGRESS (3/5) |
| 20 | E2E Demo & Chaos | DEMO-02 through DEMO-04 (3) | — |

## Archives

| File | Contents |
|------|----------|
| milestones/v1.0-ROADMAP.md | v1.0 roadmap (6 phases) |
| milestones/v1.0-REQUIREMENTS.md | v1.0 requirements (19 total) |
| milestones/v1.1-ROADMAP.md | v1.1 roadmap (5 phases) |
| milestones/v1.1-REQUIREMENTS.md | v1.1 requirements (11 total) |
| milestones/v1.1-MILESTONE-AUDIT.md | v1.1 audit report |
| milestones/v2.0-ROADMAP.md | v2.0 roadmap (4 phases) |
| milestones/v2.0-REQUIREMENTS.md | v2.0 requirements (17 total) |

## Accumulated Context

**Decisions from prior milestones:**
- Observe-only first - proved AI diagnosis quality before action
- Protocol-based abstractions - Subject and DeploymentTarget extensible
- Subprocess isolation for TUI - daemons run as real processes
- httpx, Pydantic, aiosqlite stack - proven across 3 milestones

**Key decisions from v2.0:**
- Pydantic BaseModel for action types (validation + serialization)
- Default to OBSERVE mode (safe by default, explicit opt-in for execution)
- Kill switch cancels pending AND switches to OBSERVE mode
- Fire-and-forget action semantics for PD API calls
- Tools use same ActionDefinition model with action_type=ActionType.TOOL

**Key decisions from v2.1 (Phase 16):**
- Observation type is dict[str, Any] for maximum flexibility across subjects
- store_id field name preserved in InvariantViolation for backward compatibility
- operator-protocols package has zero dependencies
- TiKVInvariantChecker.check() parses observation dict to typed objects internally
- Factory functions for CLI integration to avoid direct subject imports
- --subject flag is required (no default) for explicit subject selection
- Factory returns tuple (subject, checker) for convenience
- MonitorLoop uses generic observe/check pattern (16-03)
- Region/RegionId kept in operator_core.types for backward compat (deprecated) (16-03)
- demo/chaos.py stays TiKV-specific (not core functionality) (16-03)
- Protocol compliance tests validate abstraction works (16-05)

**Key decisions from v2.1 (Phase 17):**
- pydantic-settings for env config (RATELIMITER_ prefix)
- Connection pool pattern for async Redis (not per-request connections)
- decode_responses=True for string returns instead of bytes
- Lua script returns [allowed, count, remaining, retry_after] tuple
- Unique member format timestamp:sequence prevents duplicates at same millisecond
- Key prefix 'ratelimit:' for Redis namespacing
- X-RateLimit-* headers follow standard convention for rate limit responses
- 429 status code set automatically when rate limit exceeded
- Node registration uses hash keys with TTL for automatic expiration on failure
- Background heartbeat task maintains registration continuously
- Decorator approach for histogram timing (@CHECK_LATENCY.time())
- Gauge update on counters endpoint reflects current state per query

**Key decisions from v2.1 (Phase 18):**
- Inline Prometheus config via Docker configs feature (no separate prometheus.yml file)
- Copy src/ before pip install in Dockerfile (hatch build requires source at install time)
- restart: "no" for dev environment (show failures instead of hiding them)
- depends_on with condition: service_healthy for proper startup ordering
- Both 200 and 429 responses count as success for load generator (rate limiter working correctly)
- asyncio.Semaphore(100) for concurrent request limiting in load generator
- itertools.cycle for stateless round-robin target distribution

**Key decisions from v2.1 (Phase 19-01):**
- Pydantic model_validate() for response parsing (not **response.json())
- Redis client returns raw ZCARD count (not cleaned - use RateLimiterClient for accurate counts)
- Prometheus string-to-float conversion handled in get_metric_value()
- Fire-and-forget reset_counter operation
- Graceful fallback for missing Prometheus metrics (return 0/None)

**Key decisions from v2.1 (Phase 19-03):**
- Per-key limit storage in Redis hash keys at "ratelimit:limit:{key}" (RLPKG-09)
- Reset endpoint returns 200 for both existing and nonexistent keys (idempotent) (RLPKG-10)
- Update limit requires explicit limit parameter (no optional/null to prevent accidents) (RLPKG-11)
- Hash structure stores both limit and window_ms together
- RateLimiter.get_limit() returns None if no custom limit exists

**Research flags for v2.1:**
- Phase 16 (Core Refactoring): COMPLETE - abstraction validated with 86 passing tests
- Phase 17 (Lua Scripts): VERIFIED - atomic patterns prevent race conditions (20 concurrent requests, exactly 10 allowed/blocked)

## Session Continuity

**Last session:** 2026-01-27
**Stopped at:** Completed 19-03-PLAN.md (Management API actions) - Phase 19 plan 3/5 complete
**Resume with:** 19-02-PLAN.md (RateLimiterSubject implementation) or 19-04-PLAN.md (next in sequence)

## Phase 16 Completion Summary

All 5 plans of Phase 16 completed:
- 16-01: Created operator-protocols package (SubjectProtocol, InvariantCheckerProtocol, InvariantViolation)
- 16-02: Updated TiKV subject to implement protocols via factory
- 16-03: Removed TiKV imports from operator-core, MonitorLoop uses protocols
- 16-04: Added CLI subject selection with --subject flag
- 16-05: Validated abstraction with protocol compliance tests

Total new tests: 26 (15 protocol compliance + 11 generic monitor)
Total tests passing: 86

## Phase 17 Completion Summary

All 4 plans of Phase 17 completed:
- 17-01: Created package structure with config, Redis client, and empty api/ directory
- 17-02: Implemented sliding window rate limiter with atomic Lua script
- 17-03: Built FastAPI application with rate limiting endpoints, management APIs, and Prometheus metrics
- 17-04: Wired CHECK_LATENCY histogram and ACTIVE_COUNTERS gauge (gap closure)

Rate limiter service is fully instrumented and ready for deployment (Phase 18).

## Phase 18 Completion Summary

All 2 plans of Phase 18 completed:
- 18-01: Docker Compose environment with Redis, 3 rate limiter nodes, and Prometheus
- 18-02: Load generator with round-robin targeting and burst traffic patterns

Files created:
- packages/ratelimiter-service/Dockerfile
- docker/docker-compose.yml
- docker/.env.example
- docker/loadgen/loadgen.py
- docker/loadgen/Dockerfile

Verified: 6 services orchestrated (redis, 3 ratelimiters, prometheus, loadgen). Load generator produces ~10 RPS with burst spikes.

## Phase 19 Progress

Plans 01 and 03 of 05 completed:
- 19-01: Created operator-ratelimiter package foundation (HTTP, Redis, Prometheus clients)
- 19-03: Added management API actions (reset_counter, update_limit)

Files created:
- packages/operator-ratelimiter/pyproject.toml
- packages/operator-ratelimiter/src/operator_ratelimiter/__init__.py
- packages/operator-ratelimiter/src/operator_ratelimiter/types.py
- packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py
- packages/operator-ratelimiter/src/operator_ratelimiter/redis_client.py
- packages/operator-ratelimiter/src/operator_ratelimiter/prom_client.py
- packages/ratelimiter-service/tests/test_management_api.py

Next: 19-02 (RateLimiterSubject implementation) or 19-04 (Action definitions)

## Open Issues

*None*

---
*State updated: 2026-01-27 (Phase 19 plan 03 complete)*
