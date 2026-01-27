---
phase: 19-operator-ratelimiter
plan: 04
subsystem: operator-integration
tags: [factory, cli, lazy-import, rate-limiter]
requires:
  - 19-02  # RateLimiterSubject and checker implementation
provides:
  - CLI can create RateLimiterSubject via --subject ratelimiter flag
  - Factory function for subject/checker instantiation
  - Package exports for all public APIs
affects:
  - 19-05  # Testing will verify CLI integration
  - 20-01  # E2E demo will use --subject ratelimiter
tech-stack:
  added: []
  patterns:
    - Factory pattern for dependency injection
    - Lazy imports to avoid loading unused packages
key-files:
  created:
    - packages/operator-ratelimiter/src/operator_ratelimiter/factory.py
  modified:
    - packages/operator-ratelimiter/src/operator_ratelimiter/__init__.py
    - packages/operator-core/src/operator_core/cli/subject_factory.py
decisions:
  - what: "Factory returns tuple[Subject, Checker]"
    why: "Convenience pattern for CLI - both are needed together"
    alternatives: "Separate factory functions, but that's more verbose for CLI"
  - what: "decode_responses=True for Redis client"
    why: "Return Python strings instead of bytes (easier to work with)"
    alternatives: "bytes mode, but requires decoding everywhere"
  - what: "Lazy import in subject_factory.py"
    why: "Don't load operator-ratelimiter unless --subject ratelimiter used"
    alternatives: "Eager import, but that would slow down TiKV-only users"
metrics:
  duration: "106s"
  tasks: 3
  commits: 3
  files_created: 1
  files_modified: 2
  completed: "2026-01-27"
---

# Phase 19 Plan 04: Factory Function and CLI Integration Summary

**One-liner:** Factory function enables CLI to create RateLimiterSubject via --subject ratelimiter with lazy loading pattern

## Overview

Created factory function for RateLimiter subject/checker instantiation and integrated with CLI subject selection. This completes the abstraction loop: operator-core CLI can now create either TiKV or rate limiter subjects via the --subject flag, with lazy imports ensuring packages are only loaded when needed.

## What Was Built

### Factory Function (packages/operator-ratelimiter/src/operator_ratelimiter/factory.py)
- `create_ratelimiter_subject_and_checker()` factory function
- Parameters: ratelimiter_url, redis_url, prometheus_url
- Optional pre-configured clients: rl_http, redis_client, prom_http
- Returns tuple[RateLimiterSubject, RateLimiterInvariantChecker]
- Pattern mirrors TiKV factory for consistency

### Package Exports (__init__.py)
- Export RateLimiterSubject, RateLimiterInvariantChecker
- Export create_ratelimiter_subject_and_checker factory
- Export all client classes (RateLimiterClient, RedisClient, PrometheusClient)
- Export all response types (NodeInfo, CounterInfo, etc.)
- Export invariant configs
- Comprehensive __all__ list

### CLI Integration (subject_factory.py)
- Added "ratelimiter" to AVAILABLE_SUBJECTS list
- Added ratelimiter case in create_subject() with lazy import
- Updated docstring with ratelimiter usage example
- Lazy import prevents loading operator-ratelimiter unless requested

## Technical Details

### Factory Pattern
The factory follows the same pattern as operator-tikv:
- Takes endpoint URLs as required parameters
- Accepts optional pre-configured clients for testing
- Creates default clients with sensible timeouts if not provided
- Returns both subject and checker as a tuple (convenience for CLI)

### Lazy Import Strategy
```python
if subject_name == "ratelimiter":
    from operator_ratelimiter.factory import create_ratelimiter_subject_and_checker
    return create_ratelimiter_subject_and_checker(**kwargs)
```

This ensures:
- No runtime overhead for TiKV-only users
- Clear separation between subject packages
- Package dependencies resolved only when needed

### Redis Client Configuration
Factory creates Redis client with `decode_responses=True`:
```python
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
```

This returns Python strings instead of bytes, making it easier to work with counter keys and values throughout the codebase.

## Verification Results

All verification checks passed:

1. ✅ Factory function imports successfully
2. ✅ Package exports work (RateLimiterSubject, checker, factory)
3. ✅ CLI AVAILABLE_SUBJECTS includes "ratelimiter"
4. ✅ Integration chain verified (tikv and ratelimiter both available)

```bash
$ python -c "from operator_core.cli.subject_factory import AVAILABLE_SUBJECTS; print(AVAILABLE_SUBJECTS)"
['tikv', 'ratelimiter']
```

## Testing Readiness

Ready for 19-05 testing plan:
- Factory function with proper dependency injection
- Package exports validated
- CLI integration verified
- Lazy import pattern working

Next phase (19-05) will add integration tests to verify:
- Factory creates working subject/checker pairs
- CLI can instantiate both TiKV and rate limiter subjects
- Lazy imports don't break when packages are actually loaded

## Deviations from Plan

None - plan executed exactly as written.

## Lessons Learned

1. **Factory pattern consistency pays off** - Following TiKV factory pattern made implementation straightforward and predictable
2. **decode_responses=True is essential** - Without it, every Redis string operation would need manual decoding
3. **Lazy imports are critical** - Prevents forcing all users to install both subject packages

## Next Phase Readiness

**Status:** ✅ Ready for 19-05 (Testing)

**Blockers:** None

**Concerns:** None

**What's needed:**
- Integration tests for factory function
- CLI integration tests with both subject types
- End-to-end test with real Redis/Prometheus (will happen in 20-01 demo)

## Files Changed

### Created (1 file)
- `packages/operator-ratelimiter/src/operator_ratelimiter/factory.py` (73 lines)
  - Factory function with optional client injection
  - Mirrors TiKV factory pattern
  - decode_responses=True for Redis

### Modified (2 files)
- `packages/operator-ratelimiter/src/operator_ratelimiter/__init__.py`
  - Added comprehensive exports (subject, checker, factory, clients, types)
  - Added __all__ list with 22 exports

- `packages/operator-core/src/operator_core/cli/subject_factory.py`
  - Added "ratelimiter" to AVAILABLE_SUBJECTS
  - Added ratelimiter case with lazy import
  - Updated docstring with ratelimiter example

## Commits

| Commit | Message | Files |
|--------|---------|-------|
| 1d065b7 | feat(19-04): create ratelimiter factory function | factory.py |
| 8e5ea82 | feat(19-04): update operator-ratelimiter package exports | __init__.py |
| 5f9c135 | feat(19-04): integrate ratelimiter with CLI subject factory | subject_factory.py |

---

*Completed: 2026-01-27 | Duration: 106s*
