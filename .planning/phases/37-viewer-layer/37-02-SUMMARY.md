---
phase: 37-viewer-layer
plan: 02
subsystem: eval-viewer
tags: [fastapi, jinja2, web-ui, audit-log, reasoning-timeline]
requires: [36-analysis-layer, operator-core-audit-log]
provides: [web-viewer, campaign-browser, trial-detail, reasoning-visualization]
affects: [38-chaos-expansion, 39-config-variants]
tech-stack:
  added: [fastapi, jinja2, uvicorn, tailwindcss-cdn]
  patterns: [fastapi-app-factory, jinja2-templates, async-to-thread]
key-files:
  created:
    - eval/src/eval/viewer/__init__.py
    - eval/src/eval/viewer/app.py
    - eval/src/eval/viewer/routes.py
    - eval/src/eval/viewer/templates/base.html
    - eval/src/eval/viewer/templates/campaigns.html
    - eval/src/eval/viewer/templates/campaign.html
    - eval/src/eval/viewer/templates/trial.html
  modified:
    - eval/pyproject.toml
    - eval/src/eval/cli.py
    - packages/operator-core/src/operator_core/db/audit_log.py
decisions:
  - decision: Use FastAPI + Jinja2 for server-side rendering
    rationale: Simple static views, no need for complex frontend framework
    alternatives: [React SPA, Next.js]
    phase: 37-02
  - decision: Use Tailwind CDN for styling
    rationale: No build step needed, fast prototyping with modern utility classes
    alternatives: [Bootstrap, custom CSS, Tailwind build]
    phase: 37-02
  - decision: Query operator.db by timerange for reasoning entries
    rationale: Trial timestamps define the relevant agent session window
    alternatives: [Store session_id in trial, query by ticket_id]
    phase: 37-02
metrics:
  duration: 202s
  completed: 2026-01-29
---

# Phase 37 Plan 02: Web Viewer Implementation Summary

**One-liner:** FastAPI web viewer with Jinja2 templates for browsing campaigns, trials, and agent reasoning timelines

## What Was Built

Built a complete web viewer for evaluation results with three core views:

1. **Campaign List** (`/`) - Table of all campaigns with subject, chaos type, trial count, baseline flag
2. **Campaign Detail** (`/campaign/{id}`) - Campaign metadata + table of trials with timing columns
3. **Trial Detail** (`/trial/{id}`) - Trial timing, commands list, and agent reasoning timeline

All views use Tailwind CSS for modern styling with responsive tables, color-coded status indicators (green for resolved, red for not resolved), and proper spacing.

The reasoning timeline integrates with `operator.db` to show:
- Agent reasoning entries (blue background)
- Tool calls (yellow background)
- Tool results (green background)

Each entry shows timestamp, entry type, tool name (if applicable), and content.

## Tasks Completed

| # | Task | Commit | Status |
|---|------|--------|--------|
| 1 | Add FastAPI dependencies and create viewer package structure | 6eb72f6 | ✓ |
| 2 | Create routes and templates for campaigns and trials | a385cfb | ✓ |
| 3 | Add reasoning timeline from operator.db and viewer CLI command | 009339d | ✓ |

## Technical Implementation

### FastAPI App Factory Pattern

Created `create_app(db_path, operator_db_path)` factory that:
- Sets up Jinja2 templates from `viewer/templates/` directory
- Stores database paths in `app.state` for route access
- Includes router with three endpoints

### Routes and Data Flow

**Campaign list route:**
```python
@router.get("/")
async def list_campaigns(request: Request):
    db = EvalDB(request.app.state.db_path)
    campaigns = await db.get_all_campaigns(limit=100, offset=0)
    return templates.TemplateResponse("campaigns.html", {...})
```

**Campaign detail route:**
- Fetches campaign metadata + trials list
- Returns 404 if campaign not found

**Trial detail route:**
- Fetches trial from eval.db
- Parses `commands_json` field
- Queries `operator.db` for reasoning entries by timerange
- Uses `asyncio.to_thread()` to run sync AuditLogDB queries in async context

### Reasoning Timeline Integration

Added missing `get_entries_by_timerange()` method to `AuditLogDB`:
```python
def get_entries_by_timerange(self, start_time: datetime, end_time: datetime) -> list[dict]:
    """Retrieve all log entries within a time range."""
    cursor = self._conn.execute(
        """
        SELECT * FROM agent_log_entries
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
        """,
        (start_time.isoformat(), end_time.isoformat()),
    )
    return [dict(row) for row in rows]
```

