"""
Database module for ticket persistence.

Exports:
    TicketDB: Async context manager for ticket database operations
"""

from operator_core.db.tickets import TicketDB

__all__ = ["TicketDB"]
