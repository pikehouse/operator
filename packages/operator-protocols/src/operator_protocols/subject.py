"""
Subject protocol definition.

The SubjectProtocol defines the interface for any observable system that
can be monitored by the operator. Implementations include TiKV clusters,
rate limiters, and other distributed systems.
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from operator_protocols.types import ActionDefinition


@runtime_checkable
class SubjectProtocol(Protocol):
    """
    Protocol for observable systems.

    A Subject represents any system that can be observed and potentially
    acted upon by the operator. It provides:
    - observe(): Returns current system state as a flexible dict
    - get_action_definitions(): Returns available actions

    Example observation schema:
        {
            "stores": [{"id": "1", "address": "host:1234", "state": "Up"}, ...],
            "metrics": {"store_metrics": [...], "cluster_metrics": {...}},
            "timestamp": "2026-01-26T12:00:00Z"
        }

    The observation dict structure is implementation-specific. Each Subject
    implementation documents its own schema.
    """

    async def observe(self) -> dict[str, Any]:
        """
        Observe the current state of the subject.

        Returns:
            A dictionary containing the current observation. The structure
            is implementation-specific but typically includes:
            - Component states (e.g., stores, nodes)
            - Metrics (e.g., latency, throughput)
            - Metadata (e.g., timestamp)
        """
        ...

    def get_action_definitions(self) -> list[Any]:
        """
        Get the action definitions available for this subject.

        Returns:
            List of ActionDefinition objects describing available actions.
            Each action includes name, description, parameters, and handler.
        """
        ...
