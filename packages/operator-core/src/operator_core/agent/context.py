"""
Context gathering for AI diagnosis.

Per CONTEXT.md decisions:
- Metric snapshot only (current values at violation time)
- Include similar ticket history (past diagnoses for same invariant)
- Include full cluster topology (all stores, regions for correlation)
- Raw log tail deferred (stubbed for v1)

Per RESEARCH.md Pattern 3: Gather all relevant information before
invoking Claude for diagnosis.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from operator_core.monitor.types import Ticket, TicketStatus
from operator_core.types import ClusterMetrics, Store

if TYPE_CHECKING:
    from operator_core.db.tickets import TicketDB
    from operator_protocols import SubjectProtocol


@dataclass
class DiagnosisContext:
    """All context needed for diagnosing a ticket.

    Assembled by ContextGatherer before invoking Claude for diagnosis.
    Contains the ticket being diagnosed plus all relevant cluster state.

    Attributes:
        ticket: The ticket being diagnosed
        metric_snapshot: Metrics captured at violation time (from ticket)
        stores: Current cluster topology (all TiKV stores)
        cluster_metrics: Store/region counts, leader distribution
        log_tail: Last N lines from affected component (None in v1)
        similar_tickets: Past diagnoses for same invariant
    """

    ticket: Ticket
    metric_snapshot: dict[str, Any]
    stores: list[Store]
    cluster_metrics: ClusterMetrics
    log_tail: str | None
    similar_tickets: list[Ticket]


class ContextGatherer:
    """Assembles diagnosis context from multiple sources.

    Per CONTEXT.md: Context includes metric snapshot, cluster topology,
    similar ticket history, and log tail (stubbed for v1).

    Example:
        gatherer = ContextGatherer(subject, db)
        context = await gatherer.gather(ticket)
        prompt = build_diagnosis_prompt(context)
    """

    def __init__(self, subject: "SubjectProtocol", db: "TicketDB") -> None:
        """Initialize context gatherer with data sources.

        Args:
            subject: SubjectProtocol for cluster state observations
            db: TicketDB for similar ticket history queries
        """
        self.subject = subject
        self.db = db

    async def gather(self, ticket: Ticket) -> DiagnosisContext:
        """Gather all context for diagnosing a ticket.

        Assembles context from:
        - Ticket's metric_snapshot (captured at violation time)
        - Current cluster topology (stores)
        - Cluster-wide metrics (store/region counts, leader distribution)
        - Similar past tickets (same invariant_name)
        - Log tail (stubbed - returns None for v1)

        Args:
            ticket: The ticket to gather context for

        Returns:
            DiagnosisContext with all assembled information
        """
        # Metric snapshot at violation time (from ticket)
        metric_snapshot = ticket.metric_snapshot or {}

        # Current cluster topology
        stores = await self.subject.get_stores()
        cluster_metrics = await self.subject.get_cluster_metrics()

        # Raw log tail (stubbed for v1)
        log_tail = await self._fetch_log_tail(ticket.store_id)

        # Similar ticket history (past diagnoses for same invariant)
        similar_tickets = await self._find_similar_tickets(ticket)

        return DiagnosisContext(
            ticket=ticket,
            metric_snapshot=metric_snapshot,
            stores=stores,
            cluster_metrics=cluster_metrics,
            log_tail=log_tail,
            similar_tickets=similar_tickets,
        )

    async def _fetch_log_tail(self, store_id: str | None) -> str | None:
        """Fetch last N lines from affected component logs.

        Note:
            Log fetching is stubbed for v1. Returns None.
            Future implementation will fetch from container logs.

        Args:
            store_id: The store ID to fetch logs for (if store-specific)

        Returns:
            None (stubbed for v1)
        """
        # Log fetching stubbed for v1 per plan
        # Future: fetch from container logs via Docker API or log aggregator
        return None

    async def _find_similar_tickets(self, ticket: Ticket) -> list[Ticket]:
        """Find past tickets with the same invariant.

        Per RESEARCH.md: Similar = same invariant_name.
        Returns diagnosed/resolved tickets that can provide
        historical context for the current violation.

        Args:
            ticket: The current ticket being diagnosed

        Returns:
            List of similar tickets (limited to recent, diagnosed ones)
        """
        # Get tickets with same invariant_name that have been diagnosed
        all_tickets = await self.db.list_tickets(status=TicketStatus.DIAGNOSED)

        similar = [
            t
            for t in all_tickets
            if t.invariant_name == ticket.invariant_name
            and t.id != ticket.id  # Don't include current ticket
        ]

        # Limit to 3 most recent per RESEARCH.md recommendation
        return similar[:3]
