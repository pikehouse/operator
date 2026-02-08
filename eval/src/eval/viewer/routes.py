"""Route handlers for eval viewer."""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from eval.runner.db import EvalDB, EvalDBProtocol

router = APIRouter()


async def _get_viewer_db(request: Request) -> EvalDBProtocol:
    """Get the appropriate database backend from app state."""
    if getattr(request.app.state, 'remote', False):
        from eval.runner.db_postgres import PostgresDB
        db = PostgresDB(request.app.state.db_url)
        await db.ensure_schema()
        return db
    else:
        db = EvalDB(request.app.state.db_path)
        await db.ensure_schema()
        return db


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
    raw_commands = json.loads(trial.commands_json) if trial.commands_json else []
    # Handle double-encoded JSON (JSONB round-trip can double-encode strings)
    if isinstance(raw_commands, str):
        try:
            raw_commands = json.loads(raw_commands)
        except (json.JSONDecodeError, TypeError):
            raw_commands = []
    chaos_meta_raw = json.loads(trial.chaos_metadata) if trial.chaos_metadata else {}
    # Handle double-encoded JSON or non-dict values
    if isinstance(chaos_meta_raw, str):
        try:
            chaos_meta_raw = json.loads(chaos_meta_raw)
        except (json.JSONDecodeError, TypeError):
            chaos_meta_raw = {}
    chaos_meta = chaos_meta_raw if isinstance(chaos_meta_raw, dict) else {}

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
                elapsed_seconds = None
                curr_ts = e.get("timestamp")
                if curr_ts and prev_ts:
                    try:
                        from datetime import datetime, timezone
                        curr_time = datetime.fromisoformat(curr_ts.replace("Z", "+00:00"))
                        prev_time = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                        if curr_time.tzinfo is None:
                            curr_time = curr_time.replace(tzinfo=timezone.utc)
                        if prev_time.tzinfo is None:
                            prev_time = prev_time.replace(tzinfo=timezone.utc)
                        elapsed_seconds = (curr_time - prev_time).total_seconds()
                    except Exception:
                        pass
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
            from datetime import datetime, timezone

            try:
                conn = sqlite3.connect(operator_db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Convert trial UTC times to local time for comparison
                # (operator.db stores local time without timezone)
                trial_start = datetime.fromisoformat(trial.started_at.replace("Z", "+00:00"))
                trial_end = datetime.fromisoformat(trial.ended_at.replace("Z", "+00:00"))

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
                    elapsed_seconds = None
                    curr_ts = e["timestamp"]
                    if curr_ts and prev_ts:
                        try:
                            from datetime import datetime, timezone
                            curr_time = datetime.fromisoformat(curr_ts.replace("Z", "+00:00"))
                            prev_time = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                            if curr_time.tzinfo is None:
                                curr_time = curr_time.replace(tzinfo=timezone.utc)
                            if prev_time.tzinfo is None:
                                prev_time = prev_time.replace(tzinfo=timezone.utc)
                            elapsed_seconds = (curr_time - prev_time).total_seconds()
                        except Exception:
                            pass

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
            from datetime import datetime
            trial_start = datetime.fromisoformat(trial.started_at.replace("Z", "+00:00"))
            trial_end = datetime.fromisoformat(trial.ended_at.replace("Z", "+00:00"))
            local_start = trial_start.astimezone().replace(tzinfo=None).isoformat()
            local_end = trial_end.astimezone().replace(tzinfo=None).isoformat()

            session_id = session_info["session_id"] if session_info else None
            reasoning_entries = await asyncio.to_thread(
                get_reasoning_entries, session_id, local_start, local_end
            )
        except Exception:
            pass

    # Extract reasoning from commands for display with elapsed time calculation
    from datetime import datetime, timezone

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
            elapsed_seconds = None

            # Calculate elapsed time from previous command
            if timestamp and prev_timestamp:
                try:
                    curr_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    prev_time = datetime.fromisoformat(prev_timestamp.replace("Z", "+00:00"))
                    if curr_time.tzinfo is None:
                        curr_time = curr_time.replace(tzinfo=timezone.utc)
                    if prev_time.tzinfo is None:
                        prev_time = prev_time.replace(tzinfo=timezone.utc)
                    elapsed_seconds = (curr_time - prev_time).total_seconds()
                except Exception:
                    pass

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
