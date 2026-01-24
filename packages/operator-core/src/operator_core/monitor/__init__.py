"""
Monitor module for ticket management and violation tracking.

Exports:
    Ticket: Dataclass representing a monitoring ticket
    TicketStatus: Enum for valid ticket states
    make_violation_key: Function to generate deduplication keys
    MonitorLoop: Daemon class for continuous invariant checking
"""

from operator_core.monitor.loop import MonitorLoop
from operator_core.monitor.types import Ticket, TicketStatus, make_violation_key

__all__ = ["Ticket", "TicketStatus", "make_violation_key", "MonitorLoop"]
