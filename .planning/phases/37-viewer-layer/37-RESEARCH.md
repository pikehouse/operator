# Phase 37: Viewer Layer - Research

**Researched:** 2026-01-29
**Domain:** CLI list/show commands and FastAPI web viewer for browsing evaluation data
**Confidence:** HIGH

## Summary

This research covers building a viewer layer that lets developers browse campaigns and drill into trial details via both CLI and web UI. The CLI adds `eval list` and `eval show <id>` commands that display data in compact table format with `--json` flag for machine-readable output. The web UI uses FastAPI with Jinja2 templates and Tailwind CSS via CDN for styling.

The existing codebase provides strong foundations: the `eval/` package has complete data models (`Campaign`, `Trial`, `TrialScore`, `CampaignSummary`), async database access via `EvalDB`, and CLI patterns using Typer with `--json` flags. The `operator-core` package provides agent session audit data via `agent_log_entries` table with `entry_type` values of `reasoning`, `tool_call`, and `tool_result`.

Key findings:
- FastAPI + Jinja2 is straightforward: install `jinja2`, mount `/static`, create `templates/` directory
- Tailwind CSS v4 Play CDN works with a single `<script>` tag, no npm required
- Plain text table output should use manual formatting (no Rich tables) for consistent, no-color output
- Pagination uses standard `offset`/`limit` query parameters with reasonable defaults (10-20 items per page)
- Reasoning display combines `reasoning` and `tool_call`/`tool_result` entries from `agent_log_entries` table

**Primary recommendation:** Add CLI commands using existing Typer patterns with manual table formatting for plain text. Create minimal FastAPI app in `eval/src/eval/viewer/` with Jinja2 templates, Tailwind CDN, and offset/limit pagination. Display reasoning timeline from `agent_log_entries` filtered by session_id linked through trial data.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typer | 0.21.0+ | CLI commands (list, show, viewer) | Already in project for eval CLI |
| fastapi | 0.115.0+ | Web API and HTML endpoints | Industry standard for Python APIs |
| jinja2 | 3.1.0+ | Server-side HTML templating | Official FastAPI integration |
| uvicorn | 0.32.0+ | ASGI server for FastAPI | Standard for FastAPI deployment |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiosqlite | 0.20.0+ | Read trial data from eval.db | Already in project from Phase 35 |
| pydantic | 2.0.0+ | Data models and JSON serialization | Already in project |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Tailwind CDN | Installed Tailwind via npm | CDN avoids npm/build step, context decision specifies CDN |
| Manual table formatting | Rich Table with no_color | Rich adds visual noise even in plain mode; manual is cleaner |
| FastAPI + Jinja | Flask | FastAPI already used elsewhere (ratelimiter), consistent stack |
| htmx | Plain HTML forms | htmx out of scope per context (static views only) |

**Installation:**
```bash
cd eval
uv add fastapi jinja2 uvicorn
```

## Architecture Patterns

### Recommended Project Structure
```
eval/src/eval/
├── viewer/
│   ├── __init__.py
│   ├── app.py              # FastAPI application setup
│   ├── routes.py           # Route handlers for campaigns, trials
│   ├── db_queries.py       # Database query functions
│   └── templates/
│       ├── base.html       # Base template with Tailwind CDN
│       ├── campaigns.html  # Campaign list page
│       ├── campaign.html   # Campaign detail page
│       └── trial.html      # Trial detail with reasoning timeline
├── cli.py                  # Add list, show, viewer commands
└── ...
```

### Pattern 1: FastAPI with Jinja2Templates

**What:** Setup FastAPI application with Jinja2 templating and static file serving.

**When to use:** Any FastAPI app that needs to render HTML pages.

**Example:**
```python
# Source: https://fastapi.tiangolo.com/advanced/templates/
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

app = FastAPI()

# Templates directory relative to this file
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

@app.get("/campaigns", response_class=HTMLResponse)
async def list_campaigns(request: Request, offset: int = 0, limit: int = 20):
    campaigns = await get_campaigns(offset=offset, limit=limit)
    return templates.TemplateResponse(
        request=request,
        name="campaigns.html",
        context={"campaigns": campaigns, "offset": offset, "limit": limit}
    )
```

### Pattern 2: Tailwind CSS via CDN (No Build Step)

**What:** Include Tailwind CSS v4 via CDN script tag, works without npm or build process.

**When to use:** Development, prototypes, simple internal tools where build complexity is not justified.

