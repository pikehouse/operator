# Phase 5: AI Diagnosis - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Claude analyzes tickets and produces structured reasoning about distributed system issues. The AI demonstrates real diagnostic thinking — not just "something is wrong" but "here's what's happening, here are the options, here's why I'd choose this one." V1 is observe-only; actions are recommendations, not automated.

</domain>

<decisions>
## Implementation Decisions

### Diagnosis output structure
- Structured sections format: Timeline, Affected Components, Metric Readings
- Nuanced confidence via natural language ("The evidence strongly suggests...", "This could be...")
- Clinical/technical tone — SRE runbook style, precise, terse, metric-focused
- Store as markdown — human-readable first, render in CLI

### Context gathering strategy
- Metric snapshot only — current values at violation time, no extended history
- Include raw log tail — last N lines from affected components
- Include similar ticket history — past diagnoses for same invariant/store to show patterns
- Include full cluster topology — all stores, regions, relationships for correlation

### Options-considered format
- Differential diagnosis style — ranked possibilities with supporting/contradicting evidence
- Summarized evidence — brief mention of key metrics without exhaustive listing
- Show top 2-3 alternative hypotheses alongside primary diagnosis
- "Insufficient data" is an acceptable conclusion — Claude explicitly states what's missing

### Action recommendations
- Explicit severity levels: Critical / Warning / Info
- Both conceptual and commands — description plus copy-paste ready CLI commands where applicable
- "Wait and observe" is a valid explicit recommendation
- Always include potential risks/side effects for every recommended action

### Claude's Discretion
- Exact structure of Timeline/Affected Components/Metric Readings sections
- How many log lines to include in raw tail
- Definition of "similar" tickets for history lookup
- When to use "insufficient data" vs low-confidence conclusion

</decisions>

<specifics>
## Specific Ideas

- Diagnosis should read like an SRE would write it — professional, metric-backed, actionable
- The "options considered" section is the core value — shows AI is actually reasoning, not pattern matching
- Risk warnings on actions prevent operators from blindly following recommendations

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-ai-diagnosis*
*Context gathered: 2026-01-24*
