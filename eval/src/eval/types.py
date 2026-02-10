"""Type definitions for evaluation harness."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


def safe_json_loads(data: str | None, default=None):
    """Parse JSON string, handling double-encoded values from JSONB.

    Many JSON fields in the database can end up double-encoded (a JSON string
    inside a JSON string) due to JSONB round-trips. This function handles that
    transparently.

    Args:
        data: JSON string (possibly double-encoded), or None
        default: Default value if data is falsy (defaults to {})

    Returns:
        Parsed Python object
    """
    if not data:
        return default if default is not None else {}
    result = json.loads(data)
    if isinstance(result, str):
        result = json.loads(result)
    return result


def parse_iso_datetime(iso_str: str | None) -> datetime | None:
    """Parse ISO8601 string to datetime, handling timezone-naive strings.

    Naive timestamps are assumed to be UTC.

    Args:
        iso_str: ISO8601 timestamp string, or None

    Returns:
        Timezone-aware datetime (UTC), or None
    """
    if iso_str is None:
        return None
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_chaos_description(chaos_type: str, chaos_meta: dict | None = None) -> str:
    """Get human-readable chaos type description.

    Args:
        chaos_type: Chaos type identifier
        chaos_meta: Optional chaos metadata dict for param details

    Returns:
        Human-readable description
    """
    descriptions = {
        "node_kill": "Container killed with SIGKILL",
        "latency": "Network latency injection",
        "disk_pressure": "Disk space exhaustion",
        "network_partition": "Network partition from peers",
        "memory_exhaustion": "Memory pressure via stress (cloud-only)",
        "cpu_starvation": "CPU starvation via stress (cloud-only)",
        "process_pause": "Process frozen with SIGSTOP",
        "packet_loss": "Intermittent packet loss",
        "asymmetric_partition": "Asymmetric network partition",
        "pd_leader_kill": "PD leader node killed",
        "leader_concentration": "Region leaders concentrated on one store",
        "load_pressure": "Load pressure test",
        "db_disconnect": "Database connection blocked",
        "debug_code_edit": "Bugs injected into app code",
        "none": "Baseline (no chaos)",
    }
    desc = descriptions.get(chaos_type, chaos_type)

    if chaos_meta:
        if chaos_type == "latency" and chaos_meta.get("min_ms") is not None:
            desc = f"Network latency ({chaos_meta['min_ms']}-{chaos_meta['max_ms']}ms)"
        elif chaos_type == "disk_pressure" and chaos_meta.get("fill_percent") is not None:
            desc = f"Disk filled to {chaos_meta['fill_percent']}%"
        elif chaos_type == "node_kill" and chaos_meta.get("target_container"):
            desc = f"Kill {chaos_meta['target_container']} (SIGKILL)"
        elif chaos_type == "packet_loss" and chaos_meta.get("percent") is not None:
            desc = f"Packet loss ({chaos_meta['percent']}%)"
        elif chaos_type == "load_pressure":
            parts = []
            if chaos_meta.get("num_users") is not None:
                parts.append(f"{chaos_meta['num_users']} users")
            if chaos_meta.get("stream_ratio") is not None:
                parts.append(f"{int(float(chaos_meta['stream_ratio']) * 100)}% streaming")
            if parts:
                desc = f"Load pressure ({', '.join(parts)})"

    return desc


class ChaosType(str, Enum):
    """Chaos types supported by evaluation harness."""

    NODE_KILL = "node_kill"
    LATENCY = "latency"
    DISK_PRESSURE = "disk_pressure"
    NETWORK_PARTITION = "network_partition"
    PROCESS_PAUSE = "process_pause"
    PACKET_LOSS = "packet_loss"
    ASYMMETRIC_PARTITION = "asymmetric_partition"
    PD_LEADER_KILL = "pd_leader_kill"
    LEADER_CONCENTRATION = "leader_concentration"


@runtime_checkable
class EvalSubject(Protocol):
    """Protocol for evaluation subjects.

    Any system under test must implement these methods to be evaluated.
    """

    async def reset(self) -> None:
        """Reset subject to clean initial state."""
        ...

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for subject to reach healthy state.

        Args:
            timeout_sec: Maximum time to wait in seconds

        Returns:
            True if healthy within timeout, False otherwise
        """
        ...

    async def capture_state(self) -> dict[str, Any]:
        """Capture current subject state for comparison.

        Returns:
            State snapshot as JSON-serializable dict
        """
        ...

    def get_chaos_types(self) -> list[str]:
        """Return list of chaos types this subject supports.

        Returns:
            List of chaos type identifiers (e.g., ["node_kill"])
        """
        ...

    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject specified chaos type.

        Args:
            chaos_type: One of get_chaos_types() values
            **params: Type-specific parameters (e.g., min_ms, max_ms for latency)

        Returns:
            Chaos metadata as JSON-serializable dict.
            IMPORTANT: Must contain all fields needed by cleanup_chaos() to revert the chaos.

        Raises:
            ValueError: If chaos_type not supported
        """
        ...

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up/revert chaos injection.

        Called after trial ends to restore subject to normal state.

        Args:
            chaos_metadata: The dict returned by inject_chaos()

        Note:
            Should handle gracefully if container was restarted/killed.
        """
        ...


