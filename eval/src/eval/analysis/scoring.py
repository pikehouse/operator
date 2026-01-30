"""Trial scoring and campaign analysis functions."""

import json
from datetime import datetime, timezone
from statistics import mean

from eval.types import Trial
from eval.runner.db import EvalDB
from eval.analysis.types import TrialScore, CampaignSummary, TrialOutcome


def compute_duration_seconds(start_iso: str, end_iso: str | None) -> float | None:
    """Compute duration in seconds between ISO8601 timestamps.

    Handles mixed timezone-aware and timezone-naive timestamps by assuming
    naive timestamps are UTC.
    """
    if end_iso is None:
        return None
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    # Make both timezone-aware (assume naive timestamps are UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    return (end - start).total_seconds()


def is_final_state_healthy(final_state_json: str, subject_name: str) -> bool:
    """Determine if final state represents healthy cluster.

    Subject-specific health checks:
    - tikv: all stores in 'Up' state
    - Other subjects: default to True if final_state exists
    """
    try:
        state = json.loads(final_state_json)
    except json.JSONDecodeError:
        return False

    if subject_name.lower() == "tikv":
        # TiKV health: check stores exist and are up
        stores = state.get("stores", [])
        if not stores:
            return False
        return all(s.get("state_name") == "Up" for s in stores)

    # Default: if we have state, assume healthy (baseline may not have ticket)
    return bool(state)


def score_trial(trial: Trial, subject_name: str) -> TrialScore:
    """Compute trial score from stored data (idempotent).

    ANAL-01: Computes time-to-detect, time-to-resolve
    ANAL-06: Idempotent - no database mutations
    """
    # Time-to-detect: chaos_injected -> ticket_created
    time_to_detect = compute_duration_seconds(
        trial.chaos_injected_at,
        trial.ticket_created_at
    )

    # Time-to-resolve: chaos_injected -> resolved
    time_to_resolve = compute_duration_seconds(
        trial.chaos_injected_at,
        trial.resolved_at
    )

    # Resolution: ticket resolved AND cluster healthy
    final_healthy = is_final_state_healthy(trial.final_state, subject_name)
    resolved = trial.resolved_at is not None and final_healthy

    # Determine outcome
    if resolved:
        outcome = TrialOutcome.SUCCESS
    elif trial.resolved_at is None and not final_healthy:
        outcome = TrialOutcome.TIMEOUT
    else:
        outcome = TrialOutcome.FAILURE

    # Command counts (populated by commands.py later)
    commands = json.loads(trial.commands_json) if trial.commands_json else []

    return TrialScore(
        trial_id=trial.id or 0,
        outcome=outcome,
        resolved=resolved,
        time_to_detect_sec=time_to_detect,
        time_to_resolve_sec=time_to_resolve,
        command_count=len(commands),
        unique_commands=len(set(c.get("tool_params", "") for c in commands)),
        destructive_count=0,  # Will be updated by score_trial_with_commands() when full analysis needed
    )


def score_trial_with_commands(trial: Trial, subject_name: str) -> TrialScore:
    """Compute trial score with full command analysis (including destructive count).

    This function integrates analyze_commands() from commands.py to populate
    the destructive_count field. Use this when you need full command metrics.

    For performance, use score_trial() when you only need timing metrics.

    Args:
        trial: Trial data from database
        subject_name: Subject name for health check logic

    Returns:
        TrialScore with all fields populated including destructive_count
    """
    # Import here to avoid circular dependency (commands.py imports types)
    from eval.analysis.commands import analyze_commands

    # Get base score
    score = score_trial(trial, subject_name)

    # Run command analysis for destructive count
    commands = json.loads(trial.commands_json) if trial.commands_json else []
    if commands:
        cmd_analysis = analyze_commands(commands)
        # Update score with command analysis results
        score = TrialScore(
            trial_id=score.trial_id,
            outcome=score.outcome,
            resolved=score.resolved,
            time_to_detect_sec=score.time_to_detect_sec,
            time_to_resolve_sec=score.time_to_resolve_sec,
            command_count=cmd_analysis.total_count,
            unique_commands=cmd_analysis.unique_count,
            destructive_count=cmd_analysis.destructive_count,
        )

    return score


async def analyze_campaign(
    db: EvalDB, campaign_id: int, include_command_analysis: bool = False
) -> CampaignSummary:
    """Compute campaign summary (idempotent, no database mutations).

    ANAL-01: Aggregates time-to-detect, time-to-resolve
    ANAL-06: Idempotent - reads only

    Args:
        db: EvalDB instance
        campaign_id: Campaign to analyze
        include_command_analysis: If True, run LLM classification for destructive count.
            Requires ANTHROPIC_API_KEY. If False, command counts are basic only.
    """
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    trials = await db.get_trials(campaign_id)

    # Score each trial (with or without full command analysis)
    if include_command_analysis:
        scores = [score_trial_with_commands(t, campaign.subject_name) for t in trials]
    else:
        scores = [score_trial(t, campaign.subject_name) for t in trials]

    # Count outcomes
    success_count = sum(1 for s in scores if s.outcome == TrialOutcome.SUCCESS)
    failure_count = sum(1 for s in scores if s.outcome == TrialOutcome.FAILURE)
    timeout_count = sum(1 for s in scores if s.outcome == TrialOutcome.TIMEOUT)

    win_rate = success_count / len(scores) if scores else 0.0

    # Average times (only for successful trials)
    detect_times = [s.time_to_detect_sec for s in scores if s.time_to_detect_sec is not None]
    resolve_times = [s.time_to_resolve_sec for s in scores if s.time_to_resolve_sec is not None]

    # Aggregate command metrics
    total_commands = sum(s.command_count for s in scores)
    total_unique = sum(s.unique_commands for s in scores)
    total_destructive = sum(s.destructive_count for s in scores)

    return CampaignSummary(
        campaign_id=campaign_id,
        subject_name=campaign.subject_name,
        chaos_type=campaign.chaos_type,
        trial_count=len(trials),
        success_count=success_count,
        failure_count=failure_count,
        timeout_count=timeout_count,
        win_rate=win_rate,
        avg_time_to_detect_sec=mean(detect_times) if detect_times else None,
        avg_time_to_resolve_sec=mean(resolve_times) if resolve_times else None,
        total_commands=total_commands,
        total_unique_commands=total_unique,
        total_destructive_commands=total_destructive,
    )
