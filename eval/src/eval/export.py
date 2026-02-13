"""Static HTML export for eval campaigns.

Generates a single self-contained HTML file from a campaign's data.
No external dependencies — all CSS/JS is inlined and data is embedded as JSON.
"""

import json
from collections import Counter
from typing import Any

from eval.analysis.scoring import compute_duration_seconds
from eval.runner.db import EvalDBProtocol
from eval.types import Campaign, Trial, get_chaos_description, safe_json_loads


def safe_json_for_script(data: Any) -> str:
    """Serialize data to JSON safe for embedding in <script> tags.

    Escapes sequences that would break out of a script block:
    - </script> (closes the tag)
    - <!-- (opens an HTML comment)
    """
    raw = json.dumps(data, ensure_ascii=False)
    return raw.replace("</", r"<\/").replace("<!--", r"<\!--")


def _enrich_trial(trial: Trial) -> dict[str, Any]:
    """Enrich a single trial with computed fields for export.

    Replicates the enrichment logic from viewer/routes.py but without
    any live operator.db fallback — export is a snapshot of stored data.
    """
    # Parse stored JSON
    chaos_meta = safe_json_loads(trial.chaos_metadata)
    if not isinstance(chaos_meta, dict):
        chaos_meta = {}
    chaos_type = chaos_meta.get("chaos_type", "none")
    is_baseline = chaos_type == "none" or (not chaos_meta)

    # Outcome
    outcome = "success" if trial.resolved_at else "timeout"

    # Chaos description
    chaos_description = get_chaos_description(chaos_type, chaos_meta)

    # Timing
    detect_sec = compute_duration_seconds(trial.chaos_injected_at, trial.ticket_created_at)
    resolve_sec = compute_duration_seconds(trial.chaos_injected_at, trial.resolved_at)

    # Commands with reasoning
    raw_commands = safe_json_loads(trial.commands_json, [])
    if not isinstance(raw_commands, list):
        raw_commands = []
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
            except (json.JSONDecodeError, TypeError):
                command_str = str(cmd)
            timestamp = cmd.get("timestamp", "")
            elapsed = compute_duration_seconds(prev_timestamp or "", timestamp) if timestamp and prev_timestamp else None
            if timestamp:
                prev_timestamp = timestamp
            commands_with_reasoning.append({
                "command": command_str,
                "reasoning": reasoning,
                "timestamp": timestamp,
                "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
            })
        elif isinstance(cmd, str):
            commands_with_reasoning.append({
                "command": cmd,
                "reasoning": "",
                "timestamp": "",
                "elapsed_seconds": None,
            })

    # Monitor detection + agent conclusion from operator_data_json
    monitor_detection = None
    agent_conclusion = None
    reasoning_entries = []

    stored = safe_json_loads(trial.operator_data_json)
    if isinstance(stored, dict) and stored:
        det = stored.get("monitor_detection")
        if isinstance(det, dict):
            monitor_detection = {
                "violation_type": det.get("invariant_name", ""),
                "violation_details": det.get("message", ""),
                "detected_at": det.get("first_seen_at", ""),
            }
        sess = stored.get("agent_session")
        if isinstance(sess, dict) and sess.get("outcome_summary"):
            agent_conclusion = {
                "session_id": sess.get("session_id", ""),
                "status": sess.get("status", ""),
                "outcome_summary": sess.get("outcome_summary", ""),
            }
        if "reasoning_entries" in stored:
            prev_ts = None
            for e in stored["reasoning_entries"]:
                reasoning = None
                if e.get("entry_type") == "tool_call" and e.get("tool_params"):
                    try:
                        params = json.loads(e["tool_params"]) if isinstance(e["tool_params"], str) else e["tool_params"]
                        reasoning = params.get("reasoning")
                    except (json.JSONDecodeError, TypeError):
                        pass
                curr_ts = e.get("timestamp")
                elapsed = compute_duration_seconds(prev_ts or "", curr_ts) if curr_ts and prev_ts else None
                if curr_ts:
                    prev_ts = curr_ts
                reasoning_entries.append({
                    "entry_type": e.get("entry_type", ""),
                    "content": e.get("content", ""),
                    "tool_name": e.get("tool_name"),
                    "timestamp": e.get("timestamp"),
                    "reasoning": reasoning,
                    "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
                })

    # Code diff
    code_diff = None
    final_state = safe_json_loads(trial.final_state)
    if isinstance(final_state, dict):
        code_diff = final_state.get("code_diff")
        cw = final_state.get("code_workspace")
        if not code_diff and isinstance(cw, dict):
            code_diff = cw.get("diff_full") or cw.get("diff", "")

    # DB config diff
    db_config_diff = None
    initial_state = safe_json_loads(trial.initial_state)
    if isinstance(initial_state, dict) and isinstance(final_state, dict):
        init_db = initial_state.get("db_config")
        final_db = final_state.get("db_config")
        if init_db or final_db:
            from eval.analysis.db_config_diff import diff_db_config
            db_config_diff = diff_db_config(init_db, final_db)

    # Group key for trial table grouping
    chaos_params = {k: v for k, v in chaos_meta.items() if k != "chaos_type"}
    group_key = f"{chaos_type}|{json.dumps(chaos_params, sort_keys=True)}" if not is_baseline else "baseline"

    # Behavior timeline
    behavior_phases = []
    if trial.behavior_json:
        try:
            bdata = json.loads(trial.behavior_json)
            if isinstance(bdata, dict) and bdata.get("phases"):
                from eval.analysis.behavior import ACTION_COLORS
                for phase in bdata["phases"]:
                    action_type = phase.get("action_type", "investigate")
                    colors = ACTION_COLORS.get(action_type, ACTION_COLORS["investigate"])
                    behavior_phases.append({
                        "label": phase.get("label", ""),
                        "action_type": action_type,
                        "bg": colors["bg"],
                        "text": colors["text"],
                        "border": colors["border"],
                    })
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": trial.id,
        "campaign_id": trial.campaign_id,
        "outcome": outcome,
        "chaos_type": chaos_type,
        "chaos_description": chaos_description,
        "is_baseline": is_baseline,
        "group_key": group_key,
        "detect_sec": round(detect_sec, 1) if detect_sec is not None else None,
        "resolve_sec": round(resolve_sec, 1) if resolve_sec is not None else None,
        "cmd_count": len(commands_with_reasoning),
        "started_at": trial.started_at,
        "chaos_injected_at": trial.chaos_injected_at,
        "ticket_created_at": trial.ticket_created_at,
        "resolved_at": trial.resolved_at,
        "ended_at": trial.ended_at,
        "commands_with_reasoning": commands_with_reasoning,
        "monitor_detection": monitor_detection,
        "agent_conclusion": agent_conclusion,
        "reasoning_entries": reasoning_entries,
        "code_diff": code_diff or "",
        "db_config_diff": db_config_diff,
        "behavior_phases": behavior_phases,
    }


