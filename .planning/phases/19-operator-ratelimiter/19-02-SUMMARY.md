---
phase: 19-operator-ratelimiter
plan: 02
subsystem: operator-ratelimiter
status: complete
tags: [rate-limiter, subject, invariants, protocols, monitoring]

requires:
  - 19-01: Package foundation (clients)
  - 16-01: operator-protocols package

provides:
  - RateLimiterSubject implementing SubjectProtocol
  - RateLimiterInvariantChecker implementing InvariantCheckerProtocol
  - 5 invariant types with grace period support

affects:
  - 19-04: CLI integration will use these implementations
  - 19-05: Testing will validate invariant detection

tech-stack:
  added: []
  patterns:
    - Subject protocol pattern (mirrors TiKV)
    - Grace period tracking for transient violations
    - Fire-and-forget action semantics

key-files:
  created:
    - packages/operator-ratelimiter/src/operator_ratelimiter/subject.py
    - packages/operator-ratelimiter/src/operator_ratelimiter/invariants.py
  modified: []

decisions:
  - id: RLPKG-02-01
    title: Mirror TiKV patterns for consistency
    rationale: Consistent implementation patterns across subjects make codebase easier to understand
    impact: RateLimiterSubject and RateLimiterInvariantChecker follow same structure as TiKV equivalents
    alternatives: []
    date: 2026-01-27

  - id: RLPKG-02-02
    title: Grace periods for latency and drift invariants
    rationale: Rate limiter has transient spikes; grace periods prevent false alarms
    impact: high_latency gets 60s grace, counter_drift gets 30s grace
    alternatives:
      - No grace periods (rejected - too noisy)
      - Longer grace periods (rejected - delays detection)
    date: 2026-01-27

  - id: RLPKG-02-03
    title: Counter drift as helper method only
    rationale: Checking counter drift requires Redis query per counter; too expensive for observe()
    impact: check_counter_drift() available for testing but not called in generic check()
    alternatives:
      - Include in check() (rejected - performance concern)
      - Remove entirely (rejected - useful for diagnosis)
    date: 2026-01-27

metrics:
  duration: 154s
  completed: 2026-01-27
---

# Phase 19 Plan 02: RateLimiterSubject and InvariantChecker Summary

**One-liner:** Subject and invariant checker implementing generic protocols for rate limiter monitoring

## Overview

Implemented RateLimiterSubject and RateLimiterInvariantChecker following the protocol patterns established in Phase 16. These implementations enable the MonitorLoop to observe and diagnose rate limiter clusters using the same generic code path as TiKV.

## What Was Built

### RateLimiterSubject (206 lines)

Subject implementation with:

1. **Generic observe() method** returning dict with:
   - nodes: List of node info (id, address, state)
   - counters: List of counter info (key, count, limit, remaining)
   - node_metrics: Per-node latency metrics
   - redis_connected: Boolean connectivity status

2. **Action definitions** for ActionRegistry:
   - reset_counter: Medium risk, fire-and-forget
   - update_limit: High risk, fire-and-forget

3. **Action methods**:
   - reset_counter(key): Clears rate limit counter
   - update_limit(key, new_limit): Sets new limit for key

### RateLimiterInvariantChecker (415 lines)

Invariant checker implementing 5 invariant types:

1. **node_down** (immediate, critical)
   - Detects nodes not in "Up" state
   - No grace period - critical failure

2. **redis_disconnected** (immediate, critical)
   - Detects Redis connectivity loss
   - Cluster-wide violation

3. **high_latency** (60s grace, warning)
   - Detects P99 latency > 100ms
   - Grace period prevents transient spike alerts

4. **counter_drift** (30s grace, warning)
   - Helper method for Redis vs API count mismatch
   - Not used in generic check() (performance)

5. **ghost_allowing** (immediate, warning)
   - Detects limit=0 with remaining>0 (misconfiguration)
   - Indicates requests allowed with no valid limit

## Tasks Completed

