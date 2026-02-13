#!/usr/bin/env python3
"""
Standalone test script for TiKV latency detection.

Tests the observe() -> check() cycle with tc netem latency injection.
Used to verify that the monitor detects latency violations with and without
client workload (YCSB).

Usage:
    # Test with default settings (200-500ms, auto-detect container)
    uv run python scripts/test_latency_detection.py --verbose

    # Skip injection (just observe what Prometheus reports)
    uv run python scripts/test_latency_detection.py --skip-inject --verbose

    # Custom latency range
    uv run python scripts/test_latency_detection.py --min-ms 50 --max-ms 150 --verbose

Exit codes:
    0 = violation detected
    1 = timeout (no detection)
"""

import argparse
import asyncio
import subprocess
import sys
import time


def get_tikv_containers() -> list[str]:
    """Find running TiKV containers."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "ancestor=tikv-chaos:v8.5.5", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
    if not containers:
        # Try cloud image
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=tikv", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        )
        containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip() and "tikv" in c.lower() and "pd" not in c.lower() and "prom" not in c.lower() and "ycsb" not in c.lower()]
    return containers


def inject_latency(container: str, min_ms: int, max_ms: int) -> None:
    """Inject latency via tc netem on a container."""
    jitter = (max_ms - min_ms) // 2
    delay = min_ms + jitter
    cmd = f"tc qdisc add dev eth0 root netem delay {delay}ms {jitter}ms"
    print(f"  Injecting latency on {container}: {cmd}")
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Might already have a qdisc, try replace
        cmd_replace = f"tc qdisc replace dev eth0 root netem delay {delay}ms {jitter}ms"
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-c", cmd_replace],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  WARNING: Failed to inject latency: {result.stderr}")


def cleanup_latency(container: str) -> None:
    """Remove tc netem rules from a container."""
    print(f"  Cleaning up latency on {container}")
    subprocess.run(
        ["docker", "exec", container, "sh", "-c", "tc qdisc del dev eth0 root 2>/dev/null"],
        capture_output=True, text=True,
    )


async def run_detection_loop(
    pd_endpoint: str,
    prometheus_url: str,
    timeout_sec: int,
    verbose: bool,
) -> bool:
    """Run observe+check loop, return True if violation detected."""
    from tikv_observer.factory import create_tikv_subject_and_checker

    subject, checker = create_tikv_subject_and_checker(
        pd_endpoint=pd_endpoint,
        prometheus_url=prometheus_url,
    )

    start = time.time()
    cycle = 0

    while time.time() - start < timeout_sec:
        cycle += 1
        elapsed = time.time() - start
        print(f"\n--- Cycle {cycle} ({elapsed:.0f}s / {timeout_sec}s) ---")

        try:
            observation = await subject.observe()
        except Exception as e:
            print(f"  observe() error: {e}")
            await asyncio.sleep(5)
            continue

        if verbose:
            store_metrics = observation.get("store_metrics", {})
            for store_id, metrics in sorted(store_metrics.items()):
                print(f"  Store {store_id}:")
                print(f"    latency_p99_ms     = {metrics.get('latency_p99_ms', 'N/A')}")
                print(f"    raft_commit_p99_ms  = {metrics.get('raft_commit_p99_ms', 'N/A')}")
                print(f"    qps                = {metrics.get('qps', 'N/A')}")
                print(f"    scrape_duration_s  = {metrics.get('scrape_duration_seconds', 'N/A')}")

            # Also query raw scrape_duration directly for debugging
            try:
                raw_scrape = await subject.prom.get_metric_value(
                    'max(scrape_duration_seconds{job="tikv"})'
                )
                print(f"  [raw] max scrape_duration_seconds(job=tikv) = {raw_scrape}")
            except Exception as e:
                print(f"  [raw] scrape_duration query error: {e}")

        violations = checker.check(observation)

        if violations:
            print(f"\n  VIOLATIONS DETECTED:")
            for v in violations:
                print(f"    [{v.severity}] {v.invariant_name}: {v.message}")
            return True
        else:
            print("  No violations detected")

        await asyncio.sleep(5)

    print(f"\n  TIMEOUT after {timeout_sec}s - no violations detected")
    return False


def main():
    parser = argparse.ArgumentParser(description="Test TiKV latency detection")
    parser.add_argument("--min-ms", type=int, default=200, help="Min latency (ms)")
    parser.add_argument("--max-ms", type=int, default=500, help="Max latency (ms)")
    parser.add_argument("--container", type=str, default=None, help="Container name (auto-detect if not set)")
    parser.add_argument("--timeout", type=int, default=120, help="Detection timeout (seconds)")
    parser.add_argument("--verbose", action="store_true", help="Print all metrics each cycle")
    parser.add_argument("--skip-inject", action="store_true", help="Skip latency injection (observe only)")
    parser.add_argument("--pd-endpoint", type=str, default="http://localhost:2379")
    parser.add_argument("--prometheus-url", type=str, default="http://localhost:9090")
    args = parser.parse_args()

    # Find container
    container = args.container
    if not args.skip_inject and not container:
        containers = get_tikv_containers()
        if not containers:
            print("ERROR: No TiKV containers found. Start cluster first.")
            sys.exit(1)
        container = containers[0]
        print(f"Auto-detected container: {container}")
        print(f"All TiKV containers: {containers}")

    print(f"Settings: latency={args.min_ms}-{args.max_ms}ms, timeout={args.timeout}s, verbose={args.verbose}")
    print(f"PD: {args.pd_endpoint}, Prometheus: {args.prometheus_url}")

    try:
        if not args.skip_inject:
            print(f"\nInjecting latency on {container}...")
            inject_latency(container, args.min_ms, args.max_ms)

        print("\nStarting detection loop...")
        detected = asyncio.run(
            run_detection_loop(
                pd_endpoint=args.pd_endpoint,
                prometheus_url=args.prometheus_url,
                timeout_sec=args.timeout,
                verbose=args.verbose,
            )
        )

        if detected:
            print("\nRESULT: PASS - violation detected")
            sys.exit(0)
        else:
            print("\nRESULT: FAIL - no violation detected within timeout")
            sys.exit(1)

    finally:
        if not args.skip_inject and container:
            print("\nCleaning up...")
            cleanup_latency(container)


if __name__ == "__main__":
    main()
