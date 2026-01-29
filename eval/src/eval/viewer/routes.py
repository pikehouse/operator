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
    import json

    db = EvalDB(request.app.state.db_path)
    await db.ensure_schema()

    trial = await db.get_trial(trial_id)
    if trial is None:
        return HTMLResponse(content="Trial not found", status_code=404)

    # Parse commands from JSON
    commands = json.loads(trial.commands_json) if trial.commands_json else []

    # Reasoning entries will be added in Task 3
    reasoning_entries = []

    return request.app.state.templates.TemplateResponse(
        "trial.html",
        {
            "request": request,
            "trial": trial,
            "commands": commands,
            "reasoning_entries": reasoning_entries,
        },
    )
