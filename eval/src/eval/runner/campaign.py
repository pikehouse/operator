"""Campaign YAML configuration loading and matrix expansion."""

from itertools import product
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class ChaosSpec(BaseModel):
    """Per-chaos-type configuration."""
    type: str  # "node_kill", "latency", "disk_pressure", "network_partition"
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_chaos_type(cls, v: str) -> str:
        valid_types = ["node_kill", "latency", "disk_pressure", "network_partition"]
        if v not in valid_types:
            raise ValueError(f"Invalid chaos type: {v}. Must be one of {valid_types}")
        return v


class CampaignConfig(BaseModel):
    """Campaign YAML schema with validation."""
    name: str
    subjects: list[str] = Field(default_factory=lambda: ["tikv"])
    chaos_types: list[ChaosSpec]
    trials_per_combination: int = Field(default=1, ge=1)
    parallel: int = Field(default=1, ge=1, le=10)
    cooldown_seconds: int = Field(default=0, ge=0)
    include_baseline: bool = False
    variant: str = Field(default="default", description="Variant name to use for agent configuration")

    @field_validator("subjects")
    @classmethod
    def validate_subjects(cls, v: list[str]) -> list[str]:
        valid_subjects = ["tikv"]  # Extend as more subjects added
        for s in v:
            if s not in valid_subjects:
                raise ValueError(f"Invalid subject: {s}. Must be one of {valid_subjects}")
        return v


def load_campaign_config(path: Path) -> CampaignConfig:
    """Load and validate campaign config from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return CampaignConfig.model_validate(data)


def expand_campaign_matrix(config: CampaignConfig) -> list[dict[str, Any]]:
    """Generate trial specifications from matrix (subjects x chaos_types x trials_per_combination)."""
    trials = []

    # Cartesian product: subjects x chaos_types
    for subject, chaos in product(config.subjects, config.chaos_types):
        for trial_idx in range(config.trials_per_combination):
            trials.append({
                "subject": subject,
                "chaos_type": chaos.type,
                "chaos_params": chaos.params,
                "trial_index": trial_idx,
                "baseline": False,
                "variant": config.variant,
            })

    # Optional baseline trials (one per subject, no chaos)
    if config.include_baseline:
        for subject in config.subjects:
            trials.append({
                "subject": subject,
                "chaos_type": "none",
                "chaos_params": {},
                "trial_index": 0,
                "baseline": True,
                "variant": config.variant,
            })

    return trials
