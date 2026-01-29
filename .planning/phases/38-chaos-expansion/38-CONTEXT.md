# Phase 38: Chaos Expansion - Context

**Gathered:** 2026-01-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend TiKV chaos injection with latency, disk pressure, and network partition chaos types. Enable batch campaign execution via YAML configuration file. Supports `eval run campaign config.yaml` command.

</domain>

<decisions>
## Implementation Decisions

### Chaos Parameters
- Latency chaos: range-based configuration (min_ms, max_ms) — random delay within range
- Disk pressure: fill percentage — relative to current available space (e.g., fill_percent: 90)
- Network partition: node isolation granularity — isolate specific TiKV node from cluster
- Strict validation: reject invalid params (e.g., >100% disk fill) before trial starts

### Campaign YAML Format
- Matrix expansion for trial specification: subjects × chaos types generates all combinations
- Baselines opt-in: `include_baseline: true` flag, default false
- Defaults + overrides pattern: global defaults, per-chaos-type param overrides
- Auto-generated naming: `campaign-{timestamp}-{hash}`, `trial-{subject}-{chaos}-{index}`

### Chaos Sequencing
- Configurable parallelism: `parallel: N` — run up to N trials concurrently (default 1)
- Configurable cooldown: `cooldown_seconds: N` — optional pause between trials
- Fresh start each trial: tear down and recreate subject between trials

### Failure Handling
- Chaos injection failure: mark trial as failed, record error, continue campaign
- Always continue campaign regardless of trial failures
- Resumable campaigns: persist completed trials, can resume from interruption point
- Immediate stop on cancel: Ctrl+C kills current trial immediately (no graceful finish)

### Claude's Discretion
- Chaos duration/auto-revert strategy
- Exact YAML schema structure and field names
- Internal retry logic for transient failures
- Progress reporting during campaign execution

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

*Phase: 38-chaos-expansion*
*Context gathered: 2026-01-29*
