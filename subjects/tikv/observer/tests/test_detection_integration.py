"""
Integration tests for TiKV latency detection.

These tests require a running TiKV cluster with Prometheus.
They inject network latency via tc netem and verify detection.

Run with: uv run pytest tests/test_detection_integration.py -m integration -v
Skip with: uv run pytest -m "not integration"
"""

import asyncio
import subprocess
import time

import pytest

from tikv_observer.factory import create_tikv_subject_and_checker


def _tikv_cluster_available() -> bool:
    """Check if TiKV cluster is reachable."""
    try:
        import httpx

        r = httpx.get("http://localhost:2379/pd/api/v1/stores", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _get_tikv_container() -> str | None:
    """Find a running TiKV container."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=tikv", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    for name in result.stdout.strip().split("\n"):
        name = name.strip()
        if name and "tikv" in name.lower() and "pd" not in name.lower() and "prom" not in name.lower() and "ycsb" not in name.lower():
            return name
    return None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _tikv_cluster_available(),
        reason="TiKV cluster not running (start with docker compose up -d)",
    ),
]


@pytest.fixture
def tikv_container():
    """Get a TiKV container name, skip if not found."""
    container = _get_tikv_container()
    if not container:
        pytest.skip("No TiKV container found")
    return container


@pytest.fixture
def inject_latency(tikv_container):
    """Fixture that injects latency and always cleans up."""
    injected = False

    def _inject(min_ms: int, max_ms: int):
        nonlocal injected
        jitter = (max_ms - min_ms) // 2
        delay = min_ms + jitter
        cmd = f"tc qdisc add dev eth0 root netem delay {delay}ms {jitter}ms"
        result = subprocess.run(
            ["docker", "exec", tikv_container, "sh", "-c", cmd],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            cmd_replace = f"tc qdisc replace dev eth0 root netem delay {delay}ms {jitter}ms"
            subprocess.run(
                ["docker", "exec", tikv_container, "sh", "-c", cmd_replace],
                capture_output=True, text=True,
            )
        injected = True

    yield _inject

    # Always clean up
    if injected:
        subprocess.run(
            ["docker", "exec", tikv_container, "sh", "-c", "tc qdisc del dev eth0 root 2>/dev/null"],
            capture_output=True, text=True,
        )


async def _wait_for_detection(timeout_sec: int = 90) -> list:
    """Run observe+check loop until violation detected or timeout."""
    subject, checker = create_tikv_subject_and_checker(
        pd_endpoint="http://localhost:2379",
        prometheus_url="http://localhost:9090",
    )

    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            observation = await subject.observe()
            violations = checker.check(observation)
            if violations:
                return violations
        except Exception:
            pass
        await asyncio.sleep(5)

    return []


@pytest.mark.asyncio
async def test_detects_200ms_latency(inject_latency):
    """Detection fires within 90s for 200-500ms latency injection."""
    inject_latency(200, 500)
    violations = await _wait_for_detection(timeout_sec=90)
    assert len(violations) > 0, "No violations detected for 200-500ms latency"
    names = {v.invariant_name for v in violations}
    # Should detect via scrape_duration and/or high_latency/raft_commit
    assert names & {"high_scrape_duration", "high_latency", "high_raft_commit"}, (
        f"Expected latency-related violation, got: {names}"
    )


@pytest.mark.asyncio
async def test_detects_50ms_latency(inject_latency):
    """Detection fires within 90s for 50-150ms latency injection."""
    inject_latency(50, 150)
    violations = await _wait_for_detection(timeout_sec=90)
    assert len(violations) > 0, "No violations detected for 50-150ms latency"
    names = {v.invariant_name for v in violations}
    assert names & {"high_scrape_duration", "high_latency", "high_raft_commit"}, (
        f"Expected latency-related violation, got: {names}"
    )