**Example:**
```html
<!-- Source: https://tailwindcss.com/docs/installation/play-cdn -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Eval Viewer</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <main class="container mx-auto px-4 py-8">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

### Pattern 3: Plain Text Table Output (No Colors)

**What:** Manual string formatting for CLI table output that works everywhere without color codes.

**When to use:** Context decision specifies "No colors - plain text output, works everywhere".

**Example:**
```python
# Plain text table formatting (no Rich)
def format_campaign_table(campaigns: list[CampaignSummary]) -> str:
    """Format campaigns as plain text table."""
    # Header
    header = f"{'ID':<6} {'Date':<12} {'Subject':<12} {'Trials':<7} {'Win Rate':<10}"
    separator = "-" * len(header)

    lines = [header, separator]
    for c in campaigns:
        date_str = c.created_at[:10]  # YYYY-MM-DD
        win_pct = f"{c.win_rate:.0%}"
        lines.append(f"{c.campaign_id:<6} {date_str:<12} {c.subject_name:<12} {c.trial_count:<7} {win_pct:<10}")

    return "\n".join(lines)
```

### Pattern 4: Offset/Limit Pagination

**What:** Standard pagination using offset and limit query parameters for both CLI and web.

**When to use:** Any list endpoint that may return many items.

**Example:**
```python
# Database query with pagination
async def get_campaigns(
    db: EvalDB,
    offset: int = 0,
    limit: int = 20
) -> list[CampaignSummary]:
    """Get paginated list of campaigns with summary stats."""
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT c.*, COUNT(t.id) as actual_trial_count
            FROM campaigns c
            LEFT JOIN trials t ON t.campaign_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        )
        rows = await cursor.fetchall()
        # ... convert to CampaignSummary objects
```

### Pattern 5: CLI Subcommand with Viewer Launch

**What:** Add `eval viewer` command that starts local FastAPI server.

**When to use:** When CLI needs to launch web interface.

**Example:**
```python
# Source: Project pattern (typer + uvicorn)
import typer
import uvicorn

@app.command()
def viewer(
    port: int = typer.Option(8080, "--port", "-p", help="Port to listen on"),
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
):
    """Launch web viewer for browsing campaigns and trials."""
    import os
    os.environ["EVAL_DB_PATH"] = str(db_path)

    from eval.viewer.app import create_app
    web_app = create_app()

    print(f"Starting viewer at http://localhost:{port}")
    uvicorn.run(web_app, host="127.0.0.1", port=port, log_level="warning")
