#!/usr/bin/env python3
"""
Integration test for TUI demo flow.

This test runs the actual TUIDemoController programmatically,
advancing through chapters and verifying that:
1. Chaos callbacks execute
2. Monitor subprocess detects violations
3. Health poller sees counters
4. Workload panel would show data

Run with: uv run python scripts/test-tui-demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "operator-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "operator-ratelimiter" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import subprocess


async def flush_redis():
    """Flush Redis like run-demo.sh does."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "docker-redis-1", "redis-cli", "FLUSHALL",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await proc.wait()


async def run_tui_test():
    """Run TUI demo programmatically and validate behavior."""
    from rich.console import Console

    from demo.ratelimiter import RATELIMITER_CHAPTERS
    from demo.ratelimiter_health import RateLimiterHealthPoller
    from demo.tui_integration import TUIDemoController

    print("=" * 60)
    print("TUI DEMO INTEGRATION TEST")
    print("=" * 60)
    print()

    # Step 1: Flush Redis for clean state
    print("Step 1: Flushing Redis...")
    await flush_redis()
    print("  Done.")
    print()

    # Step 2: Create TUI controller (but don't run full event loop)
    print("Step 2: Creating TUI controller...")
    health_poller = RateLimiterHealthPoller(
        endpoints=[
            "http://localhost:8001",
            "http://localhost:8002",
            "http://localhost:8003",
        ],
        poll_interval=2.0,
    )

    # Use a null console to avoid terminal issues
    console = Console(force_terminal=False, no_color=True)

    controller = TUIDemoController(
        subject_name="ratelimiter",
        chapters=RATELIMITER_CHAPTERS,
        health_poller=health_poller,
        compose_file=Path("docker/docker-compose.yml"),
        console=console,
    )
    print("  Done.")
    print()

    # Step 3: Manually initialize components (simulating what run() does)
    print("Step 3: Starting subprocesses and health poller...")

    from operator_core.tui.subprocess import SubprocessManager

    controller._subprocess_mgr = SubprocessManager()

    # Spawn monitor with -u flag for unbuffered output
    monitor_proc = await controller._subprocess_mgr.spawn(
        "monitor",
        [
            "-u",
            "-m",
            "operator_core.cli.main",
            "monitor",
            "run",
            "--subject",
            "ratelimiter",
            "-i",
            "3",
        ],
        buffer_size=50,
    )

    # Spawn agent
    agent_proc = await controller._subprocess_mgr.spawn(
        "agent",
        [
            "-u",
            "-m",
            "operator_core.cli.main",
            "agent",
            "start",
            "--subject",
            "ratelimiter",
            "-i",
            "5",
        ],
        buffer_size=50,
    )

    # Start reading subprocess output in background
    reader_tasks = [
        asyncio.create_task(controller._subprocess_mgr.read_output(monitor_proc)),
        asyncio.create_task(controller._subprocess_mgr.read_output(agent_proc)),
    ]

    # Start health poller
    health_poller._running = True
    import httpx
    health_poller._client = httpx.AsyncClient(timeout=5.0)
    poller_task = asyncio.create_task(health_poller.run())

    print("  Subprocesses started.")
    print()

    # Step 4: Wait for monitor to initialize
    print("Step 4: Waiting for monitor to start...")
    await asyncio.sleep(4)

    # Check monitor output
    monitor_buf = controller._subprocess_mgr.get_buffer("monitor")
    if monitor_buf:
        output = monitor_buf.get_text()
        print(f"  Monitor output ({len(monitor_buf)} lines):")
        for line in output.split("\n")[-10:]:
            print(f"    {line}")
    print()

    # Step 5: Advance to Stage 3 (Counter Drift Chaos) and execute callback
    print("Step 5: Advancing to Stage 3 (Counter Drift Chaos)...")

    # Advance from Welcome (0) to Stage 1 (1)
    controller._demo_state.advance()
    # Advance from Stage 1 (1) to Stage 2 (2) - Setup
    controller._demo_state.advance()

    # Execute Stage 2 callback (setup_rate_limit)
    stage2 = controller._demo_state.get_current()
    print(f"  At: {stage2.title}")
    if stage2.on_enter:
        print("  Executing Stage 2 callback (setup)...")
        await stage2.on_enter()
        print("  Stage 2 callback complete.")

    # Stage 2 auto-advances, so advance again
    controller._demo_state.advance()

    # Now at Stage 3 - Counter Drift Chaos
    stage3 = controller._demo_state.get_current()
    print(f"  At: {stage3.title}")

    # Execute Stage 3 callback (inject chaos)
    if stage3.on_enter:
        print("  Executing Stage 3 callback (chaos injection)...")
        await stage3.on_enter()
        print("  Stage 3 callback complete.")
    print()

    # Step 6: Wait for monitor to detect violation
    print("Step 6: Waiting for monitor to detect violation...")
    await asyncio.sleep(6)  # Wait for 2 monitor cycles

    # Check monitor output again
    if monitor_buf:
        output = monitor_buf.get_text()
        print(f"  Monitor output ({len(monitor_buf)} lines):")
        for line in output.split("\n")[-15:]:
            print(f"    {line}")
    print()

    # Step 7: Check health poller
    print("Step 7: Checking health poller...")
    await health_poller._poll_health()
    health = health_poller.get_health()
    if health:
        counters = health.get("counters", [])
        print(f"  Counters from health poller: {counters}")
    else:
        print("  No health data!")
    print()

    # Step 8: Validate results
    print("Step 8: Validating results...")

    errors = []

    # Check monitor detected violations
    if monitor_buf:
        output = monitor_buf.get_text()
        if "violation(s) detected" in output:
            print("  ✓ Monitor detected violations")
        else:
            errors.append("Monitor did not detect violations")
            print("  ✗ Monitor did NOT detect violations")

        if "counter-drift-demo" in output:
            print("  ✓ Monitor observed counter-drift-demo key")
        else:
            errors.append("Monitor did not observe counter-drift-demo")
            print("  ✗ Monitor did NOT observe counter-drift-demo key")
    else:
        errors.append("No monitor output captured")
        print("  ✗ No monitor output captured")

    # Check health poller has counters
    if health:
        counters = health.get("counters", [])
        if counters:
            print(f"  ✓ Health poller found {len(counters)} counter(s)")
            over_limit = [c for c in counters if c.get("over_limit")]
            if over_limit:
                print(f"  ✓ Found {len(over_limit)} over-limit counter(s)")
            else:
                errors.append("No over-limit counters found")
                print("  ✗ No over-limit counters found")
        else:
            errors.append("Health poller found no counters")
            print("  ✗ Health poller found no counters")

    print()

    # Step 9: Cleanup
    print("Step 9: Cleaning up...")
    health_poller.stop()
    controller._subprocess_mgr._shutdown.set()
    await controller._subprocess_mgr.terminate_all()

    for task in reader_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass

    if health_poller._client:
        await health_poller._client.aclose()

    print("  Done.")
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if errors:
        print(f"FAILED - {len(errors)} error(s):")
        for err in errors:
            print(f"  ✗ {err}")
        return False
    else:
        print("SUCCESS - All checks passed!")
        return True


async def main():
    try:
        success = await run_tui_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
