"""
Subject configuration types for declarative capability registration.

This module provides dataclasses for subjects to declare their capabilities
(actions, observations, SLOs) without modifying operator core code. Each
subject defines a SubjectConfig that describes what it can do.

This enables:
1. Discovery of subject capabilities at runtime
2. Validation of operator requests against subject capabilities
3. Documentation generation from capability declarations
4. SLO-driven monitoring and alerting

Example:
    A TiKV subject declares its capabilities:

    ```python
    from operator_core.config import Action, Observation, SLO, SubjectConfig

    tikv_config = SubjectConfig(
        name="tikv",
        actions=[
            Action("transfer_leader", ["region_id", "to_store_id"],
                   description="Move region leadership to another store"),
            Action("split_region", ["region_id"],
                   description="Split a hot region into two"),
        ],
        observations=[
            Observation("get_stores", "list[Store]",
                       description="List all TiKV nodes"),
            Observation("get_hot_write_regions", "list[Region]",
                       description="Find regions with high write traffic"),
        ],
        slos=[
            SLO("write_latency_p99", target=100, unit="ms",
                grace_period_s=60,
                description="99th percentile write latency threshold"),
            SLO("under_replicated_regions", target=0, unit="count",
                grace_period_s=600,
                description="Regions with fewer replicas than configured"),
        ],
    )
    ```

    The operator core uses this config to:
    - Know what actions it can request from the subject
    - Understand what observations are available
    - Monitor SLO compliance and trigger alerts
"""

from dataclasses import dataclass, field


@dataclass
class Action:
    """
    Describes an action that a subject can perform.

    Actions are operations that modify the subject system's state.
    Each action has a name, list of required arguments, and optional
    description.

    Attributes:
        name: The method name on the Subject implementation.
        args: List of argument names the action requires.
        description: Human-readable description of what the action does.

    Example:
        Action("transfer_leader", ["region_id", "to_store_id"],
               description="Move region leadership to another store")
    """

    name: str
    args: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Observation:
    """
    Describes an observation that a subject can provide.

    Observations are read-only queries about the subject system's state.
    Each observation has a name, return type (as a string for documentation),
    and optional description.

    Attributes:
        name: The method name on the Subject implementation.
        returns: String representation of the return type (e.g., "list[Store]").
        description: Human-readable description of what the observation provides.

    Example:
        Observation("get_stores", "list[Store]",
                   description="List all TiKV nodes in the cluster")
    """

    name: str
    returns: str = ""
    description: str = ""


@dataclass
class SLO:
    """
    Describes a service level objective for the subject.

    SLOs define targets that the operator monitors. When an SLO is violated
    (after the grace period), the operator can trigger alerts or remediation.

    Attributes:
        name: Identifier for this SLO (e.g., "write_latency_p99").
        target: The threshold value. Interpretation depends on the metric:
            - For latency: max acceptable value (e.g., 100 for 100ms)
            - For counts: max acceptable count (e.g., 0 for no under-replicated regions)
        unit: Unit of measurement (e.g., "ms", "percent", "count").
        grace_period_s: Seconds of violation allowed before alert/action.
            Prevents alerting on transient spikes.
        description: Human-readable description of this SLO.

    Example:
        SLO("write_latency_p99", target=100, unit="ms", grace_period_s=60,
            description="99th percentile write latency must stay below 100ms")
    """

    name: str
    target: float
    unit: str = ""
    grace_period_s: int = 0
    description: str = ""


@dataclass
class SubjectConfig:
    """
    Complete configuration for a subject system.

    Aggregates all actions, observations, and SLOs that a subject
    supports. The operator core uses this to understand subject
    capabilities and monitor SLO compliance.

    Attributes:
        name: Subject identifier (e.g., "tikv", "kafka").
        actions: List of actions the subject can perform.
        observations: List of observations the subject can provide.
        slos: List of SLOs to monitor for this subject.

    Example:
        SubjectConfig(
            name="tikv",
            actions=[Action("transfer_leader", ["region_id", "to_store_id"])],
            observations=[Observation("get_stores", "list[Store]")],
            slos=[SLO("write_latency_p99", target=100, unit="ms")],
        )
    """

    name: str
    actions: list[Action] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    slos: list[SLO] = field(default_factory=list)


def create_subject_config(
    name: str,
    actions: list[Action],
    observations: list[Observation],
    slos: list[SLO],
) -> SubjectConfig:
    """
    Factory function for creating SubjectConfig instances.

    Provides a convenient way to create configs with explicit arguments
    rather than keyword-only initialization.

    Args:
        name: Subject identifier.
        actions: List of Action definitions.
        observations: List of Observation definitions.
        slos: List of SLO definitions.

    Returns:
        A new SubjectConfig instance.

    Example:
        config = create_subject_config(
            name="tikv",
            actions=[Action("transfer_leader", ["region_id", "to_store_id"])],
            observations=[Observation("get_stores", "list[Store]")],
            slos=[SLO("write_latency_p99", target=100, unit="ms")],
        )
    """
    return SubjectConfig(
        name=name,
        actions=actions,
        observations=observations,
        slos=slos,
    )
