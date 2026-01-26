# Phase 16: Core Abstraction Refactoring - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Decouple operator-core from TiKV-specific types so any Subject can be monitored. This is a structural refactoring phase — extract packages, define protocols, update imports. The TiKV subject must continue working unchanged.

</domain>

<decisions>
## Implementation Decisions

### Generic type design
- Observation type: `dict[str, Any]` — maximum flexibility, each subject defines its own schema
- Action type: Protocol-based — any class implementing `execute()` works, no central registry

### CLI subject selection
- Hardcoded switch for subject selection (`if subject == 'tikv': ...`)
- `--subject` flag is **required** — explicit selection, no default
- Unknown subject shows error with available subjects list
- Subjects can register their own CLI flags (e.g., `--pd-address` for tikv, `--redis-url` for ratelimiter)

### Package boundaries
- **operator-protocols**: New package for Subject Protocol and base types
- **operator-helpers**: New package for generic utilities (Prometheus, log reading, HTTP helpers)
- **operator-core**: MonitorLoop, AI integration, action executor — subject-agnostic orchestration
- **operator-tikv**: Separate installable package for TiKV subject (depends on core, protocols, helpers)
- Subject-specific utilities stay with their subject package

### Migration strategy
- Big bang refactor — one large PR extracting all packages at once
- All work done on feature branch, only merge when fully working
- Validation: existing test suite must pass
- Add protocol compliance tests to verify TiKV subject correctly implements the new Protocol

### Claude's Discretion
- Invariant result type design — choose what works best for AI consumption
- Subject Protocol style (typing.Protocol vs ABC) — based on Python patterns in codebase

</decisions>

<specifics>
## Specific Ideas

- Generic utilities (Prometheus, log reading) are shared; subject-specific utilities (PD client, rate limiter client) stay with their subject
- Protocol-based actions mean no inheritance required — if it has `execute()`, it's an action

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 16-core-abstraction-refactoring*
*Context gathered: 2026-01-26*
