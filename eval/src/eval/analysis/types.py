"""Analysis types for trial scoring and campaign summaries."""

from enum import Enum
from pydantic import BaseModel


class TrialOutcome(str, Enum):
    """Trial outcome classification."""
    SUCCESS = "success"    # Resolved and healthy
    FAILURE = "failure"    # Not resolved or not healthy
    TIMEOUT = "timeout"    # Timed out waiting


class TrialScore(BaseModel):
    """Computed metrics for a single trial."""
    trial_id: int
    outcome: TrialOutcome
    resolved: bool  # Ticket resolved AND final state healthy
    time_to_detect_sec: float | None  # chaos_injected -> ticket_created
    time_to_resolve_sec: float | None  # chaos_injected -> resolved
    command_count: int = 0
    unique_commands: int = 0
    destructive_count: int = 0


class CampaignSummary(BaseModel):
    """Aggregate metrics for a campaign."""
    campaign_id: int
    subject_name: str
    chaos_type: str
    trial_count: int
    success_count: int
    failure_count: int
    timeout_count: int
    win_rate: float  # success_count / trial_count
    avg_time_to_detect_sec: float | None
    avg_time_to_resolve_sec: float | None
    # Command metrics (aggregated across all trials)
    total_commands: int = 0
    total_unique_commands: int = 0
    total_destructive_commands: int = 0
