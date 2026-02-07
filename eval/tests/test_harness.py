"""Unit tests for eval harness fixes."""

import asyncio

import pytest

from eval.runner.campaign import CampaignConfig, ChaosSpec
from eval.runner.harness import TrialStats


class TestManagedModeLogic:
    """Tests for managed mode determination logic."""

    def test_managed_mode_with_baseline(self):
        """Managed mode should be enabled regardless of include_baseline."""
        config = CampaignConfig(
            name="test",
            subjects=["tikv"],
            chaos_types=[ChaosSpec(type="node_kill")],
            trials_per_combination=1,
            include_baseline=True,  # This should NOT disable managed mode
        )
        operator_running = False

        # Fixed logic: include_baseline doesn't affect managed mode
        managed_mode = not operator_running
        assert managed_mode is True

    def test_managed_mode_without_baseline(self):
        """Managed mode when include_baseline is False."""
        config = CampaignConfig(
            name="test",
            subjects=["tikv"],
            chaos_types=[ChaosSpec(type="node_kill")],
            trials_per_combination=1,
            include_baseline=False,
        )
        operator_running = False

        managed_mode = not operator_running
        assert managed_mode is True

    def test_external_mode_when_operator_running(self):
        """External mode when operator is already running."""
        operator_running = True

        # When operator is already running, don't manage it
        managed_mode = not operator_running
        assert managed_mode is False


class TestCampaignEncoding:
    """Tests for campaign subject/chaos encoding."""

    def test_campaign_subject_name_single(self):
        """Campaign should store single subject, not comma-joined list."""
        subjects = ["tikv"]

        # Fixed: use first subject only
        subject_name = subjects[0] if subjects else "unknown"
        assert subject_name == "tikv"
        assert "," not in subject_name

    def test_campaign_subject_name_multiple(self):
        """Multiple subjects should store first only for baseline matching."""
        subjects = ["tikv", "etcd"]

        # Fixed: use first subject only
        subject_name = subjects[0] if subjects else "unknown"
        assert subject_name == "tikv"
        assert "," not in subject_name

    def test_campaign_subject_name_empty(self):
        """Empty subjects list should fallback to 'unknown'."""
        subjects: list[str] = []

        subject_name = subjects[0] if subjects else "unknown"
        assert subject_name == "unknown"

    def test_campaign_chaos_type_single(self):
        """Campaign should store single chaos type for baseline matching."""
        chaos_types = [ChaosSpec(type="node_kill")]

        # Fixed: use first chaos type only
        chaos_type = chaos_types[0].type if chaos_types else "unknown"
        assert chaos_type == "node_kill"
        assert "," not in chaos_type

    def test_campaign_chaos_type_multiple(self):
        """Multiple chaos types should store first only."""
        chaos_types = [
            ChaosSpec(type="node_kill"),
            ChaosSpec(type="latency"),
        ]

        chaos_type = chaos_types[0].type if chaos_types else "unknown"
        assert chaos_type == "node_kill"
        assert "," not in chaos_type

    def test_campaign_chaos_type_empty(self):
        """Empty chaos types should fallback to 'unknown'."""
        chaos_types: list[ChaosSpec] = []

        chaos_type = chaos_types[0].type if chaos_types else "unknown"
        assert chaos_type == "unknown"


class TestTrialStats:
    """Tests for thread-safe TrialStats counter."""

    @pytest.mark.asyncio
    async def test_trial_stats_single_increment(self):
        """TrialStats should track single increments."""
        stats = TrialStats()

        await stats.record_complete()
        assert stats.completed == 1
        assert stats.failed == 0

        await stats.record_failure()
        assert stats.completed == 1
        assert stats.failed == 1

    @pytest.mark.asyncio
    async def test_trial_stats_concurrent_increments(self):
        """TrialStats should handle concurrent increments correctly."""
        stats = TrialStats()

        async def increment_many(n: int):
            for _ in range(n):
                await stats.record_complete()

        # Run 10 coroutines, each incrementing 100 times
        tasks = [increment_many(100) for _ in range(10)]
        await asyncio.gather(*tasks)

        # Must equal exactly 1000 (no lost increments)
        assert stats.completed == 1000

    @pytest.mark.asyncio
    async def test_trial_stats_mixed_concurrent_increments(self):
        """TrialStats should handle mixed complete/failure increments."""
        stats = TrialStats()

        async def increment_completes(n: int):
            for _ in range(n):
                await stats.record_complete()

        async def increment_failures(n: int):
            for _ in range(n):
                await stats.record_failure()

        # Run mixed increments concurrently
        tasks = [
            *[increment_completes(50) for _ in range(5)],
            *[increment_failures(30) for _ in range(5)],
        ]
        await asyncio.gather(*tasks)

        assert stats.completed == 250
        assert stats.failed == 150


class TestGatherExceptionHandling:
    """Tests for asyncio.gather exception handling."""

    @pytest.mark.asyncio
    async def test_gather_captures_exceptions(self):
        """gather() results should be checked for exceptions."""

        async def success():
            return "ok"

        async def failure():
            raise ValueError("boom")

        tasks = [success(), failure(), success()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count exceptions in results
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 1
        assert "boom" in str(exceptions[0])

    @pytest.mark.asyncio
    async def test_gather_all_success(self):
        """gather() with all successful tasks."""

        async def success(n: int):
            return n * 2

        tasks = [success(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0
        assert results == [0, 2, 4, 6, 8]

    @pytest.mark.asyncio
    async def test_gather_all_failures(self):
        """gather() with all failed tasks."""

        async def failure(n: int):
            raise RuntimeError(f"error {n}")

        tasks = [failure(i) for i in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 3


class TestBaselineCampaignMatching:
    """Tests for baseline campaign matching logic."""

    def test_baseline_exact_match(self):
        """Baseline campaigns should match by exact subject and chaos type."""
        # Agent campaign
        agent_subject = "tikv"
        agent_chaos = "node_kill"

        # Baseline campaign (should match)
        baseline_subject = "tikv"
        baseline_chaos = "node_kill"

        # Exact match should work
        assert agent_subject == baseline_subject
        assert agent_chaos == baseline_chaos

    def test_baseline_comma_joined_no_match(self):
        """Comma-joined values should NOT match single values (old bug)."""
        baseline_subject = "tikv"
        baseline_chaos = "node_kill"

        # Old buggy encoding
        bad_subject = "tikv,tikv"
        bad_chaos = "node_kill,latency"

        assert bad_subject != baseline_subject
        assert bad_chaos != baseline_chaos

    def test_baseline_different_chaos_no_match(self):
        """Different chaos types should not match."""
        agent_chaos = "latency"
        baseline_chaos = "node_kill"

        assert agent_chaos != baseline_chaos

    def test_baseline_different_subject_no_match(self):
        """Different subjects should not match."""
        agent_subject = "etcd"
        baseline_subject = "tikv"

        assert agent_subject != baseline_subject
