"""Campaign and baseline comparison functions.

Implements ANAL-04 (baseline comparison) and ANAL-05 (campaign comparison).
"""

from pydantic import BaseModel

from eval.runner.db import EvalDB
from eval.analysis.types import CampaignSummary
from eval.analysis.scoring import analyze_campaign


class BaselineComparison(BaseModel):
    """Agent vs baseline comparison result.

    Shows full breakdown with all metrics side-by-side.
    """
    agent_campaign_id: int
    baseline_campaign_id: int
    subject_name: str
    chaos_type: str

    # Agent metrics
    agent_trial_count: int
    agent_win_rate: float
    agent_avg_detect_sec: float | None
    agent_avg_resolve_sec: float | None

    # Baseline metrics
    baseline_trial_count: int
    baseline_win_rate: float
    baseline_avg_resolve_sec: float | None  # No detect for baseline (no ticket)

    # Deltas (agent - baseline, positive = agent better for win rate)
    win_rate_delta: float
    resolve_time_delta: float | None  # Negative = agent faster

    # Winner determination
    winner: str  # "agent", "baseline", or "tie"
    winner_reason: str


class CampaignComparison(BaseModel):
    """Campaign A vs Campaign B comparison result.

    Win rate is primary metric, resolution time is tiebreaker.
    """
    campaign_a_id: int
    campaign_b_id: int
    subject_name: str
    chaos_type: str

    # Campaign A metrics
    a_trial_count: int
    a_win_rate: float
    a_avg_resolve_sec: float | None

    # Campaign B metrics
    b_trial_count: int
    b_win_rate: float
    b_avg_resolve_sec: float | None

    # Deltas (B - A, positive = B better for win rate)
    win_rate_delta: float
    resolve_time_delta: float | None

    # Winner determination
    winner: str  # "A", "B", or "tie"
    winner_reason: str


def _determine_winner(
    a_win_rate: float,
    b_win_rate: float,
    a_resolve_sec: float | None,
    b_resolve_sec: float | None,
    a_label: str = "A",
    b_label: str = "B",
) -> tuple[str, str]:
    """Determine winner by win rate, then resolution time as tiebreaker.

    Returns:
        Tuple of (winner_label, reason)
    """
    # Primary: win rate
    if a_win_rate > b_win_rate:
        return a_label, f"Higher win rate ({a_win_rate:.1%} vs {b_win_rate:.1%})"
    elif b_win_rate > a_win_rate:
        return b_label, f"Higher win rate ({b_win_rate:.1%} vs {a_win_rate:.1%})"

    # Tiebreaker: faster resolution
    if a_resolve_sec is not None and b_resolve_sec is not None:
        if a_resolve_sec < b_resolve_sec:
            return a_label, f"Faster resolution ({a_resolve_sec:.1f}s vs {b_resolve_sec:.1f}s)"
        elif b_resolve_sec < a_resolve_sec:
            return b_label, f"Faster resolution ({b_resolve_sec:.1f}s vs {a_resolve_sec:.1f}s)"

    return "tie", "Equal win rate and resolution time"


