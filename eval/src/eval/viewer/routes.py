"""Route handlers for eval viewer."""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from eval.runner.db import EvalDB

router = APIRouter()


def get_chaos_description(chaos_type: str, chaos_meta: dict | None = None) -> str:
    """Get human-readable chaos type description."""
    descriptions = {
        "node_kill": "Container killed with SIGKILL",
        "latency": "Network latency injection",
        "disk_pressure": "Disk space exhaustion",
        "network_partition": "Network partition from peers",
    }
    desc = descriptions.get(chaos_type, chaos_type)

    if chaos_meta:
        if chaos_type == "latency" and chaos_meta.get("min_ms") is not None:
            desc = f"Network latency ({chaos_meta['min_ms']}-{chaos_meta['max_ms']}ms)"
        elif chaos_type == "disk_pressure" and chaos_meta.get("fill_percent") is not None:
            desc = f"Disk filled to {chaos_meta['fill_percent']}%"
        elif chaos_type == "node_kill" and chaos_meta.get("target_container"):
            desc = f"Kill {chaos_meta['target_container']} (SIGKILL)"

    return desc


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

    # Add chaos description and trial outcomes
    chaos_description = get_chaos_description(campaign.chaos_type)

    # Enrich trials with outcome status
    trial_data = []
    for t in trials:
        outcome = "success" if t.resolved_at else "timeout"
        trial_data.append({
            "trial": t,
            "outcome": outcome,
        })

    return request.app.state.templates.TemplateResponse(
        "campaign.html",
        {
            "request": request,
            "campaign": campaign,
            "trials": trial_data,
            "chaos_description": chaos_description,
        },
    )


@router.get("/trial/{trial_id}", response_class=HTMLResponse)
async def get_trial(request: Request, trial_id: int):
    """Show trial detail with reasoning timeline."""
    import asyncio

    db = EvalDB(request.app.state.db_path)
    await db.ensure_schema()

    trial = await db.get_trial(trial_id)
    if trial is None:
        return HTMLResponse(content="Trial not found", status_code=404)

    # Parse commands and chaos metadata from JSON
    raw_commands = json.loads(trial.commands_json) if trial.commands_json else []
    chaos_meta = json.loads(trial.chaos_metadata) if trial.chaos_metadata else {}

    # Extract command strings from various formats
    commands = []
    for cmd in raw_commands:
        if isinstance(cmd, str):
            commands.append(cmd)
        elif isinstance(cmd, dict):
            # Try to get command from tool_params (JSON string)
            tool_params = cmd.get("tool_params", "")
            if tool_params:
                try:
                    params = json.loads(tool_params) if isinstance(tool_params, str) else tool_params
                    commands.append(params.get("command", str(cmd)))
                except json.JSONDecodeError:
                    commands.append(cmd.get("command", str(cmd)))
            else:
                commands.append(cmd.get("command", str(cmd)))
        else:
            commands.append(str(cmd))

    # Get chaos description
    chaos_type = chaos_meta.get("chaos_type", "unknown")
    chaos_description = get_chaos_description(chaos_type, chaos_meta)

    # Calculate timing deltas
    timing = {}
    if trial.ticket_created_at and trial.chaos_injected_at:
        from datetime import datetime, timezone
        try:
            chaos_time = datetime.fromisoformat(trial.chaos_injected_at.replace("Z", "+00:00"))
            ticket_time = datetime.fromisoformat(trial.ticket_created_at.replace("Z", "+00:00"))
            if chaos_time.tzinfo is None:
                chaos_time = chaos_time.replace(tzinfo=timezone.utc)
            if ticket_time.tzinfo is None:
                ticket_time = ticket_time.replace(tzinfo=timezone.utc)
            timing["detect_seconds"] = (ticket_time - chaos_time).total_seconds()
        except Exception:
            pass

    if trial.resolved_at and trial.ticket_created_at:
        from datetime import datetime, timezone
        try:
            ticket_time = datetime.fromisoformat(trial.ticket_created_at.replace("Z", "+00:00"))
            resolve_time = datetime.fromisoformat(trial.resolved_at.replace("Z", "+00:00"))
            if ticket_time.tzinfo is None:
                ticket_time = ticket_time.replace(tzinfo=timezone.utc)
            if resolve_time.tzinfo is None:
                resolve_time = resolve_time.replace(tzinfo=timezone.utc)
            timing["resolve_seconds"] = (resolve_time - ticket_time).total_seconds()
        except Exception:
            pass

    # Fetch reasoning entries and monitor detection if operator.db path is available
    reasoning_entries = []
    monitor_detection = None
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

        def get_monitor_detection():
            """Query tickets table for what the monitor detected."""
            import sqlite3
            from datetime import datetime

            try:
                conn = sqlite3.connect(operator_db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Find ticket created around trial time
                start_time = datetime.fromisoformat(trial.started_at.replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(trial.ended_at.replace("Z", "+00:00"))

                cursor.execute("""
                    SELECT violation_type, violation_details, created_at
                    FROM tickets
                    WHERE created_at BETWEEN ? AND ?
                    ORDER BY created_at ASC
                    LIMIT 1
                """, (start_time.isoformat(), end_time.isoformat()))

                row = cursor.fetchone()
                conn.close()

                if row:
                    return {
                        "violation_type": row["violation_type"],
                        "violation_details": row["violation_details"],
                        "detected_at": row["created_at"],
                    }
            except Exception:
                pass
            return None

        try:
            reasoning_entries = await asyncio.to_thread(get_entries)
        except Exception:
            pass

        try:
            monitor_detection = await asyncio.to_thread(get_monitor_detection)
        except Exception:
            pass

    return request.app.state.templates.TemplateResponse(
        "trial.html",
        {
            "request": request,
            "trial": trial,
            "commands": commands,
            "chaos_meta": chaos_meta,
            "chaos_description": chaos_description,
            "timing": timing,
            "monitor_detection": monitor_detection,
            "reasoning_entries": reasoning_entries,
        },
    )
