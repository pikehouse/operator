# Phase 17: Rate Limiter Service Foundation - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a custom distributed rate limiter service that will be monitored by operator-ratelimiter. The service runs as 3+ nodes sharing Redis state via atomic Lua scripts. This is a demo service to prove the operator abstraction generalizes beyond TiKV — not a production-ready rate limiter product.

The operator-ratelimiter package that monitors this service is Phase 19. Docker Compose environment is Phase 18.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion

User elected to skip discussion. Claude has full discretion on implementation decisions for this phase, guided by the success criteria from ROADMAP.md:

1. **Rate limiting algorithm** — Sliding window counter with atomic Lua scripts
2. **HTTP management API** — Endpoints for node list, counters, limits, blocks
3. **Prometheus metrics** — Standard rate limiter metrics (requests, blocks, latency)
4. **Node coordination** — Shared Redis state, nodes are stateless

**Constraints from success criteria:**
- Must run as 3+ nodes
- Must use Redis for shared state
- Must use atomic Lua scripts (no race conditions)
- Must enforce limits exactly under concurrent load
- Must export Prometheus metrics

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches that meet the success criteria.

**Key principle:** This is a demo to prove the operator abstraction works. Simplicity over production-readiness.

</specifics>

<deferred>
## Deferred Ideas

None — discussion skipped, no scope creep possible.

</deferred>

---

*Phase: 17-rate-limiter-service-foundation*
*Context gathered: 2026-01-26*