async def compare_baseline(
    db: EvalDB,
    agent_campaign_id: int,
    baseline_campaign_id: int | None = None,
) -> BaselineComparison:
    """Compare agent campaign to baseline campaign.

    ANAL-04: Agent vs self-healing comparison

    Args:
        db: EvalDB instance
        agent_campaign_id: Campaign ID with agent enabled
        baseline_campaign_id: Campaign ID with baseline=True (optional, auto-finds if None)

    Returns:
        BaselineComparison with full metric breakdown

    Raises:
        ValueError: If campaigns have mismatched subject/chaos or baseline not found
    """
    agent_summary = await analyze_campaign(db, agent_campaign_id)
    agent_campaign = await db.get_campaign(agent_campaign_id)

    if not agent_campaign:
        raise ValueError(f"Campaign {agent_campaign_id} not found")

    # Find baseline campaign if not specified
    if baseline_campaign_id is None:
        # Query for matching baseline campaign
        baseline_campaign_id = await _find_baseline_campaign(
            db, agent_campaign.subject_name, agent_campaign.chaos_type
        )
        if baseline_campaign_id is None:
            raise ValueError(
                f"No baseline campaign found for {agent_campaign.subject_name}/{agent_campaign.chaos_type}"
            )

    baseline_summary = await analyze_campaign(db, baseline_campaign_id)
    baseline_campaign = await db.get_campaign(baseline_campaign_id)

    if not baseline_campaign:
        raise ValueError(f"Baseline campaign {baseline_campaign_id} not found")

    # Validate matching subject and chaos type
    if agent_campaign.subject_name != baseline_campaign.subject_name:
        raise ValueError(
            f"Subject mismatch: agent={agent_campaign.subject_name}, "
            f"baseline={baseline_campaign.subject_name}"
        )
    if agent_campaign.chaos_type != baseline_campaign.chaos_type:
        raise ValueError(
            f"Chaos type mismatch: agent={agent_campaign.chaos_type}, "
            f"baseline={baseline_campaign.chaos_type}"
        )

    # Compute deltas
    win_rate_delta = agent_summary.win_rate - baseline_summary.win_rate
    resolve_time_delta = None
    if agent_summary.avg_time_to_resolve_sec and baseline_summary.avg_time_to_resolve_sec:
        resolve_time_delta = (
            agent_summary.avg_time_to_resolve_sec - baseline_summary.avg_time_to_resolve_sec
        )

    winner, reason = _determine_winner(
        agent_summary.win_rate,
        baseline_summary.win_rate,
        agent_summary.avg_time_to_resolve_sec,
        baseline_summary.avg_time_to_resolve_sec,
        a_label="agent",
        b_label="baseline",
    )

    return BaselineComparison(
        agent_campaign_id=agent_campaign_id,
        baseline_campaign_id=baseline_campaign_id,
        subject_name=agent_campaign.subject_name,
        chaos_type=agent_campaign.chaos_type,
        agent_trial_count=agent_summary.trial_count,
        agent_win_rate=agent_summary.win_rate,
        agent_avg_detect_sec=agent_summary.avg_time_to_detect_sec,
        agent_avg_resolve_sec=agent_summary.avg_time_to_resolve_sec,
        baseline_trial_count=baseline_summary.trial_count,
        baseline_win_rate=baseline_summary.win_rate,
        baseline_avg_resolve_sec=baseline_summary.avg_time_to_resolve_sec,
        win_rate_delta=win_rate_delta,
        resolve_time_delta=resolve_time_delta,
        winner=winner,
        winner_reason=reason,
    )


async def compare_campaigns(
    db: EvalDB,
    campaign_a_id: int,
    campaign_b_id: int,
) -> CampaignComparison:
    """Compare two campaigns by win rate.

    ANAL-05: Campaign comparison (variant A vs variant B)

    Args:
        db: EvalDB instance
        campaign_a_id: First campaign ID
        campaign_b_id: Second campaign ID

    Returns:
        CampaignComparison with win rate comparison

    Raises:
        ValueError: If campaigns have mismatched subject/chaos type
    """
    a_summary = await analyze_campaign(db, campaign_a_id)
    b_summary = await analyze_campaign(db, campaign_b_id)

    a_campaign = await db.get_campaign(campaign_a_id)
    b_campaign = await db.get_campaign(campaign_b_id)

    if not a_campaign or not b_campaign:
        raise ValueError("One or both campaigns not found")

    # Validate matching subject and chaos type
    if a_campaign.subject_name != b_campaign.subject_name:
        raise ValueError(
            f"Subject mismatch: A={a_campaign.subject_name}, B={b_campaign.subject_name}"
        )
    if a_campaign.chaos_type != b_campaign.chaos_type:
        raise ValueError(
            f"Chaos type mismatch: A={a_campaign.chaos_type}, B={b_campaign.chaos_type}"
        )

    # Compute deltas (B - A)
    win_rate_delta = b_summary.win_rate - a_summary.win_rate
    resolve_time_delta = None
    if a_summary.avg_time_to_resolve_sec and b_summary.avg_time_to_resolve_sec:
        resolve_time_delta = (
            b_summary.avg_time_to_resolve_sec - a_summary.avg_time_to_resolve_sec
        )

    winner, reason = _determine_winner(
        a_summary.win_rate,
        b_summary.win_rate,
        a_summary.avg_time_to_resolve_sec,
        b_summary.avg_time_to_resolve_sec,
        a_label="A",
        b_label="B",
    )

    return CampaignComparison(
        campaign_a_id=campaign_a_id,
        campaign_b_id=campaign_b_id,
        subject_name=a_campaign.subject_name,
        chaos_type=a_campaign.chaos_type,
        a_trial_count=a_summary.trial_count,
        a_win_rate=a_summary.win_rate,
        a_avg_resolve_sec=a_summary.avg_time_to_resolve_sec,
        b_trial_count=b_summary.trial_count,
        b_win_rate=b_summary.win_rate,
        b_avg_resolve_sec=b_summary.avg_time_to_resolve_sec,
        win_rate_delta=win_rate_delta,
        resolve_time_delta=resolve_time_delta,
        winner=winner,
        winner_reason=reason,
    )


