#!/usr/bin/env python3
"""
Test script to validate the rate limiter demo flow end-to-end.

This script tests each component in isolation and together to ensure
the demo will work correctly:

1. Chaos injection - creates over-limit counters in Redis
2. Rate limiter API - returns counter data correctly
3. Monitor detection - invariant checker finds violations
4. Health poller - TUI can display counter stats
5. Agent context - diagnosis can gather context without errors

Run with: uv run python scripts/test-demo-flow.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add packages to path
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "operator-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "operator-ratelimiter" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import redis.asyncio as redis


class DemoFlowTest:
    """Test harness for demo flow validation."""

    def __init__(self):
        self.redis_url = "redis://localhost:6379"
        self.ratelimiter_url = "http://localhost:8001"
        self.errors = []
        self.warnings = []

    async def run_all_tests(self):
        """Run all tests and report results."""
        print("=" * 60)
        print("RATE LIMITER DEMO FLOW TEST")
        print("=" * 60)
        print()

        tests = [
            ("Redis connectivity", self.test_redis_connection),
            ("Rate limiter API", self.test_ratelimiter_api),
            ("Chaos injection", self.test_chaos_injection),
            ("Counter detection via API", self.test_counter_api_detection),
            ("Invariant checker", self.test_invariant_checker),
            ("Health poller counters", self.test_health_poller_counters),
            ("Agent context gathering", self.test_agent_context),
            ("Monitor observation flow", self.test_monitor_flow),
            ("TUI panel display", self.test_tui_panel_display),
            ("Monitor persistence (10s)", self.test_monitor_persistence),
        ]

        results = []
        for name, test_fn in tests:
            print(f"Testing: {name}...")
            try:
                await test_fn()
                print(f"  ✓ PASS")
                results.append((name, True, None))
            except Exception as e:
                print(f"  ✗ FAIL: {e}")
                results.append((name, False, str(e)))

        # Cleanup
        await self.cleanup()

        # Summary
        print()
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)

        passed = sum(1 for _, ok, _ in results if ok)
        failed = sum(1 for _, ok, _ in results if not ok)

        for name, ok, error in results:
            status = "✓" if ok else "✗"
            print(f"  {status} {name}")
            if error:
                print(f"      Error: {error}")

        print()
        print(f"Passed: {passed}/{len(results)}")

        if failed > 0:
            print(f"\n⚠ {failed} test(s) failed - demo may not work correctly")
            return False
        else:
            print("\n✓ All tests passed - demo should work correctly")
            return True

    async def test_redis_connection(self):
        """Test Redis is reachable."""
        r = redis.Redis.from_url(self.redis_url, decode_responses=True)
        try:
            pong = await r.ping()
            assert pong, "Redis ping failed"
        finally:
            await r.aclose()

    async def test_ratelimiter_api(self):
        """Test rate limiter management API is reachable."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Test health endpoint
            resp = await client.get(f"{self.ratelimiter_url}/health")
            resp.raise_for_status()
            health = resp.json()
            assert health.get("status") == "healthy", f"Unhealthy: {health}"

            # Test nodes endpoint
            resp = await client.get(f"{self.ratelimiter_url}/api/nodes")
            resp.raise_for_status()
            nodes = resp.json()
            assert "nodes" in nodes, "Missing nodes key"

            # Test counters endpoint
            resp = await client.get(f"{self.ratelimiter_url}/api/counters")
            resp.raise_for_status()
            counters = resp.json()
            assert "counters" in counters, "Missing counters key"

    async def test_chaos_injection(self):
        """Test chaos injection creates over-limit counter."""
        from demo.ratelimiter_chaos import inject_burst_traffic

        # Inject chaos
        result = await inject_burst_traffic(
            target_urls=[self.ratelimiter_url],
            key="test-demo-flow",
            limit=10,
            multiplier=2,
        )

        assert result["allowed"] == 20, f"Expected 20 allowed, got {result['allowed']}"

        # Verify counter exists in Redis
        r = redis.Redis.from_url(self.redis_url, decode_responses=True)
        try:
            key_type = await r.type("ratelimit:test-demo-flow")
            assert key_type == "zset", f"Expected zset, got {key_type}"

            now_ms = int(time.time() * 1000)
            count = await r.zcount("ratelimit:test-demo-flow", now_ms - 60000, now_ms + 60000)
            assert count == 20, f"Expected count 20, got {count}"
        finally:
            await r.aclose()

    async def test_counter_api_detection(self):
        """Test rate limiter API returns injected counter."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.ratelimiter_url}/api/counters")
            resp.raise_for_status()
            data = resp.json()

            counters = data.get("counters", [])
            test_counter = next(
                (c for c in counters if c["key"] == "test-demo-flow"), None
            )

            assert test_counter is not None, f"Counter not found in API. Got: {counters}"
            assert test_counter["count"] == 20, f"Expected count 20, got {test_counter['count']}"
            assert test_counter["limit"] == 10, f"Expected limit 10, got {test_counter['limit']}"

    async def test_invariant_checker(self):
        """Test invariant checker detects over-limit violation."""
        from ratelimiter_observer.invariants import RateLimiterInvariantChecker

        checker = RateLimiterInvariantChecker()

        # Simulate observation with over-limit counter
        observation = {
            "nodes": [{"id": "node-1", "address": "localhost:8001", "state": "Up"}],
            "counters": [
                {"key": "test-demo-flow", "count": 20, "limit": 10, "remaining": 0}
            ],
            "node_metrics": {},
            "redis_connected": True,
        }

        violations = checker.check(observation)

        assert len(violations) >= 1, f"Expected at least 1 violation, got {len(violations)}"

        over_limit = [v for v in violations if v.invariant_name == "over_limit"]
        assert len(over_limit) == 1, f"Expected 1 over_limit violation, got {len(over_limit)}"

    async def test_health_poller_counters(self):
        """Test health poller correctly fetches counter stats for TUI."""
        from demo.ratelimiter_health import RateLimiterHealthPoller

        poller = RateLimiterHealthPoller()
        poller._running = True
        poller._client = httpx.AsyncClient(timeout=5.0)

        try:
            await poller._poll_health()
            health = poller.get_health()

            assert health is not None, "Health is None"
            assert "counters" in health, "Missing counters key"

            counters = health["counters"]
            test_counter = next(
                (c for c in counters if c["key"] == "test-demo-flow"), None
            )

            assert test_counter is not None, f"Counter not in health poller. Got: {counters}"
            assert test_counter["count"] == 20, f"Expected count 20, got {test_counter['count']}"
            assert test_counter["over_limit"] is True, "Expected over_limit=True"
        finally:
            await poller._client.aclose()

    async def test_agent_context(self):
        """Test agent context gathering works without TiKV-specific errors."""
        from operator_core.agent.context import ContextGatherer, DiagnosisContext
        from operator_core.agent.prompt import build_diagnosis_prompt
        from operator_core.db.tickets import TicketDB
        from operator_core.monitor.types import Ticket, TicketStatus
        from ratelimiter_observer.subject import RateLimiterSubject
        from ratelimiter_observer.ratelimiter_client import RateLimiterClient
        from ratelimiter_observer.redis_client import RedisClient
        from ratelimiter_observer.prom_client import PrometheusClient
        from datetime import datetime
        from pathlib import Path
        import tempfile

        # Create subject with real clients
        async with httpx.AsyncClient(base_url=self.ratelimiter_url, timeout=5.0) as rl_http:
            async with httpx.AsyncClient(base_url="http://localhost:9090", timeout=5.0) as prom_http:
                r = redis.Redis.from_url(self.redis_url, decode_responses=True)
                try:
                    subject = RateLimiterSubject(
                        ratelimiter=RateLimiterClient(http=rl_http),
                        redis=RedisClient(redis=r),
                        prom=PrometheusClient(http=prom_http),
                    )

                    # Create temp DB for test
                    with tempfile.TemporaryDirectory() as tmpdir:
                        db_path = Path(tmpdir) / "test.db"
                        async with TicketDB(db_path) as db:
                            # Create a fake ticket
                            ticket = Ticket(
                                id=1,
                                violation_key="over_limit:test-demo-flow",
                                invariant_name="over_limit",
                                store_id="test-demo-flow",
                                message="Test violation",
                                severity="warning",
                                first_seen_at=datetime.now(),
                                last_seen_at=datetime.now(),
                                occurrence_count=1,
                                status=TicketStatus.OPEN,
                            )

                            # Gather context (this was failing with get_stores error)
                            gatherer = ContextGatherer(subject, db)
                            context = await gatherer.gather(ticket)

                            # Verify context has correct structure
                            assert isinstance(context, DiagnosisContext)
                            assert context.observation is not None, "observation is None"
                            assert "nodes" in context.observation, "Missing nodes in observation"
                            assert "counters" in context.observation, "Missing counters in observation"

                            # Build prompt (this was also failing)
                            prompt = build_diagnosis_prompt(context)
                            assert "over_limit" in prompt, "Ticket info not in prompt"
                            assert "Cluster State" in prompt, "Cluster state not in prompt"
                finally:
                    await r.aclose()

    async def test_monitor_flow(self):
        """Test full monitor observation -> check -> violation flow."""
        from ratelimiter_observer.subject import RateLimiterSubject
        from ratelimiter_observer.ratelimiter_client import RateLimiterClient
        from ratelimiter_observer.redis_client import RedisClient
        from ratelimiter_observer.prom_client import PrometheusClient
        from ratelimiter_observer.invariants import RateLimiterInvariantChecker

        async with httpx.AsyncClient(base_url=self.ratelimiter_url, timeout=5.0) as rl_http:
            async with httpx.AsyncClient(base_url="http://localhost:9090", timeout=5.0) as prom_http:
                r = redis.Redis.from_url(self.redis_url, decode_responses=True)
                try:
                    subject = RateLimiterSubject(
                        ratelimiter=RateLimiterClient(http=rl_http),
                        redis=RedisClient(redis=r),
                        prom=PrometheusClient(http=prom_http),
                    )

                    checker = RateLimiterInvariantChecker()

                    # Get observation (like monitor does)
                    observation = await subject.observe()

                    assert "nodes" in observation, "Missing nodes"
                    assert "counters" in observation, "Missing counters"
                    assert len(observation["counters"]) > 0, "No counters in observation"

                    # Check for violations (like monitor does)
                    violations = checker.check(observation)

                    # Should find at least the test counter violation
                    over_limit = [v for v in violations if v.invariant_name == "over_limit"]
                    assert len(over_limit) >= 1, f"Expected over_limit violation. Got: {violations}"
                finally:
                    await r.aclose()

    async def test_tui_panel_display(self):
        """Test what TUI panels will display - simulates _format_workload_panel."""
        from demo.tui_integration import TUIDemoController

        # Create a mock health dict like the health poller produces
        health = {
            "nodes": [
                {"id": "node-1", "address": "ratelimiter-1:8000", "state": "Up"},
                {"id": "node-2", "address": "ratelimiter-2:8000", "state": "Up"},
                {"id": "node-3", "address": "ratelimiter-3:8000", "state": "Up"},
            ],
            "redis_connected": True,
            "has_issues": False,
            "counters": [
                {"key": "test-demo-flow", "count": 20, "limit": 10, "over_limit": True},
            ],
        }

        # Create controller just to test formatting methods
        controller = TUIDemoController(
            subject_name="ratelimiter",
            chapters=[],
            health_poller=None,  # Not used for format test
        )

        # Test workload panel formatting
        workload_content = controller._format_workload_panel(health)

        assert "Rate Limit Counters" in workload_content, "Missing title"
        assert "OVER LIMIT" in workload_content, "Missing over limit indicator"
        assert "test-demo-flow" in workload_content, "Missing counter key"
        assert "20/10" in workload_content, "Missing count/limit"

        # Test cluster health panel formatting
        health_content = controller._format_health_panel(health)

        assert "Rate Limiter Cluster" in health_content, "Missing cluster title"
        assert "ratelimiter-1" in health_content or "node-1" in health_content, "Missing node"
        assert "Up" in health_content, "Missing Up status"

    async def test_monitor_persistence(self):
        """Test that violations persist across multiple check cycles (simulates demo flow)."""
        from ratelimiter_observer.subject import RateLimiterSubject
        from ratelimiter_observer.ratelimiter_client import RateLimiterClient
        from ratelimiter_observer.redis_client import RedisClient
        from ratelimiter_observer.prom_client import PrometheusClient
        from ratelimiter_observer.invariants import RateLimiterInvariantChecker
        from demo.ratelimiter_chaos import inject_redis_pause

        # Clear and inject fresh counter
        r = redis.Redis.from_url(self.redis_url, decode_responses=True)
        await r.delete("ratelimit:counter-drift-demo")
        await r.aclose()

        await inject_redis_pause()

        async with httpx.AsyncClient(base_url=self.ratelimiter_url, timeout=5.0) as rl_http:
            async with httpx.AsyncClient(base_url="http://localhost:9090", timeout=5.0) as prom_http:
                r = redis.Redis.from_url(self.redis_url, decode_responses=True)
                try:
                    subject = RateLimiterSubject(
                        ratelimiter=RateLimiterClient(http=rl_http),
                        redis=RedisClient(redis=r),
                        prom=PrometheusClient(http=prom_http),
                    )
                    checker = RateLimiterInvariantChecker()

                    # Check immediately
                    obs1 = await subject.observe()
                    v1 = checker.check(obs1)
                    assert len(v1) >= 1, f"Check 1: Expected violations, got {len(v1)}"

                    # Wait 5 seconds and check again
                    await asyncio.sleep(5)

                    obs2 = await subject.observe()
                    v2 = checker.check(obs2)
                    assert len(v2) >= 1, f"Check 2: Expected violations after 5s, got {len(v2)}"

                    # Wait 5 more seconds and check again
                    await asyncio.sleep(5)

                    obs3 = await subject.observe()
                    v3 = checker.check(obs3)
                    assert len(v3) >= 1, f"Check 3: Expected violations after 10s, got {len(v3)}"

                finally:
                    await r.aclose()

    async def cleanup(self):
        """Clean up test data from Redis."""
        r = redis.Redis.from_url(self.redis_url, decode_responses=True)
        try:
            await r.delete("ratelimit:test-demo-flow")
        finally:
            await r.aclose()


async def main():
    test = DemoFlowTest()
    success = await test.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
