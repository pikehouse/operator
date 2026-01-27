---
phase: 19-operator-ratelimiter
plan: 03
subsystem: operator-ratelimiter
tags: [management-api, rate-limiter, redis, http-endpoints]

requires:
  - phase: 17
    plan: 03
    what: FastAPI management API foundation with existing GET endpoints
  - phase: 19
    plan: 01
    what: RateLimiterClient HTTP client for API interaction

provides:
  - what: POST /api/counters/{key}/reset endpoint
    file: packages/ratelimiter-service/src/ratelimiter_service/api/management.py
    consumers: [operator-ratelimiter]
  - what: PUT /api/limits/{key} endpoint
    file: packages/ratelimiter-service/src/ratelimiter_service/api/management.py
    consumers: [operator-ratelimiter]
  - what: RateLimiter.update_limit() method for per-key limit overrides
    file: packages/ratelimiter-service/src/ratelimiter_service/limiter.py
    consumers: [management API]

affects:
  - phase: 19
    plan: 04
    how: RateLimiterSubject can now use reset_counter and update_limit actions
  - phase: 19
    plan: 05
    how: Action execution can leverage both management endpoints

tech-stack:
  added: []
  patterns:
    - Per-key limit storage using Redis hash keys (ratelimit:limit:{key})
    - Fire-and-forget reset operation with boolean confirmation
    - Update limit stores both limit and window_ms in hash
    - Pydantic models for request/response validation

key-files:
  created:
    - packages/ratelimiter-service/tests/test_management_api.py
  modified:
    - packages/ratelimiter-service/src/ratelimiter_service/api/management.py
    - packages/ratelimiter-service/src/ratelimiter_service/limiter.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/types.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py

decisions:
  - id: RLPKG-09
    what: Store per-key limit overrides in Redis hash keys
    why: Enables dynamic per-key limits without config reload
    pattern: "ratelimit:limit:{key}" with {limit, window_ms} hash fields
    alternative: Store in memory (lost on restart)
  - id: RLPKG-10
    what: Reset endpoint returns 200 for both existing and nonexistent keys
    why: Idempotent behavior - result is the same (counter cleared)
    response: reset=true if key existed, reset=false if not
    alternative: 404 for nonexistent keys (less idempotent)
  - id: RLPKG-11
    what: Update limit requires explicit limit parameter
    why: Prevent accidental removal of limits
    validation: Pydantic validates limit is required integer
    alternative: Allow null limit to remove override (more dangerous)

metrics:
  duration: 3m
  tasks: 3
  commits: 3
  tests_added: 6
  completed: 2026-01-27
---

# Phase 19 Plan 03: Management API Actions Summary

Management API endpoints for reset_counter and update_limit actions, enabling AI diagnosis to clear rate limit counters and adjust limits dynamically.

## Tasks Completed

### Task 1: Add reset counter endpoint (cc1324f)
Added POST /api/counters/{key}/reset endpoint to management API:
- Created ResetResponse model with key and reset fields
- Added reset_counter endpoint function using limiter.reset_counter()
- Returns 200 with reset=True if key existed, reset=False if not
- Idempotent operation suitable for fire-and-forget action execution

**Files modified:**
- packages/ratelimiter-service/src/ratelimiter_service/api/management.py

### Task 2: Add update limit endpoint (7178d8f)
Added PUT /api/limits/{key} endpoint and update_limit method:
- Implemented RateLimiter.update_limit() method to store per-key limits in Redis
- Implemented RateLimiter.get_limit() method to retrieve stored limits
- Added UpdateLimitRequest and UpdateLimitResponse Pydantic models
- Added update_limit endpoint to management API
- Added update_limit() method to RateLimiterClient for operator integration
- Per-key limits stored in "ratelimit:limit:{key}" hash with limit and window_ms

**Files modified:**
- packages/ratelimiter-service/src/ratelimiter_service/limiter.py
- packages/ratelimiter-service/src/ratelimiter_service/api/management.py
- packages/operator-ratelimiter/src/operator_ratelimiter/types.py
- packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py

