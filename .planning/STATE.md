# Project State: Operator

## Current Position

**Milestone:** v2.1 Multi-Subject Support (Rate Limiter)
**Phase:** 17 of 20 (Rate Limiter Service Foundation)
**Plan:** 03 of 03 completed
**Status:** Phase 17 complete
**Last activity:** 2026-01-26 - Completed 17-03-PLAN.md (HTTP API and FastAPI application)

Progress: [#####.....] 50% (2/5 phases complete)

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-26)

**Core value:** AI demonstrates real diagnostic reasoning about distributed systems — proving the abstraction works for novel, out-of-distribution systems.

**Current focus:** Phase 17 complete - Rate Limiter Service Foundation ready for deployment

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
| 17 | Rate Limiter Service Foundation | RLSVC-01 through RLSVC-04 (4) | COMPLETE |
| 18 | Docker Compose Environment | RLSVC-05, DEMO-01 (2) | — |
| 19 | operator-ratelimiter Package | RLPKG-*, MON-*, ACT-* (11) | — |
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

**Research flags for v2.1:**
- Phase 16 (Core Refactoring): COMPLETE - abstraction validated with 86 passing tests
- Phase 17 (Lua Scripts): VERIFIED - atomic patterns prevent race conditions (20 concurrent requests, exactly 10 allowed/blocked)

## Session Continuity

**Last session:** 2026-01-26
**Stopped at:** Completed 17-03-PLAN.md (HTTP API and FastAPI application)
**Resume with:** Phase 18 (Docker Compose Environment)

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

All 3 plans of Phase 17 completed:
- 17-01: Created package structure with config, Redis client, and empty api/ directory
- 17-02: Implemented sliding window rate limiter with atomic Lua script
- 17-03: Built FastAPI application with rate limiting endpoints, management APIs, and Prometheus metrics

Rate limiter service is ready for deployment (Phase 18).

## Open Issues

*None*

---
*State updated: 2026-01-26 (Phase 17 complete)*
