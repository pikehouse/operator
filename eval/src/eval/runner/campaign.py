"""Campaign YAML configuration loading and matrix expansion."""

import os
from itertools import product
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ChaosSpec(BaseModel):
    """Per-chaos-type configuration."""
    type: str  # "node_kill", "latency", "disk_pressure", "network_partition", etc.
    params: dict[str, Any] = Field(default_factory=dict)
    resolution_timeout: int | None = Field(default=None, description="Override default resolution timeout (seconds)")

    @field_validator("type")
    @classmethod
    def validate_chaos_type(cls, v: str) -> str:
        # Base types always allowed; cloud-only types validated at runtime
        valid_types = [
            "node_kill", "latency", "disk_pressure", "network_partition",
            "memory_exhaustion", "cpu_starvation",  # Cloud-only
            "process_pause", "packet_loss", "asymmetric_partition",
            "pd_leader_kill", "leader_concentration",
            "load_pressure", "db_kill", "debug_code_edit",  # Chat DB App
            "missing_index", "pool_exhaustion", "streaming_txn", "counter_race",  # Chat DB App per-defect
            "fulltext_search", "read_scale",  # Chat DB App feature-building
            "unbounded_results", "write_contention", "write_amplification",  # Chat DB App scaling
            "correlated_subquery",  # Chat DB App O(N^2) query
            "notification_fanout", "notification_counter", "notification_realtime",  # Chat DB App notification
            "notification_poll_idle", "notification_mark_read", "notification_n_plus_one",  # Chat DB App notification
            "notification_payload", "notification_cleanup", "notification_serialize",  # Chat DB App notification
            "db_sharding", "db_sharding_nudge", "db_sharding_direct",  # Chat DB App Shard
        ]
        if v not in valid_types:
            raise ValueError(f"Invalid chaos type: {v}. Must be one of {valid_types}")
        return v


class OperatorConfig(BaseModel):
    """Operator configuration for cloud eval trials."""
    enabled: bool = Field(default=False, description="Enable operator on cloud VMs")
    image: str = Field(default="", description="Artifact Registry image URL for operator (derived from GCP_PROJECT if empty)")

    @model_validator(mode="after")
    def resolve_image(self) -> "OperatorConfig":
        """Derive image URL from GCP_PROJECT env var when not explicitly set."""
        if self.enabled and not self.image:
            project = os.environ.get("GCP_PROJECT", "")
            if project:
                self.image = f"us-central1-docker.pkg.dev/{project}/eval/operator:latest"
        return self


class CloudConfig(BaseModel):
    """Cloud execution configuration."""
    provider: str = Field(default="gcp", description="Cloud provider (gcp)")
    project: str | None = Field(default=None, description="GCP project ID")
    zone: str = Field(default="us-central1-a", description="GCP zone")
    machine_type: str = Field(default="e2-standard-4", description="VM machine type")
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL for distributed execution"
    )
    operator: OperatorConfig | None = Field(
        default=None,
        description="Operator configuration for running monitor+agent on VMs"
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        valid_providers = ["gcp"]
        if v not in valid_providers:
            raise ValueError(f"Invalid provider: {v}. Must be one of {valid_providers}")
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
    continuous: bool = Field(
        default=False,
        description="Run trials sequentially without resetting between them (stacking defects)"
    )
    cloud: CloudConfig | None = Field(
        default=None,
        description="Cloud execution configuration (optional)"
    )

    @model_validator(mode="after")
    def validate_continuous_constraints(self) -> "CampaignConfig":
        if self.continuous:
            if self.parallel > 1:
                raise ValueError("continuous=true requires parallel=1 (trials must run on the same instance)")
            if self.include_baseline:
                raise ValueError("continuous=true is incompatible with include_baseline=true")
        return self

    @field_validator("subjects")
    @classmethod
    def validate_subjects(cls, v: list[str]) -> list[str]:
        valid_subjects = ["tikv", "chat-db-app", "chat-db-app-shard"]
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
    """Generate trial specifications from matrix (subjects x chaos_types x trials_per_combination).

    When config.continuous is True, each trial spec gets a sequence_number (0, 1, 2, ...)
    indicating execution order. Non-continuous trials get sequence_number=None.
    """
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
                "resolution_timeout": chaos.resolution_timeout,
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
                "resolution_timeout": None,
            })

    # Assign sequence numbers for continuous mode
    if config.continuous:
        for i, trial in enumerate(trials):
            trial["sequence_number"] = i
    else:
        for trial in trials:
            trial["sequence_number"] = None

    return trials
