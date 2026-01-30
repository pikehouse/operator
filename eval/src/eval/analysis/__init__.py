"""Analysis module for computing trial metrics and campaign summaries."""

from eval.analysis.types import TrialOutcome, TrialScore, CampaignSummary
from eval.analysis.scoring import score_trial, score_trial_with_commands, analyze_campaign
from eval.analysis.comparison import (
    BaselineComparison,
    CampaignComparison,
    VariantMetrics,
    VariantComparison,
    compare_baseline,
    compare_campaigns,
    compare_variants,
)
from eval.analysis.commands import (
    CommandCategory,
    CommandClassification,
    CommandAnalysis,
    analyze_commands,
    detect_thrashing,
)

__all__ = [
    "TrialOutcome",
    "TrialScore",
    "CampaignSummary",
    "score_trial",
    "score_trial_with_commands",
    "analyze_campaign",
    "BaselineComparison",
    "CampaignComparison",
    "VariantMetrics",
    "VariantComparison",
    "compare_baseline",
    "compare_campaigns",
    "compare_variants",
    "CommandCategory",
    "CommandClassification",
    "CommandAnalysis",
    "analyze_commands",
    "detect_thrashing",
]
