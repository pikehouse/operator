---
phase: 09-cluster-health-display
plan: 01
subsystem: tui
tags: [health, polling, rich, async, pd-api]

dependency-graph:
  requires: [07, 08]  # TUI foundation, subprocess management
  provides: [ClusterHealthPoller, health-data-types, formatting-functions]
  affects: [09-02, 10, 11]  # TUI integration, demo flow, fault workflow

tech-stack:
  added: []  # No new dependencies, uses existing httpx, rich, asyncio
  patterns:
    - "Dataclass for immutable health snapshots"
    - "Enum for health states"
    - "Async polling with Event coordination"
    - "Rich markup for color-coded display"

key-files:
  created:
    - packages/operator-core/src/operator_core/tui/health.py
  modified:
    - packages/operator-core/src/operator_core/tui/__init__.py

decisions:
  - decision: "Use synthetic node names (tikv-1, pd-1) from store/member IDs"
    rationale: "Consistency across demo runs regardless of actual hostnames"
  - decision: "Immutable ClusterHealth snapshots with atomic reference assignment"
    rationale: "Thread-safe reads without locks per RESEARCH.md Pattern 3"
  - decision: "Silent failure on PD API errors"
    rationale: "Per RESEARCH.md Pitfall 2, don't crash on API unavailability"

metrics:
  duration: "2m 8s"
  completed: "2026-01-25"
---

# Phase 9 Plan 1: ClusterHealthPoller and Health Data Types Summary

ClusterHealthPoller with async PD API polling, immutable health snapshots, and Rich markup formatting for color-coded cluster status display.

## What Was Built

### 1. Health Data Types
- **NodeHealth enum**: UP, DOWN, OFFLINE, UNKNOWN states for mapping PD API responses
- **NodeStatus dataclass**: Single node representation with id, name, type, health, address
- **ClusterHealth dataclass**: Complete cluster snapshot with nodes list, has_issues flag, timestamp

### 2. Formatting Functions
- **format_node_status()**: Rich markup with green bullet (up), red cross (down), yellow cross (offline)
- **format_cluster_panel()**: Full panel content with TiKV/PD sections
- **parse_monitor_output_for_detection()**: Monitor output parser for "violations" vs "all passing"

### 3. ClusterHealthPoller Class
- Async run() loop polling PD API at configurable interval (default 2s)
- Fetches from `/pd/api/v1/stores` (TiKV health) and `/pd/api/v1/health` (PD member health)
- Creates immutable ClusterHealth snapshots on each poll
- Detection state management for border highlighting
- Graceful shutdown via asyncio.Event

## Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `packages/operator-core/src/operator_core/tui/health.py` | Health poller and data types | 366 |
| `packages/operator-core/src/operator_core/tui/__init__.py` | Package exports | 43 |

## Commits

| Hash | Message |
|------|---------|
| 9f714ca | feat(09-01): add ClusterHealthPoller and health data types |

## Verification Results

All verifications passed:
- Data types (NodeHealth, NodeStatus, ClusterHealth) work correctly
- format_node_status() returns Rich markup with Unicode symbols
- parse_monitor_output_for_detection() correctly parses "all passing" and "violations"
- ClusterHealthPoller instantiation and state methods work correctly
- All components exported from operator_core.tui package

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

### Ready for 09-02 (TUI Integration)
- ClusterHealthPoller exported and ready for TUIController integration
- format_cluster_panel() ready for rendering in cluster panel
- parse_monitor_output_for_detection() ready for monitor output scanning

### Dependencies Satisfied
- TUI-02: Health indicators (data types and formatting complete)
- TUI-04: Detection highlighting (detection state management in poller)

### No Blockers
All components tested and verified. Ready for integration in plan 09-02.
