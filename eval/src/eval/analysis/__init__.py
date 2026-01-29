"""Analysis module for computing trial metrics and campaign summaries."""

from eval.analysis.types import TrialOutcome, TrialScore, CampaignSummary
from eval.analysis.scoring import score_trial, score_trial_with_commands, analyze_campaign

__all__ = [
    "TrialOutcome",
    "TrialScore",
    "CampaignSummary",
    "score_trial",
    "score_trial_with_commands",
    "analyze_campaign",
]
