"""
Ticket types for the monitoring system.

This module defines the core data structures for ticket management:
- TicketStatus: Enum for valid ticket states
- Ticket: Dataclass representing a monitoring ticket
- make_violation_key: Function to generate deduplication keys

Per RESEARCH.md patterns:
- Use str enum for easy JSON serialization
- Dataclass with to_dict() for database persistence
- Violation key format: invariant_name:store_id
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from operator_protocols import InvariantViolation


class TicketStatus(str, Enum):
    """Valid ticket status values."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DIAGNOSED = "diagnosed"
    RESOLVED = "resolved"


class TicketType(str, Enum):
    """Distinguishes how a ticket was created."""

    VIOLATION_OBSERVED = "violation-observed"  # From monitor invariant check
    OPERATOR_OVERRIDE = "operator-override"  # Manually injected operational task


@dataclass
class Ticket:
    """
    Represents a monitoring ticket for an invariant violation.

    Tickets persist across restarts and support deduplication via
    the violation_key field. Status transitions are enforced by
    the TicketStatus enum.

    Attributes:
        id: Database ID (None before persisted)
        violation_key: Deduplication key (invariant_name:store_id)
        invariant_name: Name of the violated invariant
        message: Human-readable description
        severity: Violation severity level
        first_seen_at: When violation was first detected
        last_seen_at: When violation was most recently confirmed
        status: Current ticket status
        store_id: Optional store ID for store-specific violations
        held: If True, prevents auto-resolution
        batch_key: Groups related violations from same check cycle
        occurrence_count: How many times this violation was detected
        resolved_at: When ticket was resolved
        diagnosis: AI-generated diagnosis (Phase 5)
        metric_snapshot: Metrics captured at violation time
        subject_context: Subject-specific agent prompt context
        created_at: Database record creation time
        updated_at: Database record last update time
    """

    id: int | None
    violation_key: str
    invariant_name: str
    message: str
    severity: str
    first_seen_at: datetime
    last_seen_at: datetime
    status: TicketStatus = TicketStatus.OPEN
    store_id: str | None = None
    held: bool = False
    batch_key: str | None = None
    occurrence_count: int = 1
    resolved_at: datetime | None = None
    diagnosis: str | None = None
    metric_snapshot: dict[str, Any] | None = None
    subject_context: str | None = None
    variant_model: str | None = None
    variant_system_prompt: str | None = None
    type: str = TicketType.VIOLATION_OBSERVED
    variant_tools_config: str | None = None  # JSON string
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["status"] = self.status.value
        return d


def make_violation_key(violation: InvariantViolation) -> str:
    """
    Generate a deduplication key for a violation.

    Per CONTEXT.md: key = invariant_name + store_id.
    Same violation will update existing ticket rather than
    creating a duplicate.

    Args:
        violation: The invariant violation

    Returns:
        Key in format "invariant_name:store_id" or just "invariant_name"
    """
    if violation.store_id:
        return f"{violation.invariant_name}:{violation.store_id}"
    return violation.invariant_name


def row_to_ticket(row: Any) -> Ticket:
    """Convert a database row (dict-like) to a Ticket dataclass.

    Works with both aiosqlite.Row and sqlite3.Row objects.

    Args:
        row: Database row with ticket fields

    Returns:
        Ticket instance
    """
    return Ticket(
        id=row["id"],
        violation_key=row["violation_key"],
        invariant_name=row["invariant_name"],
        message=row["message"],
        severity=row["severity"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        status=TicketStatus(row["status"]),
        store_id=row["store_id"],
        held=bool(row["held"]),
        batch_key=row["batch_key"],
        occurrence_count=row["occurrence_count"],
        resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
        diagnosis=row["diagnosis"],
        metric_snapshot=json.loads(row["metric_snapshot"]) if row["metric_snapshot"] else None,
        subject_context=row["subject_context"],
        type=row["type"],
        variant_model=row["variant_model"],
        variant_system_prompt=row["variant_system_prompt"],
        variant_tools_config=row["variant_tools_config"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )
