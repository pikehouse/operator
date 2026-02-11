"""Tests for eval.analysis.behavior — behavioral timeline classification."""

import json
from unittest.mock import MagicMock, patch

import pytest

from eval.analysis.behavior import (
    ACTION_COLORS,
    ActionType,
    BehaviorPhase,
    BehaviorTimeline,
    _compress_timeline,
    classify_trial_behavior,
    classify_campaign_behavior,
)
from eval.types import Campaign, Trial


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trial(
    trial_id=1,
    campaign_id=1,
    resolved=True,
    behavior_json="",
    operator_data=None,
    commands=None,
) -> Trial:
    """Create a minimal Trial for testing."""
    return Trial(
        id=trial_id,
        campaign_id=campaign_id,
        started_at="2025-01-01T00:00:00+00:00",
        chaos_injected_at="2025-01-01T00:00:10+00:00",
        ticket_created_at="2025-01-01T00:00:20+00:00" if resolved else None,
        resolved_at="2025-01-01T00:00:40+00:00" if resolved else None,
        ended_at="2025-01-01T00:01:00+00:00",
        initial_state="{}",
        final_state="{}",
        chaos_metadata=json.dumps({"chaos_type": "node_kill"}),
        commands_json=json.dumps(commands or []),
        operator_data_json=json.dumps(operator_data or {}),
        behavior_json=behavior_json,
    )


def _make_campaign(campaign_id=1, name="test") -> Campaign:
    return Campaign(
        id=campaign_id,
        subject_name="tikv",
        name=name,
        trial_count=2,
        baseline=False,
        variant_name="default",
        created_at="2025-01-01T00:00:00+00:00",
    )


class FakeDB:
    """In-memory DB for testing classify_campaign_behavior."""

    def __init__(self, campaign, trials):
        self._campaign = campaign
        self._trials = trials
        self._behavior_updates = {}

    async def get_campaign(self, campaign_id):
        if self._campaign and self._campaign.id == campaign_id:
            return self._campaign
        return None

    async def get_trials(self, campaign_id):
        return [t for t in self._trials if t.campaign_id == campaign_id]

    async def update_trial_behavior(self, trial_id, behavior_json):
        self._behavior_updates[trial_id] = behavior_json


# ---------------------------------------------------------------------------
# ActionType and color map
# ---------------------------------------------------------------------------

class TestActionTypeAndColors:
    def test_all_action_types_have_colors(self):
        for action_type in ActionType:
            assert action_type.value in ACTION_COLORS, (
                f"Missing color for {action_type.value}"
            )

    def test_color_keys(self):
        for action_type, colors in ACTION_COLORS.items():
            assert "bg" in colors
            assert "text" in colors
            assert "border" in colors
            # All should be hex colors
            assert colors["bg"].startswith("#")
            assert colors["text"].startswith("#")
            assert colors["border"].startswith("#")

    def test_action_type_values(self):
        assert ActionType.INVESTIGATE.value == "investigate"
        assert ActionType.DEPLOY.value == "deploy"
        assert ActionType.BAD_ACTION.value == "bad_action"


# ---------------------------------------------------------------------------
# _compress_timeline
# ---------------------------------------------------------------------------

class TestCompressTimeline:
    def test_empty_input(self):
        assert _compress_timeline([], []) == ""

    def test_reasoning_entries_preferred(self):
        reasoning = [
            {"entry_type": "tool_call", "tool_name": "Bash", "tool_params": json.dumps({"command": "docker ps"}), "content": ""},
        ]
        commands = [{"command": "should not appear"}]
        result = _compress_timeline(reasoning, commands)
        assert "docker ps" in result
        assert "should not appear" not in result

    def test_falls_back_to_commands(self):
        commands = [
            {"tool_params": json.dumps({"command": "curl localhost"}), "timestamp": ""},
        ]
        result = _compress_timeline([], commands)
        assert "curl localhost" in result

    def test_truncation(self):
        long_cmd = "x" * 300
        reasoning = [
            {"entry_type": "tool_call", "tool_name": "Bash", "tool_params": json.dumps({"command": long_cmd}), "content": ""},
        ]
        result = _compress_timeline(reasoning, [], max_chars=50)
        # Each entry should be truncated
        lines = result.split("\n")
        assert len(lines) == 1
        # The content portion should be at most ~50 chars plus prefix
        assert len(lines[0]) < 100

    def test_thinking_entries(self):
        reasoning = [
            {"entry_type": "reasoning", "content": "Let me check the logs", "tool_name": None, "tool_params": None},
        ]
        result = _compress_timeline(reasoning, [])
        assert "(thinking)" in result
        assert "check the logs" in result


