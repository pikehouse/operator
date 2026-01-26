"""Prometheus metrics for rate limiter service."""

from prometheus_client import Counter, Histogram, Gauge

# Rate limit check metrics
REQUESTS_CHECKED = Counter(
    "ratelimiter_requests_checked_total",
    "Total rate limit checks performed",
    ["result"],  # "allowed" or "blocked"
)

CHECK_LATENCY = Histogram(
    "ratelimiter_check_duration_seconds",
    "Rate limit check latency in seconds",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# Node status metrics
NODE_UP = Gauge(
    "ratelimiter_node_up",
    "Whether this node is up (1) or down (0)",
)

ACTIVE_COUNTERS = Gauge(
    "ratelimiter_active_counters",
    "Number of active rate limit counters",
)


def record_rate_limit_check(result: str) -> None:
    """Record a rate limit check result."""
    REQUESTS_CHECKED.labels(result=result).inc()


def set_node_up(up: bool) -> None:
    """Set node up status."""
    NODE_UP.set(1 if up else 0)


def set_active_counters(count: int) -> None:
    """Set number of active counters."""
    ACTIVE_COUNTERS.set(count)
