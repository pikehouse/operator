# Phase 20: E2E Demo & Chaos - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate that AI can diagnose rate limiter anomalies without system-specific prompts by demonstrating chaos injection and diagnosis for both TiKV and rate limiter subjects. This phase creates shared demo infrastructure that works with any subject.

</domain>

<decisions>
## Implementation Decisions

### Chaos Scenarios
- Two chaos scenarios for rate limiter: counter drift and ghost allowing
- Counter drift: Use Redis command blocking (DEBUG SLEEP or pause Redis container)
- Ghost allowing: 2x limit burst (send 2N requests when limit is N)
- No node failure scenario — keep demo focused on the two core anomalies
- Abstract chaos interface: Common chaos runner with subject-specific fault configs
- TiKV and rate limiter use same chaos abstraction with different config files

### Demo Flow
- Chapter definitions in Python modules (Chapter dataclasses with functions)
- Separate entry points: demo/ratelimiter.py and demo/tikv.py
- Shared TUI infrastructure lives in demo/ directory (not a pip package)
- Chapter advancement: configurable per chapter (some auto-advance, some wait for keypress)
- Setup chapters auto-advance, observation chapters wait for user

### AI Diagnosis Validation
- Success criterion: AI identifies anomaly type (mentions symptom correctly)
- "Without system-specific prompts" means: subject provides domain terminology, core reasoning stays generic
- No log capture — human observer validates in real-time during demo
- If AI fails to identify anomaly: pause demo for review (debug opportunity)

### Observability During Demo
- TUI only — no Grafana dashboard required
- Panel layout mirrors TiKV: cluster health, daemon output, AI panel, invariant status
- Live metrics shown in TUI: poll Prometheus every 1-2s for requests/sec, latency
- Chaos visualization: status indicator showing current state (normal/injecting/recovering)

### Claude's Discretion
- Exact TUI panel dimensions and styling
- Prometheus polling interval (1-2s range)
- Chapter timing for auto-advance scenarios
- Chaos config file format

</decisions>

<specifics>
## Specific Ideas

- "Demo TUI etc. should be a common artifact, and can run for different subjects / scripts (chapter sets)"
- Same panel structure regardless of subject — swap the data source, not the layout
- Entry points are simple: load subject-specific chapters, pass to shared TUI runner

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 20-e2e-demo-chaos*
*Context gathered: 2026-01-27*