# ---------------------------------------------------------------------------
# BehaviorTimeline model
# ---------------------------------------------------------------------------

class TestBehaviorTimeline:
    def test_serialization(self):
        tl = BehaviorTimeline(
            trial_id=1,
            phases=[
                BehaviorPhase(label="check logs", action_type=ActionType.INVESTIGATE),
                BehaviorPhase(label="+index", action_type=ActionType.CHANGE_DB),
            ],
            model_used="claude-haiku-4-5-20251001",
            classified_at="2025-01-01T00:00:00+00:00",
        )
        data = json.loads(tl.model_dump_json())
        assert len(data["phases"]) == 2
        assert data["phases"][0]["label"] == "check logs"
        assert data["phases"][0]["action_type"] == "investigate"
        assert data["phases"][1]["action_type"] == "change_db"

    def test_empty_phases(self):
        tl = BehaviorTimeline(
            trial_id=1,
            phases=[],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )
        assert len(tl.phases) == 0


# ---------------------------------------------------------------------------
# classify_trial_behavior
# ---------------------------------------------------------------------------

class TestClassifyTrialBehavior:
    def test_empty_timeline_returns_empty(self):
        result = classify_trial_behavior([], [], "tikv")
        assert result.phases == []
        assert result.reasoning_summary == ""
        assert result.model_used == "claude-haiku-4-5-20251001"

    @patch("anthropic.Anthropic")
    def test_successful_classification(self, mock_anthropic_cls):
        """Test that valid Haiku response is parsed correctly."""
        # Mock the API response with new {phases, summary} format
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "phases": [
                {"label": "check logs", "action_type": "investigate"},
                {"label": "+index", "action_type": "change_db"},
                {"label": "restart", "action_type": "deploy"},
            ],
            "summary": "The agent investigated TiKV logs, added a database index, then restarted the service.",
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        reasoning = [
            {"entry_type": "tool_call", "tool_name": "Bash",
             "tool_params": json.dumps({"command": "docker logs tikv1"}),
             "content": ""},
        ]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = classify_trial_behavior(reasoning, [], "tikv")

        assert len(result.phases) == 3
        assert result.phases[0].label == "check logs"
        assert result.phases[0].action_type == ActionType.INVESTIGATE
        assert result.phases[1].label == "+index"
        assert result.phases[1].action_type == ActionType.CHANGE_DB
        assert result.phases[2].label == "restart"
        assert result.phases[2].action_type == ActionType.DEPLOY
        assert result.reasoning_summary == "The agent investigated TiKV logs, added a database index, then restarted the service."

    @patch("anthropic.Anthropic")
    def test_markdown_wrapped_response(self, mock_anthropic_cls):
        """Test parsing when Haiku wraps response in markdown code block."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '```json\n{"phases": [{"label": "fix", "action_type": "change_code"}], "summary": "Fixed the code."}\n```'
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        reasoning = [{"entry_type": "tool_call", "tool_name": "Bash",
                       "tool_params": json.dumps({"command": "vim app.py"}),
                       "content": ""}]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = classify_trial_behavior(reasoning, [], "chat-db-app")

        assert len(result.phases) == 1
        assert result.phases[0].action_type == ActionType.CHANGE_CODE
        assert result.reasoning_summary == "Fixed the code."

    @patch("anthropic.Anthropic")
    def test_backward_compat_bare_array(self, mock_anthropic_cls):
        """Old-format bare array response should still work (no summary)."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps([
            {"label": "check logs", "action_type": "investigate"},
        ])
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        reasoning = [{"entry_type": "tool_call", "tool_name": "Bash",
                       "tool_params": json.dumps({"command": "docker ps"}),
                       "content": ""}]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = classify_trial_behavior(reasoning, [], "tikv")

        assert len(result.phases) == 1
        assert result.phases[0].label == "check logs"
        assert result.reasoning_summary == ""

    @patch("anthropic.Anthropic")
    def test_invalid_action_type_defaults(self, mock_anthropic_cls):
        """Unknown action_type should default to INVESTIGATE."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "phases": [{"label": "something", "action_type": "unknown_type"}],
            "summary": "",
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        reasoning = [{"entry_type": "tool_call", "tool_name": "Bash",
                       "tool_params": json.dumps({"command": "echo hi"}),
                       "content": ""}]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = classify_trial_behavior(reasoning, [], "tikv")

        assert len(result.phases) == 1
        assert result.phases[0].action_type == ActionType.INVESTIGATE

    @patch("anthropic.Anthropic")
    def test_api_failure_returns_empty(self, mock_anthropic_cls):
        """API errors should return empty timeline, not crash."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API down")
        mock_anthropic_cls.return_value = mock_client

        reasoning = [{"entry_type": "tool_call", "tool_name": "Bash",
                       "tool_params": json.dumps({"command": "docker ps"}),
                       "content": ""}]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = classify_trial_behavior(reasoning, [], "tikv")

        assert result.phases == []
        assert result.reasoning_summary == ""

    def test_no_api_key_raises(self):
        """Should raise ValueError when ANTHROPIC_API_KEY is not set."""
        reasoning = [{"entry_type": "tool_call", "tool_name": "Bash",
                       "tool_params": json.dumps({"command": "echo hi"}),
                       "content": ""}]

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                classify_trial_behavior(reasoning, [], "tikv")


