# Phase 4: Monitor Loop - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Automated invariant checking that runs continuously and creates tickets when violations are detected. The monitor loop checks registered invariants at a configurable interval, creates tickets with rich context when violations occur, and manages ticket lifecycle including auto-resolution. AI diagnosis of tickets belongs to Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Ticket lifecycle
- Status transitions: open → acknowledged → diagnosed → resolved
- Tickets contain rich data: violation type, timestamp, store ID, plus metric snapshots at violation time
- Diagnosis is attached directly to the ticket record (single source of truth)
- Auto-resolve when condition clears, but humans can override (keep open while investigating)

### Loop behavior
- Default check interval: 30 seconds
- Long-lived daemon mode: `operator monitor` runs forever, checking periodically
- Multiple violations in same cycle are batched into a single ticket for AI to diagnose together
- Flap detection: if same violation recurs 3+ times in N minutes, note it as flapping

### Ticket deduplication
- "Same violation" defined by: invariant type + store ID
- If violation recurs while ticket is still open: update existing ticket (occurrence count, last_seen timestamp)
- No cooldown after resolution — if it fails again, new ticket immediately
- Batched violations share a batch key — recurrence updates the batched ticket

### CLI/output
- Both CLI commands and log output
- `operator tickets list` — table by default, --json flag for structured output
- `operator tickets resolve <id>` — manual resolution
- `operator tickets hold <id>` — prevent auto-resolve while investigating
- Monitor daemon outputs periodic heartbeat: "Check complete: 3 invariants, all passing"

### Claude's Discretion
- SQLite schema details
- Exact flap detection thresholds (N minutes, recurrence count)
- Log formatting and verbosity levels
- Metric snapshot storage format

</decisions>

<specifics>
## Specific Ideas

- Heartbeat output gives visibility that the loop is running without being noisy
- Batching violations helps AI see correlated issues (store down + high latency likely related)
- Hold command is important for investigation — don't auto-close while debugging

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-monitor-loop*
*Context gathered: 2026-01-24*