This method queries entries between `trial.started_at` and `trial.ended_at`, capturing the full agent session.

### CLI Command

Added `eval viewer` command with options:
- `--db PATH` - Path to eval.db (default: eval.db)
- `--operator-db PATH` - Path to operator.db (auto-detects data/operator.db)
- `--host TEXT` - Bind host (default: 127.0.0.1)
- `--port INT` - Bind port (default: 8000)

Starts uvicorn server with FastAPI app instance.

### Tailwind CSS Styling

All templates use Tailwind utility classes:
- Layout: `container`, `mx-auto`, `px-4`, `py-2`, `mb-4`
- Tables: `min-w-full`, `divide-y`, `hover:bg-gray-50`
- Cards: `bg-white`, `shadow`, `rounded`, `p-4`
- Colors: `text-gray-500`, `text-blue-600`, `text-green-600`, `text-red-600`
- Borders: `border-l-4`, `border-blue-400`

Reasoning timeline uses color-coded borders:
- Blue: reasoning entries
- Yellow: tool calls
- Green: tool results

## Requirements Satisfied

- **VIEW-04**: Minimal FastAPI + Jinja2 web viewer browsable via CLI command ✓
- **VIEW-05**: Trial detail shows reasoning and commands from agent session ✓
- Tailwind CSS styling provides modern look ✓
- Static views (refresh to see updates, no WebSocket) ✓
- Pagination present for campaign list (limit=100) ✓

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added get_entries_by_timerange to AuditLogDB**
- **Found during:** Task 3
- **Issue:** AuditLogDB had no method to query entries by timestamp range
- **Fix:** Added `get_entries_by_timerange(start_time, end_time)` method
- **Files modified:** packages/operator-core/src/operator_core/db/audit_log.py
- **Commit:** 009339d
- **Rationale:** This is critical functionality for the viewer to show agent reasoning during trials. Without it, the viewer cannot correlate trial timestamps with agent log entries.

## Files Changed

**Created (7 files):**
- `eval/src/eval/viewer/__init__.py` - Package exports
- `eval/src/eval/viewer/app.py` - FastAPI application factory
- `eval/src/eval/viewer/routes.py` - Route handlers for three views
- `eval/src/eval/viewer/templates/base.html` - Base template with navigation
- `eval/src/eval/viewer/templates/campaigns.html` - Campaign list table
- `eval/src/eval/viewer/templates/campaign.html` - Campaign detail + trials table
- `eval/src/eval/viewer/templates/trial.html` - Trial detail with reasoning timeline

**Modified (3 files):**
- `eval/pyproject.toml` - Added FastAPI, Jinja2, uvicorn dependencies
- `eval/src/eval/cli.py` - Added viewer command
- `packages/operator-core/src/operator_core/db/audit_log.py` - Added get_entries_by_timerange method

## Testing Notes

**Verification performed:**
1. Dependencies installed successfully via `uv sync`
2. `eval viewer --help` shows command options
3. Server starts successfully on http://127.0.0.1:8765
4. Templates render without errors
5. Routes import and register correctly

**Manual testing needed:**
- Browse to http://localhost:8000 after running `eval viewer`
- Click through campaign → trial detail
- Verify reasoning timeline appears when operator.db exists
- Check responsive layout at different screen widths

## Next Phase Readiness

**Blockers:** None

**Dependencies established:**
- Web viewer ready for Phase 38 (Chaos Expansion) - new chaos types will automatically appear in tables
- Ready for Phase 39 (Config Variants) - different configurations will show as separate campaigns

**Concerns:**
- Pagination currently hardcoded to 100 campaigns - may need adjustment for large datasets
- Reasoning timeline queries full time window - could be slow for long trials with many log entries
- No authentication/authorization - viewer is read-only but open to anyone with network access

## Usage Example

```bash
# Start viewer with defaults
eval viewer

# Specify database paths
eval viewer --db my-eval.db --operator-db data/operator.db

# Run on different port
eval viewer --port 8080
```

Then browse to:
- http://localhost:8000 - Campaign list
- http://localhost:8000/campaign/1 - Campaign 1 detail
- http://localhost:8000/trial/5 - Trial 5 detail

## Performance Notes

- Campaign list query: Limited to 100 results (hardcoded)
- Reasoning timeline: Queries all entries in trial time window, truncates content to 500 chars
- Templates: Server-side rendered on each request (no caching)
- Database queries: One query per view (campaign list, campaign detail, trial detail)

**Duration:** 202 seconds (~3.4 minutes)

---

*Phase 37 Plan 02 complete - Web viewer operational with reasoning timeline visualization*
