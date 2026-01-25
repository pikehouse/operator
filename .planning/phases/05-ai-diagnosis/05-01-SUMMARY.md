---
phase: 05-ai-diagnosis
plan: 01
subsystem: agent
tags: [anthropic, pydantic, structured-output, claude]

# Dependency graph
requires:
  - phase: 04-monitor-loop
    provides: Ticket dataclass with diagnosis field, TicketDB for persistence
provides:
  - DiagnosisOutput Pydantic model for Claude structured output
  - Alternative model for differential diagnosis
  - format_diagnosis_markdown() for human-readable output
  - TicketDB.update_diagnosis() method for storing diagnoses
affects: [05-02, 05-03, 05-04]

# Tech tracking
tech-stack:
  added: [anthropic>=0.40.0]
  patterns: [pydantic Field() descriptions for Claude guidance, structured output with differential diagnosis]

key-files:
  created:
    - packages/operator-core/src/operator_core/agent/__init__.py
    - packages/operator-core/src/operator_core/agent/diagnosis.py
  modified:
    - packages/operator-core/pyproject.toml
    - packages/operator-core/src/operator_core/db/tickets.py

key-decisions:
  - "Field descriptions guide Claude's structured output generation"
  - "Markdown as storage format for human-readable diagnosis"
  - "Status transitions to 'diagnosed' when AI attaches analysis"

patterns-established:
  - "Pydantic models with Field(description=...) for Claude structured output"
  - "format_*_markdown() helper for human-readable rendering"

# Metrics
duration: 1min 21s
completed: 2026-01-25
---

# Phase 05 Plan 01: Diagnosis Data Models Summary

**DiagnosisOutput Pydantic model with differential diagnosis support and TicketDB.update_diagnosis() for storing AI-generated markdown**

## Performance

- **Duration:** 1min 21s
- **Started:** 2026-01-25T01:50:33Z
- **Completed:** 2026-01-25T01:51:54Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added anthropic SDK dependency (>=0.40.0) for Claude API access
- Created DiagnosisOutput Pydantic model with Field descriptions to guide Claude's structured output
- Built Alternative model for differential diagnosis (hypothesis/supporting/contradicting/conclusion)
- Implemented format_diagnosis_markdown() for CLI rendering
- Added TicketDB.update_diagnosis() to persist AI diagnosis and transition ticket status

## Task Commits

Each task was committed atomically:

1. **Task 1: Add anthropic dependency and create agent package** - `ed1bb3d` (feat)
2. **Task 2: Create DiagnosisOutput Pydantic model** - `76e3f1f` (feat)
3. **Task 3: Add update_diagnosis method to TicketDB** - `6b325f8` (feat)

## Files Created/Modified
- `packages/operator-core/pyproject.toml` - Added anthropic>=0.40.0 dependency
- `packages/operator-core/src/operator_core/agent/__init__.py` - Module docstring describing agent purpose
- `packages/operator-core/src/operator_core/agent/diagnosis.py` - DiagnosisOutput, Alternative models, format_diagnosis_markdown()
- `packages/operator-core/src/operator_core/db/tickets.py` - Added update_diagnosis() method

## Decisions Made
- Field descriptions in Pydantic models serve dual purpose: Python docs and Claude output guidance
- Diagnosis stored as markdown per CONTEXT.md (human-readable first)
- Status transitions from 'open'/'acknowledged' to 'diagnosed' when AI attaches analysis

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Data models ready for 05-02 (context gathering)
- TicketDB integration ready for storing diagnoses
- Pydantic model ready for Claude structured output in 05-03 (Claude integration)

---
*Phase: 05-ai-diagnosis*
*Completed: 2026-01-25*
