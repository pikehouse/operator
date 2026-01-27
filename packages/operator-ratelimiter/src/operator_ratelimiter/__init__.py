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

from operator_ratelimiter.factory import create_ratelimiter_subject_and_checker
from operator_ratelimiter.invariants import (
    COUNTER_DRIFT_CONFIG,
    GHOST_ALLOWING_CONFIG,
    HIGH_LATENCY_CONFIG,
    InvariantConfig,
    NODE_DOWN_CONFIG,
    REDIS_DISCONNECTED_CONFIG,
    RateLimiterInvariantChecker,
)
from operator_ratelimiter.prom_client import PrometheusClient
from operator_ratelimiter.ratelimiter_client import RateLimiterClient
from operator_ratelimiter.redis_client import RedisClient
from operator_ratelimiter.subject import RateLimiterSubject
from operator_ratelimiter.types import (
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
