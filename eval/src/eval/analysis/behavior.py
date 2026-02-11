"""Behavior timeline classification via Claude API.

Classifies raw agent reasoning/command timelines into high-level behavioral
phases (investigate, change_config, deploy, etc.) using Haiku. This provides
an at-a-glance view of what the agent did strategically during a trial.
"""

import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ActionType(str, Enum):
    """High-level action categories for behavioral phases."""

    INVESTIGATE = "investigate"      # gray — reading logs, checking state
    CHANGE_CONFIG = "change_config"  # yellow — pool sizes, timeouts, settings
    CHANGE_CODE = "change_code"      # green — editing app source code
    CHANGE_DB = "change_db"          # teal — adding indexes, schema changes
    DEPLOY = "deploy"                # dark — rebuild, restart, apply changes
    OBSERVE = "observe"              # blue — verify fix worked post-deploy
    BAD_ACTION = "bad_action"        # red — made things worse
    REVERT = "revert"                # orange — undo previous changes


# Color map: action_type -> (background, text, border)
ACTION_COLORS: dict[str, dict[str, str]] = {
    "investigate":   {"bg": "#f3f4f6", "text": "#374151", "border": "#9ca3af"},
    "change_config": {"bg": "#fef3c7", "text": "#92400e", "border": "#f59e0b"},
    "change_code":   {"bg": "#dcfce7", "text": "#166534", "border": "#22c55e"},
    "change_db":     {"bg": "#ccfbf1", "text": "#115e59", "border": "#14b8a6"},
    "deploy":        {"bg": "#e5e7eb", "text": "#1f2937", "border": "#4b5563"},
    "observe":       {"bg": "#dbeafe", "text": "#1e40af", "border": "#3b82f6"},
    "bad_action":    {"bg": "#fee2e2", "text": "#991b1b", "border": "#ef4444"},
    "revert":        {"bg": "#ffedd5", "text": "#9a3412", "border": "#f97316"},
}


class BehaviorPhase(BaseModel):
    """A single phase in a behavioral timeline."""

    label: str              # Short 1-3 word description: "+index", "fix streaming"
    action_type: ActionType  # Determines pill color


class BehaviorTimeline(BaseModel):
    """Classified behavioral timeline for a trial."""

    trial_id: int
    phases: list[BehaviorPhase]
    reasoning_summary: str = ""  # 2-3 sentence Haiku summary of what the agent did
    model_used: str         # e.g. "claude-haiku-4-5-20241022"
    classified_at: str      # ISO8601


CLASSIFICATION_MODEL = "claude-haiku-4-5-20241022"


def _compress_timeline(
    reasoning_entries: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    max_chars: int = 150,
) -> str:
    """Compress reasoning entries or commands into a concise timeline string.

    Each entry is truncated to max_chars. Reasoning entries are preferred;
    falls back to commands if reasoning is empty.
    """
    entries = reasoning_entries if reasoning_entries else commands
    if not entries:
        return ""

    lines = []
    for i, entry in enumerate(entries):
        if isinstance(entry, dict):
            entry_type = entry.get("entry_type", "")
            tool_name = entry.get("tool_name", "")
            content = entry.get("content", "")
            tool_params = entry.get("tool_params", "")

            if entry_type == "tool_call" and tool_name:
                # Compress tool call: tool_name + truncated params
                params_str = ""
                if tool_params:
                    try:
                        params = json.loads(tool_params) if isinstance(tool_params, str) else tool_params
                        if isinstance(params, dict):
                            # For Bash, show command; for others, show key params
                            cmd = params.get("command", "")
                            if cmd:
                                params_str = cmd[:max_chars]
                            else:
                                params_str = str(params)[:max_chars]
                    except (json.JSONDecodeError, TypeError):
                        params_str = str(tool_params)[:max_chars]
                line = f"[{tool_name}] {params_str}"
            elif entry_type == "reasoning" or (content and not tool_name):
                line = f"(thinking) {content[:max_chars]}"
            else:
                # Command entry from commands_json
                cmd_str = entry.get("command", "")
                if not cmd_str:
                    tp = entry.get("tool_params", "")
                    try:
                        params = json.loads(tp) if isinstance(tp, str) else tp
                        cmd_str = params.get("command", str(tp))[:max_chars] if isinstance(params, dict) else str(tp)[:max_chars]
                    except (json.JSONDecodeError, TypeError):
                        cmd_str = str(tp)[:max_chars]
                line = cmd_str[:max_chars]
        else:
            line = str(entry)[:max_chars]

        lines.append(f"{i+1}. {line}")

    return "\n".join(lines)


