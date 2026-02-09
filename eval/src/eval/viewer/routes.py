"""Route handlers for eval viewer."""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from eval.runner.db import EvalDBProtocol, get_db
from eval.types import get_chaos_description, safe_json_loads

router = APIRouter()


async def _get_viewer_db(request: Request) -> EvalDBProtocol:
    """Get the appropriate database backend from app state."""
    return await get_db(
        remote=getattr(request.app.state, 'remote', False),
        db_path=getattr(request.app.state, 'db_path', None),
        db_url=getattr(request.app.state, 'db_url', None),
    )


@router.get("/", response_class=HTMLResponse)
async def list_campaigns(request: Request):
    """List all campaigns."""
    db = await _get_viewer_db(request)
    try:
        campaigns = await db.get_all_campaigns(limit=100, offset=0)

        return request.app.state.templates.TemplateResponse(
            "campaigns.html",
            {"request": request, "campaigns": campaigns},
        )
    finally:
        if hasattr(db, 'close'):
            await db.close()


@router.get("/campaign/{campaign_id}", response_class=HTMLResponse)
async def get_campaign(request: Request, campaign_id: int):
    """Show campaign detail with trial list."""
    db = await _get_viewer_db(request)
    try:
        campaign = await db.get_campaign(campaign_id)
        if campaign is None:
            return HTMLResponse(content="Campaign not found", status_code=404)

        trials = await db.get_trials(campaign_id)

        # Add chaos description and trial outcomes
        chaos_description = campaign.name

        # Parse topology and generate SVG
        topology_svg = ""
        if campaign.topology_json:
            try:
                from eval.viewer.svg import render_topology_svg
                topology = json.loads(campaign.topology_json)
                topology_svg = render_topology_svg(topology)
            except (json.JSONDecodeError, Exception):
                pass

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
                "topology_svg": topology_svg,
            },
        )
    finally:
        if hasattr(db, 'close'):
            await db.close()


@router.get("/trial/{trial_id}", response_class=HTMLResponse)
async def get_trial(request: Request, trial_id: int):
    """Show trial detail with reasoning timeline."""
    import asyncio

    db = await _get_viewer_db(request)
    try:
        return await _render_trial(request, db, trial_id)
    finally:
        if hasattr(db, 'close'):
            await db.close()