| Task | Description | Commit | Result |
|------|-------------|--------|--------|
| 1 | Create RateLimiterSubject | 27a848b | ✅ Subject implements observe(), get_action_definitions(), and 2 action methods |
| 2 | Create RateLimiterInvariantChecker | ccbfa6e | ✅ Checker implements check() with 5 invariant types and grace period tracking |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] update_limit raised NotImplementedError**

- **Found during:** Task 1 completion
- **Issue:** Initial implementation raised NotImplementedError for update_limit, but plan 19-03 had already implemented the API endpoint
- **Fix:** Updated update_limit() to call self.ratelimiter.update_limit(key, new_limit)
- **Files modified:** subject.py
- **Commit:** fb89de5

## Verification Results

All verification checks passed:

1. ✅ RateLimiterSubject has observe(), get_action_definitions(), reset_counter(), update_limit()
2. ✅ RateLimiterInvariantChecker.check() returns list of InvariantViolation
3. ✅ redis_disconnected detected when redis_connected=False
4. ✅ node_down detected when node state != "Up"
5. ✅ Observation structure matches TiKV pattern

## Testing

Manual verification performed:

```python
# Basic structure test
checker = RateLimiterInvariantChecker()
violations = checker.check({
    'nodes': [],
    'counters': [],
    'node_metrics': {},
    'redis_connected': True,
})
assert isinstance(violations, list)

# Redis disconnected detection
violations = checker.check({
    'nodes': [],
    'counters': [],
    'node_metrics': {},
    'redis_connected': False,
})
assert any(v.invariant_name == 'redis_disconnected' for v in violations)

# Node down detection
violations = checker.check({
    'nodes': [{'id': 'node1', 'address': 'localhost:8080', 'state': 'Down'}],
    'counters': [],
    'node_metrics': {},
    'redis_connected': True,
})
assert any(v.invariant_name == 'node_down' for v in violations)
```

## Next Phase Readiness

**Ready for Phase 19-04 (CLI Integration)**

Prerequisites met:
- ✅ RateLimiterSubject implements SubjectProtocol
- ✅ RateLimiterInvariantChecker implements InvariantCheckerProtocol
- ✅ Factory pattern ready (can create factory in 19-04)
- ✅ Action definitions available for registry

**Known limitations:**
- counter_drift invariant not used in check() due to performance (requires per-counter Redis queries)
- Graceful metric collection fallback (continues on error)

## Architecture Notes

**Pattern consistency:**
- RateLimiterSubject mirrors TiKVSubject structure exactly
- RateLimiterInvariantChecker mirrors TiKVInvariantChecker structure exactly
- Grace period tracking uses same _first_seen dict pattern
- Fire-and-forget action semantics match TiKV

**Grace period rationale:**
- high_latency: 60s to tolerate transient spikes during load bursts
- counter_drift: 30s to tolerate brief Redis/API inconsistencies
- node_down: 0s because node failure is critical
- redis_disconnected: 0s because Redis is critical for rate limiting
- ghost_allowing: 0s because misconfiguration should be immediately visible

**Performance considerations:**
- observe() collects all data in one pass
- Metrics collection has try/except to prevent blocking
- counter_drift not in check() to avoid N*Redis queries per observation

## Commits

- `27a848b` feat(19-02): implement RateLimiterSubject with observe and action methods
- `ccbfa6e` feat(19-02): implement RateLimiterInvariantChecker with 5 invariant types
- `fb89de5` fix(19-02): implement update_limit action using existing API

## Files Changed

**Created (2 files, 621 lines):**
- packages/operator-ratelimiter/src/operator_ratelimiter/subject.py (206 lines)
- packages/operator-ratelimiter/src/operator_ratelimiter/invariants.py (415 lines)

**Modified (1 file):**
- packages/operator-ratelimiter/src/operator_ratelimiter/subject.py (bug fix)

---

*Completed: 2026-01-27*
*Duration: 154 seconds (~2.5 minutes)*
