"""Route handlers for eval viewer."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from eval.runner.db import EvalDB

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_campaigns(request: Request):
    """List all campaigns."""
    db = EvalDB(request.app.state.db_path)
    await db.ensure_schema()
    campaigns = await db.get_all_campaigns(limit=100, offset=0)

    return request.app.state.templates.TemplateResponse(
        "campaigns.html",
        {"request": request, "campaigns": campaigns},
    )


@router.get("/campaign/{campaign_id}", response_class=HTMLResponse)
async def get_campaign(request: Request, campaign_id: int):
    """Show campaign detail with trial list."""
    db = EvalDB(request.app.state.db_path)
    await db.ensure_schema()

    campaign = await db.get_campaign(campaign_id)
    if campaign is None:
        return HTMLResponse(content="Campaign not found", status_code=404)

    trials = await db.get_trials(campaign_id)

    return request.app.state.templates.TemplateResponse(
        "campaign.html",
        {"request": request, "campaign": campaign, "trials": trials},
    )


@router.get("/trial/{trial_id}", response_class=HTMLResponse)
async def get_trial(request: Request, trial_id: int):
    """Show trial detail with reasoning timeline."""
    import asyncio
    import json

    db = EvalDB(request.app.state.db_path)
    await db.ensure_schema()

    trial = await db.get_trial(trial_id)
    if trial is None:
        return HTMLResponse(content="Trial not found", status_code=404)

    # Parse commands from JSON
    commands = json.loads(trial.commands_json) if trial.commands_json else []

    # Fetch reasoning entries if operator.db path is available
    reasoning_entries = []
    operator_db_path = request.app.state.operator_db_path

    if operator_db_path and operator_db_path.exists():
        from operator_core.db.audit_log import AuditLogDB

        def get_entries():
            """Sync function to query audit log."""
            from datetime import datetime

            with AuditLogDB(operator_db_path) as audit_db:
                # Query entries within trial time window
                start_time = datetime.fromisoformat(trial.started_at.replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(trial.ended_at.replace("Z", "+00:00"))

                entries = audit_db.get_entries_by_timerange(start_time, end_time)
                return [
                    {
                        "entry_type": e["entry_type"],
                        "content": e["content"][:500] if len(e["content"]) > 500 else e["content"],
                        "tool_name": e["tool_name"],
                        "timestamp": e["timestamp"],
                    }
                    for e in entries
                ]

        try:
            reasoning_entries = await asyncio.to_thread(get_entries)
        except Exception:
            # Silently skip if audit log query fails
            pass

    return request.app.state.templates.TemplateResponse(
        "trial.html",
        {
            "request": request,
            "trial": trial,
            "commands": commands,
            "reasoning_entries": reasoning_entries,
        },
    )
