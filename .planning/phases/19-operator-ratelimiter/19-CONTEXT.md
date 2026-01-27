# Phase 19: operator-ratelimiter Package - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement Subject Protocol for rate limiter with invariants and actions. RateLimiterSubject implements SubjectProtocol, InvariantChecker detects anomalies (node unreachable, Redis disconnected, high latency, counter drift, ghost allowing), and actions execute (reset counter, update limit). MonitorLoop runs with RateLimiterSubject using same code path as TiKV.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion

All implementation decisions delegated to Claude:

**Observation structure:**
- What data to collect from each node (health, counters, latency, Redis connectivity)
- How to aggregate multi-node state into a single observation
- Polling frequency and timeout handling

**Invariant definitions:**
- Detection thresholds for high latency, counter drift, ghost allowing
- How to define "node unreachable" vs "Redis disconnected"
- Window sizes for drift detection

**Action semantics:**
- Parameters for reset_counter and update_limit actions
- Whether actions are confirmed or fire-and-forget (match TiKV pattern)
- Error handling for failed actions

**AI context format:**
- How observations are structured for AI diagnosis
- Verbosity level and grouping of state
- Alignment with TiKV observation patterns

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

Guiding principle: Follow patterns established by TiKV subject implementation. The goal is proving the abstraction works generically, not novel approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 19-operator-ratelimiter*
*Context gathered: 2026-01-26*
