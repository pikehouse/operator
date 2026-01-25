# Phase 6: Chaos Demo - Context

**Gathered:** 2026-01-25
**Status:** Ready for planning

<domain>
## Phase Boundary

End-to-end demonstration showing AI diagnosis of injected faults. The demo runs the full operator pipeline: healthy cluster -> inject fault -> detect -> diagnose -> explain. Core capability is CHAOS-01 (node kill via Docker).

</domain>

<decisions>
## Implementation Decisions

### Demo format
- Single command invocation: `operator demo chaos` runs the whole cycle
- Press-enter prompts at key moments for pacing
- Auto-starts cluster if not running (waits for healthy state)
- Tears down cluster completely when demo finishes

### Fault injection
- Random TiKV store selection each run (not always the same node)
- `docker kill` for hard failure (immediate SIGKILL, simulates sudden crash)
- YCSB load running before fault injection (more realistic scenario)
- Show brief YCSB throughput/latency stats before and after fault

### Output presentation
- Full structured DiagnosisOutput displayed (observation, root cause, evidence, actions)
- Colored terminal output (green success, red failures, yellow warnings)
- Moderate verbosity — stage transitions and key findings, skip low-level details

### Detection timing
- Detection must occur within 30 seconds of fault injection
- Live counter during detection wait: "Waiting for detection... 5s... 10s..."
- Warn and continue if timeout exceeded (don't fail the demo)
- Verify both: ticket created AND invariant shows store down

### Claude's Discretion
- Stage display style (banners vs numbered steps)
- Exact spacing and formatting of output
- How to surface YCSB load stats (table, inline, etc.)
- Monitor loop polling frequency during detection wait

</decisions>

<specifics>
## Specific Ideas

- Demo should feel like a showcase — the AI diagnosis is the star
- Show the full reasoning chain, not just "store is down"
- Load stats help demonstrate real-world impact of the failure

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-chaos-demo*
*Context gathered: 2026-01-25*