@dataclass
class Campaign:
    """Evaluation campaign metadata."""

    id: int | None = None
    subject_name: str = ""
    name: str = ""
    trial_count: int = 0
    baseline: bool = False
    variant_name: str = "default"
    topology_json: str = ""
    git_commit_hash: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_row(cls, row, *, keys: set[str] | None = None) -> "Campaign":
        """Construct from a database row (dict-like).

        Handles fallbacks for optional columns (variant_name, topology_json, name)
        that may be missing in older databases. Works with both aiosqlite.Row
        and asyncpg.Record.

        Args:
            row: Dict-like row (aiosqlite.Row or asyncpg.Record)
            keys: Column names present in row. If None, uses row.keys().
        """
        if keys is None:
            keys = set(row.keys())
        name = row["name"] if "name" in keys and row["name"] else (
            f"{row['subject_name']}/{row['chaos_type']}"
        )
        # topology_json: asyncpg auto-decodes JSONB to dict; convert back to string
        topo_raw = row["topology_json"] if "topology_json" in keys else None
        if topo_raw and not isinstance(topo_raw, str):
            topo = json.dumps(topo_raw)
        else:
            topo = topo_raw or ""
        # created_at: asyncpg returns datetime; convert to ISO string
        created = row["created_at"]
        if created and not isinstance(created, str):
            created = created.isoformat()
        return cls(
            id=row["id"],
            subject_name=row["subject_name"],
            name=name,
            trial_count=row["trial_count"],
            baseline=bool(row["baseline"]),
            variant_name=(row["variant_name"] if "variant_name" in keys and row["variant_name"] else "default"),
            topology_json=topo,
            git_commit_hash=(row["git_commit_hash"] if "git_commit_hash" in keys and row["git_commit_hash"] else ""),
            created_at=created or "",
        )


@dataclass
class Trial:
    """Single trial execution record."""

    id: int | None = None
    campaign_id: int = 0
    started_at: str = ""
    chaos_injected_at: str = ""
    ticket_created_at: str | None = None  # None for baseline
    resolved_at: str | None = None  # None if not resolved
    ended_at: str = ""
    initial_state: str = ""  # JSON blob
    final_state: str = ""  # JSON blob
    chaos_metadata: str = ""  # JSON blob
    commands_json: str = "[]"  # JSON array of commands
    operator_data_json: str = "{}"  # JSON blob of operator monitoring data

    @classmethod
    def from_row(cls, row, *, keys: set[str] | None = None, jsonb_to_str=None) -> "Trial":
        """Construct from a database row (dict-like).

        Handles fallbacks for optional columns (operator_data_json) that may
        be missing in older databases.

        Args:
            row: Dict-like row (aiosqlite.Row or asyncpg.Record)
            keys: Column names present in row. If None, uses row.keys().
            jsonb_to_str: Optional function to convert JSONB values to strings.
                          Used by PostgresDB where asyncpg auto-decodes JSONB.
                          Defaults to str passthrough for SQLite.
        """
        if keys is None:
            keys = set(row.keys())
        if jsonb_to_str is None:
            jsonb_to_str = lambda val, default: val if val is not None else default

        def _ts(val) -> str:
            """Convert timestamp value to ISO string."""
            if val is None:
                return ""
            return val if isinstance(val, str) else val.isoformat()

        def _ts_opt(val) -> str | None:
            """Convert optional timestamp value to ISO string or None."""
            if val is None:
                return None
            return val if isinstance(val, str) else val.isoformat()

        return cls(
            id=row["id"],
            campaign_id=row["campaign_id"],
            started_at=_ts(row["started_at"]),
            chaos_injected_at=_ts(row["chaos_injected_at"]),
            ticket_created_at=_ts_opt(row["ticket_created_at"]),
            resolved_at=_ts_opt(row["resolved_at"]),
            ended_at=_ts(row["ended_at"]),
            initial_state=jsonb_to_str(row["initial_state"], "{}"),
            final_state=jsonb_to_str(row["final_state"], "{}"),
            chaos_metadata=jsonb_to_str(row["chaos_metadata"], "{}"),
            commands_json=jsonb_to_str(row["commands_json"], "[]"),
            operator_data_json=jsonb_to_str(
                row["operator_data_json"] if "operator_data_json" in keys else None,
                "{}",
            ),
        )


class VariantConfig(BaseModel):
    """Agent configuration variant for A/B testing.

    Defines model, system prompt, and tool configuration for an agent variant.
    """
    name: str = Field(..., min_length=1, description="Human-readable variant name")
    model: str = Field(..., description="Anthropic model ID (e.g., claude-opus-4-20250514)")
    system_prompt: str = Field(..., min_length=1, description="System prompt text (inline)")
    tools_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool configuration (tool_choice, enabled_tools)"
    )
