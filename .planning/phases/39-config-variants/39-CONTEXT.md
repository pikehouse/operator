# Phase 39: Config Variants - Context

**Gathered:** 2026-01-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Test different agent configurations (model, system prompt, tools) and compare their performance across chaos scenarios. One variant per campaign — run multiple campaigns to compare variants.

</domain>

<decisions>
## Implementation Decisions

### Variant definition
- Variants have three fields: model, system_prompt, tools_config
- Variants require a human-readable name field (e.g., "haiku-minimal-prompt")
- system_prompt is an inline string (not file path reference)

### Campaign integration
- One variant per campaign (top-level `variant:` field in campaign YAML)
- Campaign references variant by name (e.g., `variant: haiku-v1`)
- If campaign omits variant field, use a default variant
- Trial records store variant name for filtering/comparison

### Comparison output
- Simple table format: Variant | Avg TTR | Avg TTD | Success Rate | Command Count
- Balanced scorecard — show all metrics equally, user interprets tradeoffs
- Aggregate metrics only (no per-chaos-type breakdown)
- No automated recommendations — just show data, user decides

### Variant management
- Variants stored as YAML files in `eval/variants/` directory
- One file per variant (e.g., `eval/variants/haiku-v1.yaml`)
- Include `default.yaml` as working example using current agent config

### Claude's Discretion
- tools_config structure (what fields, what controls)
- Whether to add CLI commands for variant listing
- Default variant contents
- Exact table formatting for comparison output

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

*Phase: 39-config-variants*
*Context gathered: 2026-01-30*
