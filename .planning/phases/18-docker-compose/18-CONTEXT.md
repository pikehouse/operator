# Phase 18: Docker Compose Environment - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Create reproducible development environment for rate limiter cluster. `docker-compose up` brings up 3 rate limiter nodes, Redis, Prometheus. Prometheus scrapes all nodes. Load generator creates configurable traffic patterns.

</domain>

<decisions>
## Implementation Decisions

### Service Topology
- Single Redis instance (not cluster or sentinel) — sufficient for shared state
- 3 rate limiter nodes — matches success criteria, demonstrates distributed behavior
- Prometheus config inline in docker-compose (not separate file)
- Single network for all services — simple, sufficient for dev

### Load Generator Design
- Container in docker-compose (not external CLI)
- Traffic patterns: steady rate + burst spikes + gradual ramp-up
- Round-robin targeting across all nodes — tests cluster behavior
- Progress stats output: periodic summary (requests sent, success/fail, current RPS)

### Developer Experience
- Rebuild required for code changes (no hot reload via volume mounts)
- Standard docker-compose logs (no centralized logging)
- Direct docker-compose commands (no Makefile wrapper)
- Port mappings configurable via .env file — avoids conflicts

### Health & Readiness
- HTTP health endpoint check (GET /health returns 200)
- depends_on with condition: rate limiters wait for Redis healthy
- Restart policy: no — easier to see failures in dev
- Load generator depends_on rate limiters being healthy

### Claude's Discretion
- Exact port numbers (as long as configurable via .env)
- Prometheus scrape interval
- Load generator default RPS and burst parameters
- Container naming conventions

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 18-docker-compose*
*Context gathered: 2026-01-26*
