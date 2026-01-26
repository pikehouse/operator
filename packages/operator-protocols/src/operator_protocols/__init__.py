"""
Protocol definitions for the AI-powered operator system.

This package provides generic Protocol definitions that can be implemented
by any subject (TiKV, rate limiter, etc.). It has zero dependencies on
other operator-* packages.

Key protocols:
- SubjectProtocol: Interface for observable systems
- InvariantCheckerProtocol: Interface for health invariant checkers

Key types:
- InvariantViolation: Represents a detected invariant violation
- Store: Generic node in a distributed system
- StoreMetrics: Performance metrics for a node
- ClusterMetrics: Cluster-wide aggregated metrics
- StoreId: Type alias for node identifiers
"""

from operator_protocols.subject import SubjectProtocol
from operator_protocols.invariant import InvariantCheckerProtocol, InvariantViolation
from operator_protocols.types import Store, StoreMetrics, ClusterMetrics, StoreId

__all__ = [
    # Protocols
    "SubjectProtocol",
    "InvariantCheckerProtocol",
    # Data types
    "InvariantViolation",
    "Store",
    "StoreMetrics",
    "ClusterMetrics",
    "StoreId",
]
