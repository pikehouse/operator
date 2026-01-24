# Phase 2: TiKV Subject - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement the TiKV Subject — operator can observe TiKV cluster state through PD API client, Prometheus metrics client, TiKV invariants, and log parsing. This is the first complete subject implementation against the interface defined in Phase 1.

Lives in `operator-tikv` package, separate from `operator-core`.

</domain>

<decisions>
## Implementation Decisions

### Metric selection
- Fixed thresholds (not baseline-relative) for latency alerting
- Track P95 and P99 latency percentiles
- Conservative resource thresholds (70%+) for disk, CPU, memory
- Raft-specific metrics: skip for now — focus on basic health first

### Invariant design
- Grace period configurable per invariant (some immediate like node down, others sustained like latency)
- Auto-close tickets when violation clears before diagnosis
- Time-windowed deduplication for repeated violations of same invariant

### Log parsing scope
- Purpose: context for AI diagnosis only (not independent alerting)
- Event types: leadership changes only — simplest viable implementation
- Retention: last 30 minutes of log history for diagnosis context

### API error handling
- Immediate ticket when PD or Prometheus unreachable (can't observe = ticket)
- Hardcoded timeout defaults (no configuration complexity)
- Fail loudly on unexpected data (schema mismatch, missing fields)

### Claude's Discretion
- Severity levels for invariants (critical/warning/info vs binary)
- Log access method (Docker logs API vs mounted files)
- Degraded operation mode (simplest approach)
- Specific timeout values

</decisions>

<specifics>
## Specific Ideas

- Keep implementation minimal — absolute simplest subject implementation
- TiKV concerns isolated in `operator-tikv`, core stays abstract

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-tikv-subject*
*Context gathered: 2026-01-24*