async def _render_trial(request: Request, db: EvalDBProtocol, trial_id: int):
    """Render trial detail page (extracted for cleanup wrapper)."""
    import asyncio

    trial = await db.get_trial(trial_id)
    if trial is None:
        return HTMLResponse(content="Trial not found", status_code=404)

    # Parse commands and chaos metadata from JSON
    raw_commands = safe_json_loads(trial.commands_json, [])
    if not isinstance(raw_commands, list):
        raw_commands = []
    chaos_meta = safe_json_loads(trial.chaos_metadata)
    if not isinstance(chaos_meta, dict):
        chaos_meta = {}

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
    from eval.analysis.scoring import compute_duration_seconds
    timing = {}
    detect_sec = compute_duration_seconds(trial.chaos_injected_at, trial.ticket_created_at)
    if detect_sec is not None:
        timing["detect_seconds"] = detect_sec
    resolve_sec = compute_duration_seconds(
        trial.ticket_created_at or "", trial.resolved_at
    )
    if resolve_sec is not None:
        timing["resolve_seconds"] = resolve_sec

    # Fetch reasoning entries, agent conclusion, and monitor detection
    # Priority: stored operator_data_json in trial record, then live operator.db fallback
    reasoning_entries = []
    monitor_detection = None
    agent_conclusion = None

    # Try stored operator data first (captures monitoring story even after operator.db is deleted)
    stored_operator_data = {}
    if trial.operator_data_json and trial.operator_data_json != "{}":
        try:
            stored_operator_data = json.loads(trial.operator_data_json)
        except (json.JSONDecodeError, TypeError):
            pass

    if stored_operator_data:
        # Use stored data - no need for operator.db
        if "monitor_detection" in stored_operator_data:
            det = stored_operator_data["monitor_detection"]
            monitor_detection = {
                "violation_type": det.get("invariant_name", ""),
                "violation_details": det.get("message", ""),
                "detected_at": det.get("first_seen_at", ""),
            }

        if "agent_session" in stored_operator_data:
            sess = stored_operator_data["agent_session"]
            if sess.get("outcome_summary"):
                agent_conclusion = {
                    "session_id": sess.get("session_id", ""),
                    "status": sess.get("status", ""),
                    "outcome_summary": sess.get("outcome_summary", ""),
                }

        if "reasoning_entries" in stored_operator_data:
            prev_ts = None
            for e in stored_operator_data["reasoning_entries"]:
                # Extract reasoning from tool_params
                reasoning = None
                if e.get("entry_type") == "tool_call" and e.get("tool_params"):
                    try:
                        params = json.loads(e["tool_params"]) if isinstance(e["tool_params"], str) else e["tool_params"]
                        reasoning = params.get("reasoning")
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Calculate elapsed time
                curr_ts = e.get("timestamp")
                elapsed_seconds = compute_duration_seconds(prev_ts or "", curr_ts) if curr_ts and prev_ts else None
                if curr_ts:
                    prev_ts = curr_ts

                reasoning_entries.append({
                    "entry_type": e.get("entry_type", ""),
                    "content": e.get("content", ""),
                    "tool_name": e.get("tool_name"),
                    "timestamp": e.get("timestamp"),
                    "reasoning": reasoning,
                    "elapsed_seconds": elapsed_seconds,
                })

    elif (operator_db_path := request.app.state.operator_db_path) and operator_db_path.exists():
        import sqlite3

        def get_ticket_and_session():
            """Query ticket and agent session for this trial."""
            from eval.types import parse_iso_datetime

            try:
                conn = sqlite3.connect(operator_db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Convert trial UTC times to local time for comparison
                # (operator.db stores local time without timezone)
                trial_start = parse_iso_datetime(trial.started_at)
                trial_end = parse_iso_datetime(trial.ended_at)

                # Convert to local time strings (without timezone) for SQLite comparison
                local_start = trial_start.astimezone().replace(tzinfo=None).isoformat()
                local_end = trial_end.astimezone().replace(tzinfo=None).isoformat()

                # Find ticket created during trial (use first_seen_at which is in local time)
                cursor.execute("""
                    SELECT id, invariant_name, message, first_seen_at as detected_at
                    FROM tickets
                    WHERE first_seen_at BETWEEN ? AND ?
                    ORDER BY first_seen_at ASC
                    LIMIT 1
                """, (local_start, local_end))
                ticket_row = cursor.fetchone()

                ticket_info = None
                session_info = None

                if ticket_row:
                    ticket_id = ticket_row["id"]
                    ticket_info = {
                        "violation_type": ticket_row["invariant_name"],
                        "violation_details": ticket_row["message"],
                        "detected_at": ticket_row["detected_at"],
                    }

                    # Find agent session for this ticket
                    cursor.execute("""
                        SELECT session_id, status, outcome_summary, started_at, ended_at
                        FROM agent_sessions
                        WHERE ticket_id = ?
                        ORDER BY started_at DESC
                        LIMIT 1
                    """, (ticket_id,))
                    session_row = cursor.fetchone()

                    if session_row and session_row["outcome_summary"]:
                        session_info = {
                            "session_id": session_row["session_id"],
                            "status": session_row["status"],
                            "outcome_summary": session_row["outcome_summary"],
                        }

                conn.close()
                return ticket_info, session_info
            except Exception as e:
                return None, None

        def get_reasoning_entries(session_id: str | None, local_start: str, local_end: str):
            """Get reasoning entries by session_id or time range."""
            try:
                conn = sqlite3.connect(operator_db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if session_id:
                    # Prefer querying by session_id (more reliable)
                    cursor.execute("""
                        SELECT entry_type, content, raw_content, tool_name, tool_params, timestamp
                        FROM agent_log_entries
                        WHERE session_id = ?
                        ORDER BY timestamp ASC
                    """, (session_id,))
                else:
                    # Fallback to time range
                    cursor.execute("""
                        SELECT entry_type, content, raw_content, tool_name, tool_params, timestamp
                        FROM agent_log_entries
                        WHERE timestamp BETWEEN ? AND ?
                        ORDER BY timestamp ASC
                    """, (local_start, local_end))

                rows = cursor.fetchall()
                conn.close()

                entries = []
                prev_ts = None
                for e in rows:
                    # Get full content (prefer raw_content if available)
                    content = e["raw_content"] or e["content"] or ""

                    # For tool_calls, extract reasoning from tool_params
                    reasoning = None
                    if e["entry_type"] == "tool_call" and e["tool_params"]:
                        try:
                            params = json.loads(e["tool_params"])
                            reasoning = params.get("reasoning")
                        except:
                            pass

                    # Calculate elapsed time from previous entry
                    curr_ts = e["timestamp"]
                    elapsed_seconds = compute_duration_seconds(prev_ts or "", curr_ts) if curr_ts and prev_ts else None
                    if curr_ts:
                        prev_ts = curr_ts

                    entries.append({
                        "entry_type": e["entry_type"],
                        "content": content,
                        "tool_name": e["tool_name"],
                        "timestamp": e["timestamp"],
                        "reasoning": reasoning,
                        "elapsed_seconds": elapsed_seconds,
                    })
                return entries
            except Exception:
                return []

        try:
            ticket_info, session_info = await asyncio.to_thread(get_ticket_and_session)
            monitor_detection = ticket_info
            agent_conclusion = session_info

            # Get reasoning entries
            trial_start = parse_iso_datetime(trial.started_at)
            trial_end = parse_iso_datetime(trial.ended_at)
            local_start = trial_start.astimezone().replace(tzinfo=None).isoformat()
            local_end = trial_end.astimezone().replace(tzinfo=None).isoformat()

            session_id = session_info["session_id"] if session_info else None
            reasoning_entries = await asyncio.to_thread(
                get_reasoning_entries, session_id, local_start, local_end
            )
        except Exception:
            pass

    # Extract reasoning from commands for display with elapsed time calculation
    commands_with_reasoning = []
    prev_timestamp = None

    for cmd in raw_commands:
        if isinstance(cmd, dict):
            tool_params = cmd.get("tool_params", "")
            command_str = ""
            reasoning = ""
            try:
                params = json.loads(tool_params) if isinstance(tool_params, str) else tool_params
                command_str = params.get("command", "")
                reasoning = params.get("reasoning", "")
            except:
                command_str = str(cmd)

            timestamp = cmd.get("timestamp", "")
            elapsed_seconds = compute_duration_seconds(prev_timestamp or "", timestamp) if timestamp and prev_timestamp else None
            if timestamp:
                prev_timestamp = timestamp

            commands_with_reasoning.append({
                "command": command_str,
                "reasoning": reasoning,
                "timestamp": timestamp,
                "elapsed_seconds": elapsed_seconds,
            })
        elif isinstance(cmd, str):
            commands_with_reasoning.append({
                "command": cmd,
                "reasoning": "",
                "timestamp": "",
                "elapsed_seconds": None,
            })

    return request.app.state.templates.TemplateResponse(
        "trial.html",
        {
            "request": request,
            "trial": trial,
            "commands": commands,
            "commands_with_reasoning": commands_with_reasoning,
            "chaos_meta": chaos_meta,
            "chaos_description": chaos_description,
            "timing": timing,
            "monitor_detection": monitor_detection,
            "agent_conclusion": agent_conclusion,
            "reasoning_entries": reasoning_entries,
        },
    )