async def _find_baseline_campaign(
    db: EvalDB,
    subject_name: str,
    chaos_type: str,
) -> int | None:
    """Find most recent baseline campaign matching subject and chaos type."""
    import aiosqlite

    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT id FROM campaigns
            WHERE subject_name = ? AND chaos_type = ? AND baseline = 1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (subject_name, chaos_type),
        )
        row = await cursor.fetchone()
        return row["id"] if row else None


class VariantMetrics(BaseModel):
    """Aggregate metrics for a single variant across all its campaigns/trials."""
    variant_name: str
    trial_count: int
    success_count: int
    win_rate: float
    avg_time_to_detect_sec: float | None
    avg_time_to_resolve_sec: float | None
    avg_commands: float


class VariantComparison(BaseModel):
    """Comparison of multiple variants for the same subject/chaos combination.

    Shows balanced scorecard - all metrics equally, no winner determination.
    User interprets tradeoffs.
    """
    subject_name: str
    chaos_type: str
    variants: dict[str, VariantMetrics]  # variant_name -> metrics


async def compare_variants(
    db: EvalDB,
    subject_name: str,
    chaos_type: str,
    variant_names: list[str] | None = None,
) -> VariantComparison:
    """Compare performance across variants for same subject/chaos combination.

    CONF-03: Aggregate metrics per variant for A/B comparison.

    Args:
        db: EvalDB instance
        subject_name: Filter by subject (e.g., "tikv")
        chaos_type: Filter by chaos type (e.g., "node_kill")
        variant_names: Optional list of variant names to include (None = all)

    Returns:
        VariantComparison with aggregate metrics per variant

    Raises:
        ValueError: If no campaigns found for criteria
    """
    import aiosqlite

    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row

        # Check if variant_name column exists (for backward compatibility)
        cursor = await conn.execute("PRAGMA table_info(campaigns)")
        columns = await cursor.fetchall()
        has_variant_column = any(col[1] == "variant_name" for col in columns)

        if not has_variant_column:
            raise ValueError("Database schema missing variant_name column. Run migration first.")

        # Get all non-baseline campaigns matching criteria
        query = """
            SELECT id, variant_name
            FROM campaigns
            WHERE subject_name = ? AND chaos_type = ? AND baseline = 0
        """
        params: list = [subject_name, chaos_type]

        if variant_names:
            placeholders = ",".join("?" * len(variant_names))
            query += f" AND variant_name IN ({placeholders})"
            params.extend(variant_names)

        cursor = await conn.execute(query, params)
        campaigns = await cursor.fetchall()

    if not campaigns:
        raise ValueError(
            f"No campaigns found for {subject_name}/{chaos_type}"
            + (f" with variants {variant_names}" if variant_names else "")
        )

    # Group campaigns by variant, analyze each
    variant_summaries: dict[str, list[CampaignSummary]] = {}
    for campaign in campaigns:
        summary = await analyze_campaign(db, campaign["id"])
        variant_name = campaign["variant_name"] or "default"
        if variant_name not in variant_summaries:
            variant_summaries[variant_name] = []
        variant_summaries[variant_name].append(summary)

    # Aggregate metrics for each variant
    def _safe_avg(values: list[float | None]) -> float | None:
        filtered = [v for v in values if v is not None]
        return sum(filtered) / len(filtered) if filtered else None

    results: dict[str, VariantMetrics] = {}
    for variant_name, summaries in variant_summaries.items():
        total_trials = sum(s.trial_count for s in summaries)
        total_success = sum(s.success_count for s in summaries)
        total_commands = sum(s.total_commands for s in summaries)

        results[variant_name] = VariantMetrics(
            variant_name=variant_name,
            trial_count=total_trials,
            success_count=total_success,
            win_rate=total_success / total_trials if total_trials > 0 else 0.0,
            avg_time_to_detect_sec=_safe_avg([s.avg_time_to_detect_sec for s in summaries]),
            avg_time_to_resolve_sec=_safe_avg([s.avg_time_to_resolve_sec for s in summaries]),
            avg_commands=total_commands / total_trials if total_trials > 0 else 0.0,
        )

    return VariantComparison(
        subject_name=subject_name,
        chaos_type=chaos_type,
        variants=results,
    )
