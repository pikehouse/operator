---
phase: "05"
plan: "02"
subsystem: "agent"
tags: ["context-gathering", "prompt-engineering", "ai-diagnosis"]

dependency_graph:
  requires:
    - "05-01 (DiagnosisOutput model)"
    - "02-05 (TiKVSubject observations)"
    - "04-01 (TicketDB)"
  provides:
    - "DiagnosisContext dataclass"
    - "ContextGatherer class"
    - "SYSTEM_PROMPT constant"
    - "build_diagnosis_prompt function"
  affects:
    - "05-03 (Agent runner uses context gatherer and prompt builder)"

tech_stack:
  added: []
  patterns:
    - "Context assembly pattern for AI prompting"
    - "TYPE_CHECKING imports to avoid circular dependencies"

key_files:
  created:
    - "packages/operator-core/src/operator_core/agent/context.py"
    - "packages/operator-core/src/operator_core/agent/prompt.py"
  modified:
    - "packages/operator-core/src/operator_core/agent/__init__.py"

decisions: []

metrics:
  duration: "1m23s"
  completed: "2026-01-25"
---

# Phase 05 Plan 02: Context Gathering and Prompt Building Summary

Context gatherer assembles metrics, topology, and similar tickets; prompt builder creates structured markdown for differential diagnosis.

## What Was Built

### DiagnosisContext Dataclass
Central data structure holding all context needed for diagnosis:
- `ticket`: The ticket being diagnosed
- `metric_snapshot`: Metrics captured at violation time
- `stores`: Current cluster topology (all TiKV stores)
- `cluster_metrics`: Store/region counts, leader distribution
- `log_tail`: Last N lines from affected component (stubbed as None for v1)
- `similar_tickets`: Past diagnoses for same invariant

### ContextGatherer Class
Assembles DiagnosisContext from multiple data sources:
- Uses TiKVSubject for cluster observations (`get_stores`, `get_cluster_metrics`)
- Uses TicketDB to find similar past tickets by invariant_name
- `_fetch_log_tail` stubbed for v1 (returns None)
- Limits similar tickets to 3 most recent diagnosed ones

### SYSTEM_PROMPT Constant
1188-character system prompt that elicits differential diagnosis:
- Timeline, affected components, metric readings
- Primary diagnosis with confidence in natural language
- Alternatives considered with supporting/contradicting evidence
- Recommended action with severity, commands, and risks
- Clinical/technical SRE runbook tone

### build_diagnosis_prompt Function
Builds structured markdown prompt with sections:
- Ticket details (invariant, store, message, timing, occurrence count)
- Metrics at violation time (if available)
- Cluster topology (stores, regions, leader distribution)
- Recent logs (if log_tail is not None)
- Similar past tickets (with diagnosis previews)

## Key Implementation Details

**TYPE_CHECKING import pattern**: Used `TYPE_CHECKING` to import TiKVSubject and TicketDB types without creating circular imports at runtime.

**Similar ticket lookup**: Queries diagnosed tickets with same invariant_name, excludes the current ticket, limits to 3 most recent.

**Log tail stubbed**: `_fetch_log_tail` returns None for v1. Future implementation will fetch from container logs.

**Diagnosis preview truncation**: Similar ticket diagnoses truncated to 300 chars in prompt to manage context window.

## Deviations from Plan

None - plan executed exactly as written.

## Commits

| Hash | Message |
|------|---------|
| d33dc08 | feat(05-02): add DiagnosisContext and ContextGatherer |
| f39c2f4 | feat(05-02): add system prompt and prompt builder |
| 3050b00 | feat(05-02): update agent package exports |

## Next Phase Readiness

Ready for 05-03 (Agent runner). All context gathering and prompt building components exported from agent package.

**Provides to 05-03:**
- `ContextGatherer(subject, db)` for context assembly
- `build_diagnosis_prompt(context)` for prompt construction
- `SYSTEM_PROMPT` for Claude system message
