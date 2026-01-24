"""
Monitor module for ticket management and violation tracking.

Exports:
    Ticket: Dataclass representing a monitoring ticket
    TicketStatus: Enum for valid ticket states
    make_violation_key: Function to generate deduplication keys
    MonitorLoop: Daemon class for continuous invariant checking
"""

from operator_core.monitor.types import Ticket, TicketStatus, make_violation_key

# Lazy import to avoid circular dependency with db.tickets
# MonitorLoop imports TicketDB which imports from monitor.types
# Import MonitorLoop at usage time from operator_core.monitor.loop


def __getattr__(name: str):
    """Lazy import for MonitorLoop to avoid circular imports."""
    if name == "MonitorLoop":
        from operator_core.monitor.loop import MonitorLoop

        return MonitorLoop
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Ticket", "TicketStatus", "make_violation_key", "MonitorLoop"]
