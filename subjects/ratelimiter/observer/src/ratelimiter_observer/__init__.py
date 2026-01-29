"""
Rate Limiter subject implementation for the AI-powered operator.

This package provides the RateLimiter-specific implementation of the Subject interface
defined in operator-protocols. It includes:

- RateLimiterSubject: Complete Subject Protocol implementation (SubjectProtocol)
- RateLimiterInvariantChecker: Health invariant checking (InvariantCheckerProtocol)
- RateLimiter management API client for cluster state observation
- Redis client for direct state inspection
- Prometheus metrics client for performance monitoring
- Factory function for CLI integration
"""

# Re-export InvariantViolation from operator_protocols for convenience
from operator_protocols import InvariantViolation

from ratelimiter_observer.factory import create_ratelimiter_subject_and_checker
from ratelimiter_observer.invariants import (
    COUNTER_DRIFT_CONFIG,
    GHOST_ALLOWING_CONFIG,
    HIGH_LATENCY_CONFIG,
    InvariantConfig,
    NODE_DOWN_CONFIG,
    REDIS_DISCONNECTED_CONFIG,
    RateLimiterInvariantChecker,
)
from ratelimiter_observer.prom_client import PrometheusClient
from ratelimiter_observer.ratelimiter_client import RateLimiterClient
from ratelimiter_observer.redis_client import RedisClient
from ratelimiter_observer.subject import RateLimiterSubject
from ratelimiter_observer.types import (
    BlockedKeyInfo,
    BlocksResponse,
    CounterInfo,
    CountersResponse,
    LimitsResponse,
    NodeInfo,
    NodesResponse,
    UpdateLimitRequest,
    UpdateLimitResponse,
)

__all__ = [
    # Subject
    "RateLimiterSubject",
    # Factory
    "create_ratelimiter_subject_and_checker",
    # Clients
    "RateLimiterClient",
    "RedisClient",
    "PrometheusClient",
    # Invariants
    "RateLimiterInvariantChecker",
    "InvariantConfig",
    "InvariantViolation",  # Re-exported from operator_protocols
    "NODE_DOWN_CONFIG",
    "REDIS_DISCONNECTED_CONFIG",
    "HIGH_LATENCY_CONFIG",
    "COUNTER_DRIFT_CONFIG",
    "GHOST_ALLOWING_CONFIG",
    # Response types
    "NodeInfo",
    "NodesResponse",
    "CounterInfo",
    "CountersResponse",
    "LimitsResponse",
    "BlockedKeyInfo",
    "BlocksResponse",
    "UpdateLimitRequest",
    "UpdateLimitResponse",
]