# ---------------------------------------------------------------------------
# classify_campaign_behavior
# ---------------------------------------------------------------------------

class TestClassifyCampaignBehavior:
    @pytest.mark.asyncio
    async def test_skips_already_classified(self):
        """Trials with existing behavior_json are skipped unless force=True."""
        existing = BehaviorTimeline(
            trial_id=1,
            phases=[BehaviorPhase(label="cached", action_type=ActionType.INVESTIGATE)],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )
        trial = _make_trial(trial_id=1, behavior_json=existing.model_dump_json())
        campaign = _make_campaign()
        db = FakeDB(campaign, [trial])

        results = await classify_campaign_behavior(db, 1, force=False)

        assert len(results) == 1
        assert results[0].phases[0].label == "cached"
        # No DB update needed
        assert 1 not in db._behavior_updates

    @pytest.mark.asyncio
    @patch("eval.analysis.behavior.classify_trial_behavior")
    async def test_classifies_unclassified(self, mock_classify):
        """Trials without behavior_json get classified."""
        mock_classify.return_value = BehaviorTimeline(
            trial_id=0,
            phases=[BehaviorPhase(label="fresh", action_type=ActionType.DEPLOY)],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )

        trial = _make_trial(trial_id=1, behavior_json="")
        campaign = _make_campaign()
        db = FakeDB(campaign, [trial])

        results = await classify_campaign_behavior(db, 1)

        assert len(results) == 1
        assert results[0].phases[0].label == "fresh"
        # DB should have been updated
        assert 1 in db._behavior_updates

    @pytest.mark.asyncio
    @patch("eval.analysis.behavior.classify_trial_behavior")
    async def test_force_reclassifies(self, mock_classify):
        """force=True should re-classify even with existing data."""
        mock_classify.return_value = BehaviorTimeline(
            trial_id=0,
            phases=[BehaviorPhase(label="new", action_type=ActionType.OBSERVE)],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )

        existing = BehaviorTimeline(
            trial_id=1,
            phases=[BehaviorPhase(label="old", action_type=ActionType.INVESTIGATE)],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )
        trial = _make_trial(trial_id=1, behavior_json=existing.model_dump_json())
        campaign = _make_campaign()
        db = FakeDB(campaign, [trial])

        results = await classify_campaign_behavior(db, 1, force=True)

        assert results[0].phases[0].label == "new"
        assert 1 in db._behavior_updates

    @pytest.mark.asyncio
    async def test_campaign_not_found(self):
        db = FakeDB(None, [])
        with pytest.raises(ValueError, match="not found"):
            await classify_campaign_behavior(db, 999)

    @pytest.mark.asyncio
    @patch("eval.analysis.behavior.classify_trial_behavior")
    async def test_single_trial_filter(self, mock_classify):
        """trial_id parameter should filter to just that trial."""
        mock_classify.return_value = BehaviorTimeline(
            trial_id=0,
            phases=[BehaviorPhase(label="target", action_type=ActionType.DEPLOY)],
            model_used="test",
            classified_at="2025-01-01T00:00:00",
        )

        t1 = _make_trial(trial_id=1, behavior_json="")
        t2 = _make_trial(trial_id=2, behavior_json="")
        campaign = _make_campaign()
        db = FakeDB(campaign, [t1, t2])

        results = await classify_campaign_behavior(db, 1, trial_id=2)

        assert len(results) == 1
        assert mock_classify.call_count == 1
        assert 2 in db._behavior_updates
        assert 1 not in db._behavior_updates
