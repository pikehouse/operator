# Phase 32: Integration & Demo - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

End-to-end validation of the autonomous agent against real subjects. Agent container runs alongside TiKV cluster in Docker Compose, Claude autonomously diagnoses and fixes issues using shell commands, complete audit trail captured and reviewable.

</domain>

<decisions>
## Implementation Decisions

### Docker Compose Setup
- Separate compose file for agent container (not in main subject compose)
- Agent compose references subject's network as external — agent joins the existing network
- Mount /var/run/docker.sock from host — agent controls sibling containers directly
- Full internet access from inside agent container (can curl docs, access APIs)

### Failure Scenario Design
- Reuse existing subject fault injection mechanisms (TiKV and rate limiter already have chaos scenarios)
- Existing monitor process continues to do detection and ticket creation
- Agent polls database for tickets, picks them up, works on them — no new alerting path
- Failure injection: docker stop one TiKV node (simulates node going down)
- Success criteria: Container running AND Prometheus shows healthy cluster metrics

### Audit Review Tooling
- CLI tool (not Web UI)
- List recent sessions, show full conversation for a specific session
- Formatted text output with timestamps and indentation (human-readable)
- Show Haiku summaries, not full tool output (summarized view only)

### Demo Flow
- Repurpose existing TUI demo framework (Rich-based dashboard, chapters, visualizations stay)
- Stream Claude's full reasoning and commands to TUI panel in real-time
- No manual controls in TUI — agent runs autonomously, TUI is view-only
- Same chapter structure: inject fault → detect → agent diagnoses → agent fixes → verify

### Claude's Discretion
- Exact TUI panel layout for agent output stream
- CLI tool command naming and flag conventions
- How to handle long-running agent operations in TUI display

</decisions>

<specifics>
## Specific Ideas

- "The flows work great, we are just changing how the operator works" — preserve demo experience
- Agent visibility is key — show what Claude is doing in real-time during demo

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 32-integration-demo*
*Context gathered: 2026-01-28*
