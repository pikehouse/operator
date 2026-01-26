# Phase 13: TiKV Subject Actions - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

TiKV subject can execute leader transfer, peer transfer, and store drain operations via PD API. This phase implements the action execution layer — the Subject.execute_action() interface for TiKV-specific operations.

</domain>

<decisions>
## Implementation Decisions

### Execution semantics
- Fire-and-forget: Subject.execute_action() calls PD API and returns success/failure of the API call itself
- No polling or waiting for operation completion — that's the monitor/agent loop's responsibility
- Clean separation: subject handles execution, monitor/agent handles tracking actual completion

### Validation
- Minimal validation: verify required parameters exist (region_id, store_id, etc.)
- Let PD API reject invalid requests — PD is the source of truth
- No pre-validation of cluster state (store exists, region on source, etc.)

### Error handling
- Pass PD API errors straight through
- Return PD error message/code directly to caller
- Agent interprets errors — no error taxonomy layer in subject

### Claude's Discretion
- Exact httpx call structure
- HTTP timeout values for PD API calls
- ActionDefinition parameter schemas for each action type

</decisions>

<specifics>
## Specific Ideas

- Keep factoring clean and separable between agent and monitor
- Simplest implementation that works

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-tikv-subject-actions*
*Context gathered: 2026-01-26*
