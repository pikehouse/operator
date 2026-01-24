"""
Monitor module for ticket management and violation tracking.

Exports:
    Ticket: Dataclass representing a monitoring ticket
    TicketStatus: Enum for valid ticket states
    make_violation_key: Function to generate deduplication keys
"""

from operator_core.monitor.types import Ticket, TicketStatus, make_violation_key

__all__ = ["Ticket", "TicketStatus", "make_violation_key"]
