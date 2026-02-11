"""Tests for continuous (non-resetting) trial mode."""

import pytest
from pydantic import ValidationError

from eval.runner.campaign import CampaignConfig, expand_campaign_matrix


class TestCampaignConfigContinuousValidation:
    """Test that continuous mode config validation works correctly."""

    def test_continuous_rejects_parallel_greater_than_1(self):
        """continuous=true with parallel>1 should raise ValidationError."""
        with pytest.raises(ValidationError, match="continuous.*parallel"):
            CampaignConfig(
                name="test",
                chaos_types=[{"type": "missing_index"}],
                continuous=True,
                parallel=2,
            )

    def test_continuous_rejects_include_baseline(self):
        """continuous=true with include_baseline=true should raise ValidationError."""
        with pytest.raises(ValidationError, match="continuous.*include_baseline"):
            CampaignConfig(
                name="test",
                chaos_types=[{"type": "missing_index"}],
                continuous=True,
                include_baseline=True,
            )

    def test_continuous_accepts_parallel_1(self):
        """continuous=true with parallel=1 should be valid."""
        config = CampaignConfig(
            name="test",
            chaos_types=[{"type": "missing_index"}],
            continuous=True,
            parallel=1,
        )
        assert config.continuous is True
        assert config.parallel == 1

    def test_continuous_defaults_to_false(self):
        """continuous should default to False."""
        config = CampaignConfig(
            name="test",
            chaos_types=[{"type": "node_kill"}],
        )
        assert config.continuous is False

    def test_non_continuous_allows_parallel(self):
        """Non-continuous mode should still allow parallel>1."""
        config = CampaignConfig(
            name="test",
            chaos_types=[{"type": "node_kill"}],
            parallel=3,
        )
        assert config.parallel == 3
        assert config.continuous is False


class TestExpandCampaignMatrixContinuous:
    """Test that expand_campaign_matrix assigns sequence numbers correctly."""

    def test_continuous_assigns_sequence_numbers(self):
        """In continuous mode, each trial should get an incrementing sequence_number."""
        config = CampaignConfig(
            name="test-continuous",
            subjects=["chat-db-app"],
            chaos_types=[
                {"type": "missing_index"},
                {"type": "pool_exhaustion"},
                {"type": "streaming_txn"},
            ],
            trials_per_combination=1,
            continuous=True,
        )
        specs = expand_campaign_matrix(config)
        assert len(specs) == 3
        assert specs[0]["sequence_number"] == 0
        assert specs[1]["sequence_number"] == 1
        assert specs[2]["sequence_number"] == 2

    def test_non_continuous_sequence_numbers_are_none(self):
        """In non-continuous mode, all sequence_numbers should be None."""
        config = CampaignConfig(
            name="test-normal",
            chaos_types=[
                {"type": "node_kill"},
                {"type": "latency", "params": {"min_ms": 50, "max_ms": 150}},
            ],
            trials_per_combination=2,
        )
        specs = expand_campaign_matrix(config)
        assert len(specs) == 4  # 2 chaos types x 2 trials
        for spec in specs:
            assert spec["sequence_number"] is None

    def test_continuous_with_multiple_trials_per_combination(self):
        """Multiple trials_per_combination in continuous mode should still sequence correctly."""
        config = CampaignConfig(
            name="test-multi",
            subjects=["chat-db-app"],
            chaos_types=[
                {"type": "missing_index"},
                {"type": "pool_exhaustion"},
            ],
            trials_per_combination=2,
            continuous=True,
        )
        specs = expand_campaign_matrix(config)
        # 2 chaos types x 2 trials = 4 specs
        assert len(specs) == 4
        assert [s["sequence_number"] for s in specs] == [0, 1, 2, 3]

    def test_non_continuous_with_baseline(self):
        """Non-continuous with baseline trials should have None sequence_numbers."""
        config = CampaignConfig(
            name="test-baseline",
            chaos_types=[{"type": "node_kill"}],
            trials_per_combination=1,
            include_baseline=True,
        )
        specs = expand_campaign_matrix(config)
        # 1 chaos trial + 1 baseline trial
        assert len(specs) == 2
        for spec in specs:
            assert spec["sequence_number"] is None