def classify_trial_behavior(
    reasoning_entries: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    subject_name: str = "",
) -> BehaviorTimeline:
    """Classify a trial's timeline into behavioral phases using Haiku.

    Args:
        reasoning_entries: Entries from operator_data_json reasoning_entries
        commands: Entries from commands_json
        subject_name: Subject name for context (e.g., "tikv", "chat-db-app")

    Returns:
        BehaviorTimeline with classified phases. Empty phases on failure.
    """
    timeline_text = _compress_timeline(reasoning_entries, commands)
    if not timeline_text:
        return BehaviorTimeline(
            trial_id=0,
            phases=[],
            model_used=CLASSIFICATION_MODEL,
            classified_at=datetime.now(timezone.utc).isoformat(),
        )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Behavior classification requires an Anthropic API key."
        )

    from anthropic import Anthropic
    client = Anthropic()

    action_types_desc = """Action types:
- investigate: Reading logs, checking state, diagnosing (grep, cat, docker logs, curl, docker ps, SELECT queries)
- change_config: Changing pool sizes, timeouts, settings, env vars
- change_code: Editing application source code files
- change_db: Adding indexes, schema changes, ALTER TABLE, CREATE INDEX
- deploy: Rebuild, restart, docker restart, apply changes, git commit
- observe: Verifying fix worked after deploy (re-checking metrics, running queries)
- bad_action: Actions that made things worse or were mistakes
- revert: Undoing previous changes (git revert, removing bad config)"""

    prompt = f"""Analyze this agent's timeline of actions during an infrastructure debugging session{f' on {subject_name}' if subject_name else ''} and segment it into high-level behavioral phases.

Timeline:
{timeline_text}

{action_types_desc}

Segment into phases. Each phase groups consecutive actions with the same strategic intent. Use short 1-3 word labels (e.g., "+index", "fix streaming", "check logs", "restart app", "verify fix").

Also write a 2-3 sentence summary of what the agent did strategically.

Return JSON object:
{{"phases": [{{"label": "check logs", "action_type": "investigate"}}, ...], "summary": "The agent investigated... then fixed... and verified..."}}

Return ONLY the JSON object, no other text."""

    try:
        response = client.messages.create(
            model=CLASSIFICATION_MODEL,
            max_tokens=1024,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text

        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        parsed = json.loads(content.strip())

        # Support both old format (bare array) and new format ({phases, summary})
        summary = ""
        if isinstance(parsed, dict):
            phases_data = parsed.get("phases", [])
            summary = parsed.get("summary", "")
        elif isinstance(parsed, list):
            phases_data = parsed
        else:
            phases_data = []

        phases = []
        for item in phases_data:
            if not isinstance(item, dict):
                continue
            label = item.get("label", "")
            action_type_str = item.get("action_type", "investigate")
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                action_type = ActionType.INVESTIGATE
            if label:
                phases.append(BehaviorPhase(label=label, action_type=action_type))

        return BehaviorTimeline(
            trial_id=0,
            phases=phases,
            reasoning_summary=summary if isinstance(summary, str) else "",
            model_used=CLASSIFICATION_MODEL,
            classified_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        # Don't crash on classification failure
        return BehaviorTimeline(
            trial_id=0,
            phases=[],
            model_used=CLASSIFICATION_MODEL,
            classified_at=datetime.now(timezone.utc).isoformat(),
        )


async def classify_campaign_behavior(
    db: Any,
    campaign_id: int,
    force: bool = False,
    trial_id: int | None = None,
) -> list[BehaviorTimeline]:
    """Classify behavior for all trials in a campaign.

    Args:
        db: Database backend (EvalDB or PostgresDB)
        campaign_id: Campaign to classify
        force: Re-classify even if already classified
        trial_id: If set, classify only this trial

    Returns:
        List of BehaviorTimeline for each classified trial
    """
    from eval.types import safe_json_loads

    campaign = await db.get_campaign(campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    trials = await db.get_trials(campaign_id)
    if trial_id is not None:
        trials = [t for t in trials if t.id == trial_id]

    results = []
    for trial in trials:
        # Skip already classified unless force
        if not force and trial.behavior_json:
            try:
                existing = json.loads(trial.behavior_json)
                if existing.get("phases"):
                    timeline = BehaviorTimeline(**existing)
                    results.append(timeline)
                    continue
            except (json.JSONDecodeError, Exception):
                pass

        # Get reasoning entries and commands
        op_data = safe_json_loads(trial.operator_data_json)
        reasoning_entries = []
        if isinstance(op_data, dict):
            reasoning_entries = op_data.get("reasoning_entries", [])

        commands = safe_json_loads(trial.commands_json, [])
        if not isinstance(commands, list):
            commands = []

        # Classify
        timeline = classify_trial_behavior(
            reasoning_entries=reasoning_entries,
            commands=commands,
            subject_name=campaign.subject_name,
        )
        timeline.trial_id = trial.id

        # Store
        behavior_json = timeline.model_dump_json()
        await db.update_trial_behavior(trial.id, behavior_json)

        results.append(timeline)

    return results
