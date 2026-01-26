"""
Factory function for creating TiKV subject and checker instances.

This module provides a factory function for CLI integration, allowing
the operator-core CLI to create TiKV-specific instances without
direct imports from operator-tikv.
"""

import httpx

from operator_tikv.invariants import TiKVInvariantChecker
from operator_tikv.pd_client import PDClient
from operator_tikv.prom_client import PrometheusClient
from operator_tikv.subject import TiKVSubject


def create_tikv_subject_and_checker(
    pd_endpoint: str,
    prometheus_url: str,
    pd_http: httpx.AsyncClient | None = None,
    prom_http: httpx.AsyncClient | None = None,
) -> tuple[TiKVSubject, TiKVInvariantChecker]:
    """
    Create a TiKV subject and checker pair.

    Factory function for creating TiKVSubject and TiKVInvariantChecker
    instances with pre-configured HTTP clients. Used by CLI to create
    subject/checker pairs without direct imports.

    Args:
        pd_endpoint: PD API endpoint URL (e.g., "http://pd:2379")
        prometheus_url: Prometheus API URL (e.g., "http://prometheus:9090")
        pd_http: Optional pre-configured httpx client for PD API.
            If None, a new client is created with 10s timeout.
        prom_http: Optional pre-configured httpx client for Prometheus.
            If None, a new client is created with 10s timeout.

    Returns:
        Tuple of (TiKVSubject, TiKVInvariantChecker) instances ready for use.

    Example:
        subject, checker = create_tikv_subject_and_checker(
            pd_endpoint="http://pd:2379",
            prometheus_url="http://prometheus:9090",
        )

        # Use with generic protocols
        observation = await subject.observe()
        violations = checker.check(observation)
    """
    if pd_http is None:
        pd_http = httpx.AsyncClient(base_url=pd_endpoint, timeout=10.0)
    if prom_http is None:
        prom_http = httpx.AsyncClient(base_url=prometheus_url, timeout=10.0)

    subject = TiKVSubject(
        pd=PDClient(http=pd_http),
        prom=PrometheusClient(http=prom_http),
    )
    checker = TiKVInvariantChecker()

    return subject, checker