```

### Pattern 6: Reasoning Timeline Display

**What:** Query agent_log_entries for session, display chronologically with entry_type styling.

**When to use:** Trial detail page showing agent reasoning and actions.

**Example:**
```python
# Query reasoning entries for a trial
def get_trial_reasoning(operator_db_path: Path, session_id: str) -> list[dict]:
    """Get reasoning timeline entries for a session."""
    conn = sqlite3.connect(operator_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        """
        SELECT entry_type, content, tool_name, tool_params, exit_code, timestamp
        FROM agent_log_entries
        WHERE session_id = ?
        ORDER BY timestamp ASC
        """,
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# Template display
{% for entry in timeline %}
<div class="border-l-2 pl-4 mb-4
    {% if entry.entry_type == 'reasoning' %}border-blue-500
    {% elif entry.entry_type == 'tool_call' %}border-green-500
    {% else %}border-gray-500{% endif %}">

    <div class="text-xs text-gray-500">{{ entry.timestamp }}</div>

    {% if entry.entry_type == 'reasoning' %}
        <div class="font-medium text-blue-800">Claude</div>
        <p class="text-gray-700">{{ entry.content }}</p>
    {% elif entry.entry_type == 'tool_call' %}
        <div class="font-medium text-green-800">{{ entry.tool_name }}</div>
        <pre class="bg-gray-800 text-gray-100 p-2 rounded text-sm overflow-x-auto">{{ entry.tool_params }}</pre>
    {% elif entry.entry_type == 'tool_result' %}
        {% if entry.exit_code != 0 %}
        <div class="font-medium text-red-800">Error (exit {{ entry.exit_code }})</div>
        <pre class="bg-red-50 text-red-800 p-2 rounded text-sm">{{ entry.content }}</pre>
        {% endif %}
    {% endif %}
</div>
{% endfor %}
```

### Anti-Patterns to Avoid

- **Using Rich tables for plain text:** Rich adds complexity and potential color codes even in "plain" mode. Manual formatting is cleaner.
- **Installing Tailwind via npm:** Context decision specifies CDN for simplicity. NPM adds build step complexity.
- **WebSocket/polling for updates:** Context specifies "static views only - refresh to see updates". Keep it simple.
- **Showing all tool_result output:** Context specifies "command output shown only on errors". Filter by exit_code != 0.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Web framework | Custom WSGI/ASGI | FastAPI | Handles routing, templates, validation |
| HTML templating | String concatenation | Jinja2 | Template inheritance, escaping, filters |
| CSS framework | Custom styles | Tailwind CDN | Utility classes, consistent design |
| Server runner | subprocess.Popen | uvicorn | Handles signals, reloading, workers |
| URL building | Manual path concat | url_for() in Jinja2 | Handles route names, parameters |

**Key insight:** The web viewer is an internal tool, not a production service. Favor simplicity over performance optimization. Tailwind CDN and FastAPI's development mode are perfectly adequate.

## Common Pitfalls

### Pitfall 1: Database Path Configuration Between CLI and Web

**What goes wrong:** CLI passes `--db` path but web app doesn't receive it, defaults to wrong database.

**Why it happens:** FastAPI app is created separately, doesn't have access to CLI context.

**How to avoid:**
- Pass database path via environment variable (`EVAL_DB_PATH`)
- Set env var in CLI before importing/starting web app
- Have web app read from env with sensible default

**Warning signs:**
- Web viewer shows no campaigns when CLI works fine
- Different data between CLI and web

### Pitfall 2: Sync vs Async Database Access in FastAPI

**What goes wrong:** Blocking calls in async route handlers cause performance issues.

**Why it happens:** EvalDB uses aiosqlite (async), but operator.db access (for reasoning) uses sync sqlite3.

**How to avoid:**
- Use async database calls (aiosqlite) for eval.db queries
- For operator.db reasoning queries, use `asyncio.to_thread()` to run sync code
- Keep it simple: sync sqlite3 with `to_thread()` is fine for this use case

**Warning signs:**
- Web viewer hangs on trial detail page
- Slow response times under minimal load

### Pitfall 3: Jinja2 Template Path Resolution

**What goes wrong:** TemplateNotFoundError even though template files exist.

**Why it happens:** Relative paths are resolved from cwd, not from Python module location.

**How to avoid:**
- Use `Path(__file__).parent / "templates"` to get absolute path
- Verify templates directory exists at startup
- Log the resolved path for debugging

**Warning signs:**
- Works in development but fails when installed as package
- Different behavior depending on working directory

### Pitfall 4: Missing Session ID Link Between Trial and Reasoning

**What goes wrong:** Can't show reasoning for a trial because there's no session_id stored in trials table.

**Why it happens:** Trial data comes from eval.db, reasoning comes from operator.db. Need to link them.

**How to avoid:**
- Extract session_id from agent_sessions table using ticket_id or timestamp range
- Store session_id in trials table during trial execution (Phase 35 enhancement)
- Fall back to timestamp-based matching if session_id not available

**Warning signs:**
- Trial detail shows commands but no reasoning
- "No reasoning data available" message

**Current state investigation:** Checking the trial runner code, commands are extracted by timestamp from operator.db. The same approach can find agent_sessions:
```python
# Find session that was running during trial
SELECT session_id FROM agent_sessions
WHERE started_at <= ? AND (ended_at IS NULL OR ended_at >= ?)
ORDER BY started_at DESC LIMIT 1
```

### Pitfall 5: Pagination Edge Cases

**What goes wrong:** "Next" link shows even when no more items, or offset goes negative.

**Why it happens:** Not checking total count or validating offset bounds.

**How to avoid:**
- Query total count separately for pagination UI
- Validate offset >= 0, limit > 0 in route handlers
- Disable "Previous" when offset=0, "Next" when offset+limit >= total

**Warning signs:**
- Empty pages with "Previous" links that go nowhere
- URL shows negative offset values

## Code Examples

Verified patterns from official sources:

### FastAPI Template Setup
```python
# Source: https://fastapi.tiangolo.com/advanced/templates/
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="Eval Viewer")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="campaigns.html",
        context={"title": "Campaigns"}
    )
```

### Tailwind CSS v4 CDN Base Template
```html
<!-- Source: https://tailwindcss.com/docs/installation/play-cdn -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Eval Viewer{% endblock %}</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>
<body class="bg-gray-50 min-h-screen">
    <nav class="bg-white shadow-sm border-b">
        <div class="max-w-7xl mx-auto px-4 py-3">
            <a href="/" class="text-lg font-semibold text-gray-900">Eval Viewer</a>
        </div>
    </nav>
    <main class="max-w-7xl mx-auto px-4 py-6">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

