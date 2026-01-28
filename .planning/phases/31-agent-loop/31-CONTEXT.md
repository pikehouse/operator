# Phase 31: Agent Loop - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

The ~200 line core loop that runs Claude. Picks up tickets from the database, executes Claude with shell tool access, manages sessions, and logs outcomes. Health check triggering and integration testing are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Trigger mechanism
- Agent polls database for tickets (not Prometheus directly, not webhooks)
- Fixed 1-second polling interval
- One ticket at a time — finish current before checking for more

### Conversation flow
- Claude receives ticket only at session start — queries for system state as needed
- No limit on tool calls per session
- System prompt positions Claude as SRE operator
- Minimal hints about available tools ("you have shell access" — Claude discovers what's there)

### Session lifecycle
- Session completes when Claude declares done OR verifies problem resolved
- No session timeout — let Claude work as long as needed
- On success: Mark ticket resolved AND record Claude's summary
- On failure/give-up: Mark ticket as needs-human-attention (escalate)

### Output & logging
- Verbose console output: Claude's reasoning, tool calls, and outputs visible during run
- Audit logs stored in database alongside tickets (not separate JSON files)
- Tool outputs summarized by Haiku before logging (keeps logs readable)
- Claude's reasoning also summarized by Haiku
- Designed as log sequence for later viewing/replay

### Claude's Discretion
- Exact polling implementation details
- How to structure the SRE system prompt
- Console output formatting
- How to detect "problem resolved" vs "Claude says done"

</decisions>

<specifics>
## Specific Ideas

- Audit logs should be viewable as a time-ordered sequence later
- Keep the core loop under 200 lines as stated in phase goal

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 31-agent-loop*
*Context gathered: 2026-01-28*