### Task 3: Add integration tests (43e6707)
Created comprehensive integration tests for management endpoints:
- test_reset_counter_existing_key - Verifies counter cleared
- test_reset_counter_nonexistent_key - Verifies reset=False returned
- test_update_limit_basic - Verifies limit stored with custom window
- test_update_limit_default_window - Verifies default window used when not specified
- test_update_limit_overwrites_previous - Verifies updates replace old limits
- test_reset_and_update_workflow - Integration test combining both operations

**Files created:**
- packages/ratelimiter-service/tests/test_management_api.py (183 lines, 6 test cases)

## Architecture

```
operator-ratelimiter                 ratelimiter-service
    RateLimiterClient  ----HTTP---->  management_router
         |                                    |
         | POST /api/counters/{key}/reset    | reset_counter()
         | PUT /api/limits/{key}             | update_limit()
         |                                    v
         |                              RateLimiter
         |                                    |
         |                                    v
         |                                  Redis
         |                                    |
         |                    ratelimit:{key} (sorted set - counter)
         |                    ratelimit:limit:{key} (hash - custom limit)
```

## Decisions Made

### 1. Per-key limit storage pattern (RLPKG-09)
**Decision:** Store per-key limit overrides in Redis hash keys at "ratelimit:limit:{key}"

**Rationale:**
- Enables dynamic per-key limits without config reload or service restart
- Persists across rate limiter node restarts
- Accessible to all rate limiter nodes in cluster
- Hash structure stores both limit and window_ms together

**Alternative considered:** Store in memory (simpler but lost on restart)

### 2. Idempotent reset endpoint (RLPKG-10)
**Decision:** POST /api/counters/{key}/reset returns 200 for both existing and nonexistent keys

**Rationale:**
- Idempotent behavior - calling reset multiple times has same effect
- Result is the same whether key existed or not (counter is cleared)
- Simplifies client logic (no need to handle 404)
- Boolean reset field indicates whether key existed for observability

**Alternative considered:** Return 404 for nonexistent keys (less idempotent, more HTTP-semantic)

### 3. Required limit parameter (RLPKG-11)
**Decision:** Update limit endpoint requires explicit limit parameter (no optional/null)

**Rationale:**
- Prevents accidental removal of limits
- Forces explicit intent when setting limits
- Pydantic validation ensures limit is integer
- To remove a limit override, client must explicitly delete the Redis key

**Alternative considered:** Allow null limit to remove override (more flexible but dangerous)

## Testing

6 integration tests added covering:
- Reset counter for existing keys (counter cleared)
- Reset counter for nonexistent keys (returns reset=False)
- Update limit with custom window
- Update limit with default window
- Update limit overwrites previous limit
- Integration workflow (update, use, reset, verify limit persists)

All tests use FastAPI TestClient for HTTP testing and async Redis client for verification.

## Success Criteria

- [x] POST /api/counters/{key}/reset endpoint exists in management router
- [x] PUT /api/limits/{key} endpoint exists in management router
- [x] Endpoints call limiter methods and return results
- [x] RateLimiterClient has update_limit() method
- [x] Integration tests verify both endpoints work correctly

## Next Phase Readiness

**Phase 19-04 (RateLimiterSubject):**
- Ready - Both action endpoints available for Subject to call
- RateLimiterClient methods ready for integration
- HTTP client injection pattern established

**Phase 19-05 (Action Execution):**
- Ready - Action definitions can map to reset_counter and update_limit methods
- Response models provide structured results for action execution

**Blockers:** None

**Risks:** None

## Performance Impact

- Reset operation: O(1) - single Redis DEL command
- Update limit operation: O(1) - single Redis HSET command
- Both operations are fast fire-and-forget actions suitable for live diagnosis

## Files Changed Summary

**Created (1 file):**
- packages/ratelimiter-service/tests/test_management_api.py

**Modified (4 files):**
- packages/ratelimiter-service/src/ratelimiter_service/api/management.py (+33 lines)
- packages/ratelimiter-service/src/ratelimiter_service/limiter.py (+45 lines)
- packages/operator-ratelimiter/src/operator_ratelimiter/types.py (+16 lines)
- packages/operator-ratelimiter/src/operator_ratelimiter/ratelimiter_client.py (+33 lines)

## Deviations from Plan

None - plan executed exactly as written. All tasks completed without modifications.