### Typer CLI with JSON Flag (Existing Pattern)
```python
# Source: eval/src/eval/cli.py (existing pattern)
@app.command()
def list(
    db_path: Path = typer.Option(Path("eval.db"), "--db", help="Path to eval database"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    offset: int = typer.Option(0, "--offset", help="Skip first N campaigns"),
    limit: int = typer.Option(20, "--limit", help="Maximum campaigns to show"),
):
    """List all campaigns with summary stats."""
    async def run():
        db = EvalDB(db_path)
        await db.ensure_schema()
        return await get_campaign_summaries(db, offset=offset, limit=limit)

    campaigns = asyncio.run(run())

    if json_output:
        # Use pydantic serialization
        print(json.dumps([c.model_dump() for c in campaigns], indent=2))
        return

    # Plain text table
    print(format_campaign_table(campaigns))
```

### uvicorn Launch from Typer
```python
# Source: uvicorn documentation
import uvicorn

@app.command()
def viewer(
    port: int = typer.Option(8080, "--port", "-p"),
    db_path: Path = typer.Option(Path("eval.db"), "--db"),
):
    """Launch web viewer for browsing campaigns and trials."""
    import os
    os.environ["EVAL_DB_PATH"] = str(db_path.resolve())

    print(f"Starting viewer at http://localhost:{port}")
    print(f"Database: {db_path}")
    print("Press Ctrl+C to stop")

    uvicorn.run(
        "eval.viewer.app:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flask templates | FastAPI + Jinja2 | FastAPI 0.65+ (2021) | Async support, better typing |
| Bootstrap CDN | Tailwind CDN | Tailwind v3+ (2022), v4 (2024) | Utility-first, smaller bundle |
| Tailwind npm install | Tailwind Play CDN | Tailwind v3.0 (2022) | No build step for prototypes |
| Rich tables for CLI | Manual formatting | N/A | Plain text per context decision |

**Deprecated/outdated:**
- **Flask for new projects:** FastAPI preferred for async support and automatic docs
- **Bootstrap:** Tailwind provides more flexibility with utility classes
- **npm-installed Tailwind for simple tools:** CDN sufficient for internal viewers

## Open Questions

Things that couldn't be fully resolved:

1. **Session ID linkage between trial and reasoning**
   - What we know: Trials store commands by timestamp, not session_id
   - What's unclear: How to reliably find the session for a given trial
   - Recommendation: Query agent_sessions by timestamp overlap. If trial.started_at falls within session.started_at and session.ended_at, that's the matching session. May need to add session_id to trials table in future enhancement.

2. **Operator.db path configuration**
   - What we know: eval.db is configurable via --db flag. Reasoning data is in operator.db.
   - What's unclear: Where is operator.db relative to eval.db? Same directory? Configurable?
   - Recommendation: Add `--operator-db` flag to viewer command, default to `data/operator.db` (same as trial runner). Store in env var for web app access.

3. **Pagination defaults**
   - What we know: Context says "Claude's discretion" for page size
   - What's unclear: Optimal page size for usability
   - Recommendation: Default to 20 for CLI list, 20 for web campaign list, 10 for trial list within campaign. These are reasonable defaults that show enough context without overwhelming.

## Sources

### Primary (HIGH confidence)
- FastAPI Templates documentation - https://fastapi.tiangolo.com/advanced/templates/
- Tailwind CSS v4 Play CDN - https://tailwindcss.com/docs/installation/play-cdn
- Typer CLI documentation - https://typer.tiangolo.com/tutorial/printing/
- Existing eval/src/eval/cli.py patterns (--json flag, typer options)
- Existing operator_core/db/schema.py (agent_log_entries table)

### Secondary (MEDIUM confidence)
- FastAPI pagination patterns - https://sqlmodel.tiangolo.com/tutorial/fastapi/limit-and-offset/
- uvicorn deployment - https://www.uvicorn.org/deployment/
- Python tabulate vs manual formatting - https://pypi.org/project/tabulate/

### Tertiary (LOW confidence)
- NO_COLOR standard for plain text - https://no-color.org/

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries standard for Python web dev, verified with official docs
- Architecture: HIGH - Patterns verified with FastAPI docs, aligned with context decisions
- Pitfalls: MEDIUM - Based on common FastAPI/Jinja issues, session linkage is project-specific

**Research date:** 2026-01-29
**Valid until:** ~90 days (stable domain - FastAPI, Jinja2, Tailwind APIs stable)

**Context decisions honored:**
- CLI: `eval list` shows campaigns with compact table
- CLI: `--json` flag for machine-readable output (no CSV)
- CLI: Commands displayed inline as indented list in `eval show`
- CLI: No colors - plain text output
- Web: FastAPI + Jinja templates (no JS build step)
- Web: `eval viewer` command launches local server
- Web: Tailwind CSS via CDN
- Web: Static views only (refresh to see updates)
- Reasoning: Timeline view, summary only (Haiku-summarized), commands in code blocks
- Reasoning: Command output shown only on errors