async def build_export_data(
    db: EvalDBProtocol,
    campaign_id: int,
) -> dict[str, Any]:
    """Gather and enrich all data needed for the HTML export.

    Returns a dict suitable for JSON serialization and embedding in HTML.
    """
    campaign = await db.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    trials = await db.get_trials(campaign_id)

    # Enrich trials
    enriched = [_enrich_trial(t) for t in trials]

    # Sort: non-baselines first by group_key then trial id, baselines last
    enriched.sort(key=lambda x: (x["is_baseline"], x["group_key"], x["id"]))

    # Group metadata
    group_counts = Counter(t["group_key"] for t in enriched)
    prev_group = None
    for item in enriched:
        if item["group_key"] != prev_group:
            item["group_first"] = True
            item["group_size"] = group_counts[item["group_key"]]
            item["group_label"] = item["chaos_description"] if not item["is_baseline"] else "Baseline"
            prev_group = item["group_key"]
        else:
            item["group_first"] = False
            item["group_size"] = 0
            item["group_label"] = ""

    # Summary stats
    success_count = sum(1 for t in enriched if t["outcome"] == "success")
    detect_times = [t["detect_sec"] for t in enriched if t["detect_sec"] is not None]
    resolve_times = [t["resolve_sec"] for t in enriched if t["resolve_sec"] is not None]
    total = len(enriched)

    summary = {
        "total": total,
        "success_count": success_count,
        "win_rate": round(100 * success_count / total) if total else 0,
        "median_detect": round(sorted(detect_times)[len(detect_times) // 2], 1) if detect_times else None,
        "median_resolve": round(sorted(resolve_times)[len(resolve_times) // 2], 1) if resolve_times else None,
    }

    # Topology SVG
    topology_svg = ""
    if campaign.topology_json:
        try:
            from eval.viewer.svg import render_topology_svg
            topology = json.loads(campaign.topology_json)
            topology_svg = render_topology_svg(topology)
        except (json.JSONDecodeError, Exception):
            pass

    return {
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "subject_name": campaign.subject_name,
            "variant_name": campaign.variant_name,
            "baseline": campaign.baseline,
            "trial_count": campaign.trial_count,
            "created_at": campaign.created_at,
        },
        "trials": enriched,
        "summary": summary,
        "topology_svg": topology_svg,
    }


_CSS = """\
:root {
  --bg: #faf9f7;
  --bg-card: #ffffff;
  --bg-hover: #f5f5f4;
  --border: #e7e5e4;
  --border-dark: #d6d3d1;
  --text: #1c1917;
  --text-secondary: #78716c;
  --text-muted: #a8a29e;
  --header-bg: #1c1917;
  --header-text: #fafaf9;
  --header-muted: #a8a29e;
  --green: #16a34a;
  --green-bg: #f0fdf4;
  --red: #dc2626;
  --red-bg: #fef2f2;
  --blue: #2563eb;
  --blue-bg: #eff6ff;
  --orange: #d97706;
  --orange-bg: #fffbeb;
  --purple: #7c3aed;
  --code-bg: #1c1917;
  --code-text: #e7e5e4;
  --diff-add-bg: rgba(22, 163, 74, 0.15);
  --diff-add-text: #4ade80;
  --diff-del-bg: rgba(220, 38, 38, 0.15);
  --diff-del-text: #f87171;
  --diff-hunk-bg: rgba(124, 58, 237, 0.15);
  --diff-hunk-text: #c4b5fd;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: var(--text); background: var(--bg);
  margin: 0; padding: 0; line-height: 1.6;
}
.page-body {
  max-width: 1200px; margin: 0 auto; padding: 24px;
}
.page-header {
  background: var(--header-bg); color: var(--header-text);
  padding: 32px 24px; margin-bottom: 0;
}
.page-header-inner {
  max-width: 1200px; margin: 0 auto;
}
.page-header h1 { font-size: 1.5rem; margin: 0 0 4px; color: var(--header-text); font-weight: 700; letter-spacing: -0.01em; }
.page-header .meta { color: var(--header-muted); font-size: 0.875rem; }
h2 { font-size: 1.15rem; margin: 24px 0 12px; color: var(--text); font-weight: 600; }
h3 { font-size: 1rem; margin: 16px 0 8px; font-weight: 600; }
.meta { color: var(--text-secondary); font-size: 0.875rem; }
.badge {
  display: inline-block; padding: 2px 10px; border-radius: 6px;
  font-size: 0.75rem; font-weight: 600; letter-spacing: 0.01em;
}
.badge-success { background: var(--green-bg); color: var(--green); }
.badge-timeout { background: var(--red-bg); color: var(--red); }
.badge-baseline { background: var(--blue-bg); color: var(--blue); }
.stats-bar {
  display: flex; gap: 16px; flex-wrap: wrap;
  padding: 0; background: none; border: none;
  margin: 16px 0;
}
.stat {
  text-align: center; flex: 1; min-width: 120px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px 12px;
  border-top: 3px solid var(--border-dark);
}
.stat:nth-child(1) { border-top-color: var(--green); }
.stat:nth-child(2) { border-top-color: var(--blue); }
.stat:nth-child(3) { border-top-color: var(--orange); }
.stat:nth-child(4) { border-top-color: var(--purple); }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--text); }
.stat-label { font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; margin-top: 2px; }
.topology-svg { margin: 16px 0; overflow-x: auto; }
.topology-svg svg { max-width: 100%; height: auto; }
table {
  width: 100%; border-collapse: collapse; font-size: 0.875rem;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
  overflow: hidden;
}
th {
  text-align: left; padding: 10px 12px;
  border-bottom: 2px solid var(--border-dark);
  color: var(--text-secondary); font-weight: 600; font-size: 0.8rem;
  text-transform: uppercase; letter-spacing: 0.03em;
  background: var(--bg);
}
td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
tr.clickable { cursor: pointer; transition: background 0.1s; }
tr.clickable:hover { background: var(--bg-hover); }
tr.selected { background: #f5f3ff; }
.group-header td {
  padding: 14px 12px 6px; font-weight: 600; font-size: 0.8rem;
  color: var(--text-secondary); border-bottom: none;
  text-transform: uppercase; letter-spacing: 0.03em;
}
.detail-panel {
  margin-top: 24px; padding: 24px;
  border: 1px solid var(--border); border-left: 3px solid var(--blue);
  border-radius: 8px; background: var(--bg-card); display: none;
}
.detail-panel.visible { display: block; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.detail-section { margin-bottom: 16px; }
.detail-section h3 { margin-top: 0; }
details { margin: 4px 0; }
details > summary {
  cursor: pointer; font-weight: 600; font-size: 0.875rem;
  padding: 8px 0; color: var(--text);
  list-style: none;
}
details > summary::before { content: '\\25B6  '; font-size: 0.7rem; color: var(--text-muted); }
details[open] > summary::before { content: '\\25BC  '; }
.cmd-list { margin: 0; padding: 0; list-style: none; }
.cmd-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
.cmd-command {
  font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
  font-size: 0.8rem; background: var(--code-bg); color: var(--code-text);
  padding: 6px 10px; border-radius: 6px; display: block; word-break: break-all;
}
.cmd-reasoning {
  font-size: 0.8rem; color: var(--text-secondary);
  margin-top: 6px; font-style: italic;
}
.elapsed-badge {
  font-size: 0.7rem; color: var(--text-muted);
  background: var(--bg); padding: 1px 6px; border-radius: 4px;
  margin-left: 8px; border: 1px solid var(--border);
}
.reasoning-entry {
  padding: 10px 0; border-bottom: 1px solid var(--border);
}
.reasoning-type {
  font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
  color: var(--text-muted); letter-spacing: 0.03em;
}
.reasoning-content {
  font-size: 0.85rem; margin-top: 4px; white-space: pre-wrap;
  word-break: break-word; color: var(--text);
}
.diff-block {
  font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
  font-size: 0.8rem; line-height: 1.6; overflow-x: auto;
  border-radius: 8px;
  background: var(--code-bg); padding: 0;
}
.diff-line { padding: 0 12px; margin: 0; white-space: pre; color: var(--code-text); }
.diff-add { background: var(--diff-add-bg); color: var(--diff-add-text); }
.diff-del { background: var(--diff-del-bg); color: var(--diff-del-text); }
.diff-hunk { background: var(--diff-hunk-bg); color: var(--diff-hunk-text); font-weight: 600; }
.db-change { font-size: 0.85rem; padding: 4px 0; }
.db-change-add { color: var(--green); }
.db-change-del { color: var(--red); }
.db-change-mod { color: var(--orange); }
.conclusion-box {
  padding: 14px 16px; background: var(--green-bg); border: 1px solid var(--green);
  border-radius: 8px; font-size: 0.9rem;
}
.conclusion-box.timeout {
  background: var(--red-bg); border-color: var(--red);
}
.empty { color: var(--text-muted); font-style: italic; font-size: 0.85rem; }
.bh-timeline { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.bh-pill {
  display: inline-block; padding: 2px 8px; border-radius: 9999px;
  font-size: 0.75rem; font-weight: 500; white-space: nowrap;
}
.bh-arrow { color: var(--text-muted); font-size: 0.7rem; }
.bh-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.bh-trial-id { font-family: monospace; font-size: 0.8rem; width: 48px; flex-shrink: 0; }
.bh-outcome { flex-shrink: 0; margin-left: auto; }
@media print {
  body { background: #fff; }
  .page-body { max-width: 100%; padding: 12px; }
  .page-header { background: #1c1917; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .detail-panel { display: block !important; break-inside: avoid; }
  tr.clickable:hover { background: none; }
}
@media (max-width: 768px) {
  .detail-grid { grid-template-columns: 1fr; }
  .stats-bar { gap: 12px; }
  .stat { min-width: 100px; }
}
"""

_JS = """\
(function() {
  const DATA = window.__EXPORT_DATA__;
  const campaign = DATA.campaign;
  const trials = DATA.trials;
  const summary = DATA.summary;

  function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function formatTs(iso) {
    if (!iso) return 'N/A';
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch(e) { return iso.slice(0, 19); }
  }

  function shortTs(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleTimeString();
    } catch(e) { return iso.slice(11, 19); }
  }

  function renderBehaviorTimeline(phases) {
    if (!phases || phases.length === 0) return '<span class="empty">no behavior data</span>';
    let out = '';
    for (let i = 0; i < phases.length; i++) {
      const p = phases[i];
      out += `<span class="bh-pill" style="background:${p.bg};color:${p.text};border:1px solid ${p.border}">${esc(p.label)}</span>`;
      if (i < phases.length - 1) out += '<span class="bh-arrow">&rarr;</span>';
    }
    return out;
  }

  // Render campaign header
  const hdr = document.getElementById('campaign-header');
  hdr.innerHTML = `
    <h1>${esc(campaign.name)}</h1>
    <div class="meta">
      Campaign #${campaign.id} &middot; ${esc(campaign.subject_name)} &middot;
      Variant: ${esc(campaign.variant_name)} &middot;
      ${formatTs(campaign.created_at)}
    </div>
  `;

  // Summary stats
  const statsEl = document.getElementById('summary-stats');
  statsEl.innerHTML = `
    <div class="stat"><div class="stat-value">${summary.win_rate}%</div><div class="stat-label">Win Rate</div></div>
    <div class="stat"><div class="stat-value">${summary.success_count}/${summary.total}</div><div class="stat-label">Succeeded</div></div>
    <div class="stat"><div class="stat-value">${summary.median_detect != null ? summary.median_detect + 's' : 'N/A'}</div><div class="stat-label">Median Detect</div></div>
    <div class="stat"><div class="stat-value">${summary.median_resolve != null ? summary.median_resolve + 's' : 'N/A'}</div><div class="stat-label">Median Resolve</div></div>
  `;

  // Topology (pre-rendered SVG)
  if (DATA.topology_svg) {
    document.getElementById('topology').innerHTML = DATA.topology_svg;
  }

  // Behavior swimlane
  const bhSection = document.getElementById('behavior-swimlane');
  const hasBehavior = trials.some(t => t.behavior_phases && t.behavior_phases.length > 0);
  if (hasBehavior) {
    let bhHtml = '';
    for (const t of trials) {
      const badge = t.outcome === 'success'
        ? '<span class="badge badge-success">success</span>'
        : '<span class="badge badge-timeout">timeout</span>';
      bhHtml += `<div class="bh-row">
        <span class="bh-trial-id">T-${String(t.id).padStart(2, '0')}</span>
        <div class="bh-timeline">${renderBehaviorTimeline(t.behavior_phases)}</div>
        <span class="bh-outcome">${badge}</span>
      </div>`;
    }
    bhSection.innerHTML = `<h2>Behavior Timeline</h2>${bhHtml}`;
    bhSection.style.display = 'block';
  }

  // Trial table
  const tbody = document.getElementById('trial-tbody');
  let html = '';
  for (const t of trials) {
    if (t.group_first) {
      html += `<tr class="group-header"><td colspan="7">${esc(t.group_label)} (${t.group_size} trial${t.group_size !== 1 ? 's' : ''})</td></tr>`;
    }
    const badge = t.outcome === 'success' ? 'badge-success' : 'badge-timeout';
    const label = t.is_baseline ? '<span class="badge badge-baseline">baseline</span> ' : '';
    html += `<tr class="clickable" data-trial-id="${t.id}">
      <td>${t.id}</td>
      <td>${label}${esc(t.chaos_description)}</td>
      <td><span class="badge ${badge}">${t.outcome}</span></td>
      <td>${t.detect_sec != null ? t.detect_sec + 's' : '-'}</td>
      <td>${t.resolve_sec != null ? t.resolve_sec + 's' : '-'}</td>
      <td>${t.cmd_count}</td>
      <td>${shortTs(t.started_at)}</td>
    </tr>`;
  }
  tbody.innerHTML = html;

  // Trial detail rendering
  const panel = document.getElementById('detail-panel');
  const trialMap = {};
  for (const t of trials) trialMap[t.id] = t;

  function renderDiff(diffStr) {
    if (!diffStr) return '<div class="empty">No code changes</div>';
    const lines = diffStr.split('\\n');
    let out = '<div class="diff-block">';
    for (const line of lines) {
      let cls = '';
      if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-add';
      else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-del';
      else if (line.startsWith('@@')) cls = 'diff-hunk';
      out += `<div class="diff-line ${cls}">${esc(line)}</div>`;
    }
    out += '</div>';
    return out;
  }

  function renderDbDiff(diff) {
    if (!diff || !diff.has_changes) return '<div class="empty">No DB config changes</div>';
    let out = '';
    for (const s of (diff.settings_changed || [])) {
      out += `<div class="db-change db-change-mod">Setting <b>${esc(s.name)}</b>: ${esc(s.before)} &rarr; ${esc(s.after)}</div>`;
    }
    for (const idx of (diff.indexes_added || [])) {
      out += `<div class="db-change db-change-add">+ Index: ${esc(idx.definition)}</div>`;
    }
    for (const idx of (diff.indexes_removed || [])) {
      out += `<div class="db-change db-change-del">- Index: ${esc(idx.definition)}</div>`;
    }
    for (const tbl of (diff.tables_added || [])) {
      out += `<div class="db-change db-change-add">+ Table: ${esc(tbl)}</div>`;
    }
    for (const tbl of (diff.tables_removed || [])) {
      out += `<div class="db-change db-change-del">- Table: ${esc(tbl)}</div>`;
    }
    for (const col of (diff.columns_added || [])) {
      out += `<div class="db-change db-change-add">+ Column: ${esc(col.table)}.${esc(col.name)} (${esc(col.type)})</div>`;
    }
    for (const col of (diff.columns_removed || [])) {
      out += `<div class="db-change db-change-del">- Column: ${esc(col.table)}.${esc(col.name)} (${esc(col.type)})</div>`;
    }
    return out || '<div class="empty">No DB config changes</div>';
  }

  function renderCommands(cmds) {
    if (!cmds || cmds.length === 0) return '<div class="empty">No commands recorded</div>';
    const collapsed = cmds.length > 10;
    let inner = '<ul class="cmd-list">';
    for (const c of cmds) {
      const elapsed = c.elapsed_seconds != null ? `<span class="elapsed-badge">+${c.elapsed_seconds}s</span>` : '';
      inner += `<li class="cmd-item">
        <code class="cmd-command">${esc(c.command)}</code>
        ${elapsed}
        ${c.reasoning ? `<div class="cmd-reasoning">${esc(c.reasoning)}</div>` : ''}
      </li>`;
    }
    inner += '</ul>';
    if (collapsed) {
      return `<details><summary>Commands (${cmds.length})</summary>${inner}</details>`;
    }
    return inner;
  }

  function renderReasoning(entries) {
    if (!entries || entries.length === 0) return '<div class="empty">No reasoning data</div>';
    let out = '';
    for (const e of entries) {
      const elapsed = e.elapsed_seconds != null ? `<span class="elapsed-badge">+${e.elapsed_seconds}s</span>` : '';
      const typeLabel = e.entry_type === 'tool_call'
        ? `tool: ${esc(e.tool_name || 'unknown')}`
        : esc(e.entry_type);
      const content = e.content ? esc(e.content).slice(0, 500) : '';
      const reasoning = e.reasoning ? `<div class="cmd-reasoning">${esc(e.reasoning)}</div>` : '';
      out += `<details class="reasoning-entry" open>
        <summary>
          <span class="reasoning-type">${typeLabel}</span>
          ${elapsed}
          ${e.timestamp ? `<span class="elapsed-badge">${shortTs(e.timestamp)}</span>` : ''}
        </summary>
        ${content ? `<div class="reasoning-content">${content}</div>` : ''}
        ${reasoning}
      </details>`;
    }
    return out;
  }

  function showTrial(id, scroll = true) {
    const t = trialMap[id];
    if (!t) return;

    // Highlight selected row
    document.querySelectorAll('tr.selected').forEach(r => r.classList.remove('selected'));
    document.querySelectorAll(`tr[data-trial-id="${id}"]`).forEach(r => r.classList.add('selected'));

    const conclusionCls = t.outcome === 'success' ? '' : ' timeout';
    const conclusionText = t.agent_conclusion
      ? t.agent_conclusion.outcome_summary
      : (t.outcome === 'success' ? 'Resolved' : 'Not resolved within timeout');

    let detectionHtml = '<div class="empty">No detection data</div>';
    if (t.monitor_detection) {
      const m = t.monitor_detection;
      detectionHtml = `
        <div><b>Invariant:</b> ${esc(m.violation_type)}</div>
        <div><b>Details:</b> ${esc(m.violation_details)}</div>
        <div><b>Detected:</b> ${formatTs(m.detected_at)}</div>
      `;
    }

    panel.innerHTML = `
      <h2>Trial #${t.id}: ${esc(t.chaos_description)}</h2>
      <div class="conclusion-box${conclusionCls}">${esc(conclusionText)}</div>

      <div class="detail-grid" style="margin-top:16px">
        <div class="detail-section">
          <h3>Chaos Injection</h3>
          <div>${esc(t.chaos_description)}</div>
        </div>
        <div class="detail-section">
          <h3>Monitor Detection</h3>
          ${detectionHtml}
        </div>
      </div>

      <div class="detail-section">
        <h3>Timing</h3>
        <div>Started: ${formatTs(t.started_at)}</div>
        <div>Chaos injected: ${formatTs(t.chaos_injected_at)}</div>
        <div>Ticket created: ${formatTs(t.ticket_created_at)}${t.detect_sec != null ? ` (+${t.detect_sec}s)` : ''}</div>
        <div>Resolved: ${formatTs(t.resolved_at)}${t.resolve_sec != null ? ` (+${t.resolve_sec}s from chaos)` : ''}</div>
        <div>Ended: ${formatTs(t.ended_at)}</div>
      </div>

      <div class="detail-section">
        <h3>Commands</h3>
        ${renderCommands(t.commands_with_reasoning)}
      </div>

      <details class="detail-section">
        <summary>Code Changes</summary>
        ${renderDiff(t.code_diff)}
      </details>

      <details class="detail-section">
        <summary>DB Config Changes</summary>
        ${renderDbDiff(t.db_config_diff)}
      </details>

      <details class="detail-section">
        <summary>Reasoning Timeline (${(t.reasoning_entries || []).length} entries)</summary>
        ${renderReasoning(t.reasoning_entries)}
      </details>
    `;
    panel.classList.add('visible');
    if (scroll) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Click handler on trial rows
  tbody.addEventListener('click', function(e) {
    const row = e.target.closest('tr.clickable');
    if (!row) return;
    const id = parseInt(row.dataset.trialId, 10);
    if (id) showTrial(id);
  });

  // Auto-show first trial (without scrolling)
  if (trials.length > 0) {
    showTrial(trials[0].id, /* scroll */ false);
  }
})();
"""


def render_html(data: dict[str, Any]) -> str:
    """Render export data as a self-contained HTML string."""
    json_blob = safe_json_for_script(data)
    campaign_name = data["campaign"]["name"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campaign: {campaign_name}</title>
<style>{_CSS}</style>
</head>
<body>

<div class="page-header">
  <div class="page-header-inner" id="campaign-header"></div>
</div>

<div class="page-body">
<div id="summary-stats" class="stats-bar"></div>
<div id="topology" class="topology-svg"></div>
<div id="behavior-swimlane" style="display:none"></div>

<h2>Trials</h2>
<table>
  <thead>
    <tr>
      <th>ID</th><th>Chaos</th><th>Outcome</th>
      <th>Detect</th><th>Resolve</th><th>Cmds</th><th>Started</th>
    </tr>
  </thead>
  <tbody id="trial-tbody"></tbody>
</table>

<div id="detail-panel" class="detail-panel"></div>
</div>

<script>window.__EXPORT_DATA__ = {json_blob};</script>
<script>{_JS}</script>
</body>
</html>"""


async def export_campaign_html(
    db: EvalDBProtocol,
    campaign_id: int,
) -> str:
    """Export a campaign as a self-contained HTML string.

    Args:
        db: Database backend
        campaign_id: Campaign to export

    Returns:
        Complete HTML string

    Raises:
        ValueError: If campaign not found
    """
    data = await build_export_data(db, campaign_id)
    return render_html(data)
