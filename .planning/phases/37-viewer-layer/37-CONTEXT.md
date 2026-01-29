# Phase 37: Viewer Layer - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Developer can browse campaigns and drill into trial details via CLI and web UI. Includes `eval list`, `eval show <id>`, and a web viewer. Real-time updates and advanced filtering are out of scope.

</domain>

<decisions>
## Implementation Decisions

### CLI Output Format
- Compact table for `eval list` — one line per campaign: ID, date, subject, trials, aggregate scores
- JSON output via `--json` flag for machine-readable output (no CSV)
- Commands displayed inline as indented list in `eval show`
- No colors — plain text output, works everywhere

### Web UI Framework
- FastAPI + Jinja templates — Python templates, no JS build step
- Started via CLI command: `eval viewer` launches local server
- Tailwind CSS for styling — modern look, utility classes
- Static views only — refresh to see updates (no WebSocket/polling)

### Information Hierarchy
- Campaign list: ID, date, subject, trial count, aggregate scores
- Campaign detail (`eval show <campaign_id>`): full analysis — scores, command metrics, duration stats, plus trial list
- Trial detail (`eval show <trial_id>`): everything — timing, scores, outcome, commands, agent reasoning, subject state before/after chaos
- Pagination for long lists in both CLI and web UI

### Reasoning Display
- Timeline view in web UI — chronological list of thoughts and actions
- Summary only — Haiku-summarized reasoning entries, compact
- Commands in code blocks (monospace styling)
- Command output shown only on errors — success outputs hidden

### Claude's Discretion
- Pagination defaults (page size)
- Timeline entry styling
- Error output formatting
- Table column widths and alignment

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

*Phase: 37-viewer-layer*
*Context gathered: 2026-01-29*
