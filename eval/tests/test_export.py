"""Tests for eval.export — static HTML campaign export."""

import json

import pytest

from eval.export import (
    _enrich_trial,
    build_export_data,
    render_html,
    safe_json_for_script,
)
from eval.types import Campaign, Trial


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trial(
    trial_id=1,
    campaign_id=1,
    resolved=True,
    chaos_type="node_kill",
    commands=None,
    operator_data=None,
) -> Trial:
    """Create a minimal Trial for testing."""
    chaos_meta = {"chaos_type": chaos_type}
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
        chaos_metadata=json.dumps(chaos_meta),
        commands_json=json.dumps(commands or []),
        operator_data_json=json.dumps(operator_data or {}),
    )


def _make_campaign(campaign_id=1, name="test-campaign") -> Campaign:
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
    """In-memory DB implementing the subset of EvalDBProtocol we need."""

    def __init__(self, campaign: Campaign, trials: list[Trial]):
        self._campaign = campaign
        self._trials = trials

    async def get_campaign(self, campaign_id: int):
        if self._campaign and self._campaign.id == campaign_id:
            return self._campaign
        return None

    async def get_trials(self, campaign_id: int):
        return [t for t in self._trials if t.campaign_id == campaign_id]


# ---------------------------------------------------------------------------
# safe_json_for_script
# ---------------------------------------------------------------------------

class TestSafeJsonForScript:
    def test_escapes_closing_script_tag(self):
        data = {"text": "foo</script>bar"}
        result = safe_json_for_script(data)
        assert "</script>" not in result
        assert r"<\/script>" in result
        # Round-trip: can be parsed back
        parsed = json.loads(result.replace(r"<\/", "</").replace(r"<\!--", "<!--"))
        assert parsed["text"] == "foo</script>bar"

    def test_escapes_html_comment(self):
        data = {"text": "<!--injected-->"}
        result = safe_json_for_script(data)
        assert "<!--" not in result
        assert r"<\!--" in result

    def test_simple_data_unchanged(self):
        data = {"count": 42, "name": "hello"}
        result = safe_json_for_script(data)
        assert json.loads(result) == data


# ---------------------------------------------------------------------------
# _enrich_trial
# ---------------------------------------------------------------------------

class TestEnrichTrial:
    def test_success_trial(self):
        trial = _make_trial(resolved=True, chaos_type="node_kill")
        result = _enrich_trial(trial)

        assert result["outcome"] == "success"
        assert result["chaos_type"] == "node_kill"
        assert result["detect_sec"] == 10.0
        assert result["resolve_sec"] == 30.0
        assert result["is_baseline"] is False

    def test_timeout_trial(self):
        trial = _make_trial(resolved=False, chaos_type="latency")
        result = _enrich_trial(trial)

        assert result["outcome"] == "timeout"
        assert result["detect_sec"] is None
        assert result["resolve_sec"] is None

    def test_baseline_trial(self):
        trial = _make_trial(chaos_type="none")
        result = _enrich_trial(trial)

        assert result["is_baseline"] is True
        assert result["group_key"] == "baseline"

    def test_commands_with_reasoning(self):
        cmds = [
            {
                "tool_params": json.dumps({"command": "pd-ctl region", "reasoning": "Check regions"}),
                "timestamp": "2025-01-01T00:00:25+00:00",
            },
            {
                "tool_params": json.dumps({"command": "tikv-ctl compact", "reasoning": "Compact data"}),
                "timestamp": "2025-01-01T00:00:30+00:00",
            },
        ]
        trial = _make_trial(commands=cmds)
        result = _enrich_trial(trial)

        assert result["cmd_count"] == 2
        assert result["commands_with_reasoning"][0]["command"] == "pd-ctl region"
        assert result["commands_with_reasoning"][0]["reasoning"] == "Check regions"
        assert result["commands_with_reasoning"][1]["elapsed_seconds"] == 5.0

    def test_operator_data_enrichment(self):
        op_data = {
            "monitor_detection": {
                "invariant_name": "store_down",
                "message": "Store 4 is Down",
                "first_seen_at": "2025-01-01T00:00:20",
            },
            "agent_session": {
                "session_id": "sess-1",
                "status": "completed",
                "outcome_summary": "Restarted TiKV store 4",
            },
            "reasoning_entries": [
                {
                    "entry_type": "text",
                    "content": "Starting diagnosis",
                    "timestamp": "2025-01-01T00:00:22",
                },
            ],
        }
        trial = _make_trial(operator_data=op_data)
        result = _enrich_trial(trial)

        assert result["monitor_detection"]["violation_type"] == "store_down"
        assert result["agent_conclusion"]["outcome_summary"] == "Restarted TiKV store 4"
        assert len(result["reasoning_entries"]) == 1

    def test_code_diff_extraction(self):
        trial = _make_trial()
        trial.final_state = json.dumps({"code_diff": "--- a/f\n+++ b/f\n+new line"})
        result = _enrich_trial(trial)
        assert "+new line" in result["code_diff"]

    def test_code_diff_from_workspace(self):
        trial = _make_trial()
        trial.final_state = json.dumps({
            "code_workspace": {"diff_full": "--- a/x\n+++ b/x\n+added"}
        })
        result = _enrich_trial(trial)
        assert "+added" in result["code_diff"]


# ---------------------------------------------------------------------------
# build_export_data
# ---------------------------------------------------------------------------

class TestBuildExportData:
    @pytest.mark.asyncio
    async def test_basic_structure(self):
        campaign = _make_campaign()
        trials = [
            _make_trial(trial_id=1, resolved=True),
            _make_trial(trial_id=2, resolved=False),
        ]
        db = FakeDB(campaign, trials)
        data = await build_export_data(db, 1)

        assert data["campaign"]["id"] == 1
        assert data["campaign"]["name"] == "test-campaign"
        assert len(data["trials"]) == 2
        assert data["summary"]["total"] == 2
        assert data["summary"]["success_count"] == 1
        assert data["summary"]["win_rate"] == 50

    @pytest.mark.asyncio
    async def test_campaign_not_found(self):
        db = FakeDB(None, [])
        with pytest.raises(ValueError, match="not found"):
            await build_export_data(db, 999)

    @pytest.mark.asyncio
    async def test_empty_campaign(self):
        campaign = _make_campaign()
        campaign.trial_count = 0
        db = FakeDB(campaign, [])
        data = await build_export_data(db, 1)

        assert data["summary"]["total"] == 0
        assert data["summary"]["win_rate"] == 0
        assert data["trials"] == []

    @pytest.mark.asyncio
    async def test_grouping(self):
        campaign = _make_campaign()
        t1 = _make_trial(trial_id=1, chaos_type="node_kill")
        t2 = _make_trial(trial_id=2, chaos_type="node_kill")
        t3 = _make_trial(trial_id=3, chaos_type="latency")
        t3.chaos_metadata = json.dumps({"chaos_type": "latency", "min_ms": 50, "max_ms": 150})
        db = FakeDB(campaign, [t1, t2, t3])
        data = await build_export_data(db, 1)

        # Sorted by group_key: latency < node_kill alphabetically
        # So latency (1 trial) comes first, then node_kill (2 trials)
        groups = [(t["group_key"], t["group_first"], t["group_size"]) for t in data["trials"]]
        latency_trials = [t for t in data["trials"] if t["chaos_type"] == "latency"]
        nk_trials = [t for t in data["trials"] if t["chaos_type"] == "node_kill"]

        assert len(latency_trials) == 1
        assert latency_trials[0]["group_first"] is True
        assert latency_trials[0]["group_size"] == 1

        assert len(nk_trials) == 2
        assert nk_trials[0]["group_first"] is True
        assert nk_trials[0]["group_size"] == 2
        assert nk_trials[1]["group_first"] is False


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

class TestRenderHtml:
    def test_html_structure(self):
        data = {
            "campaign": {
                "id": 1,
                "name": "test",
                "subject_name": "tikv",
                "variant_name": "default",
                "baseline": False,
                "trial_count": 1,
                "created_at": "2025-01-01T00:00:00",
            },
            "trials": [],
            "summary": {"total": 0, "success_count": 0, "win_rate": 0, "median_detect": None, "median_resolve": None},
            "topology_svg": "",
        }
        html = render_html(data)

        assert html.startswith("<!DOCTYPE html>")
        assert "<title>Campaign: test</title>" in html
        assert "window.__EXPORT_DATA__" in html
        # CSS and JS are embedded
        assert ":root {" in html
        assert "function esc(s)" in html

    def test_script_escaping_in_rendered_html(self):
        data = {
            "campaign": {
                "id": 1,
                "name": "test</script><script>alert(1)",
                "subject_name": "x",
                "variant_name": "default",
                "baseline": False,
                "trial_count": 0,
                "created_at": "",
            },
            "trials": [],
            "summary": {"total": 0, "success_count": 0, "win_rate": 0, "median_detect": None, "median_resolve": None},
            "topology_svg": "",
        }
        html = render_html(data)
        # The embedded JSON must not contain raw </script>
        # Find the DATA assignment
        start = html.index("window.__EXPORT_DATA__")
        end = html.index(";</script>", start)
        json_section = html[start:end]
        assert "</script>" not in json_section


# ---------------------------------------------------------------------------
# End-to-end with real SQLite
# ---------------------------------------------------------------------------

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_export_with_sqlite(self, tmp_path):
        from eval.runner.db import EvalDB

        db_path = tmp_path / "test.db"
        db = EvalDB(db_path)
        await db.ensure_schema()

        campaign = Campaign(
            subject_name="tikv",
            name="e2e-test",
            trial_count=1,
            created_at="2025-01-01T00:00:00+00:00",
        )
        campaign_id = await db.insert_campaign(campaign)

        trial = Trial(
            campaign_id=campaign_id,
            started_at="2025-01-01T00:00:00+00:00",
            chaos_injected_at="2025-01-01T00:00:05+00:00",
            ticket_created_at="2025-01-01T00:00:15+00:00",
            resolved_at="2025-01-01T00:00:30+00:00",
            ended_at="2025-01-01T00:01:00+00:00",
            initial_state="{}",
            final_state="{}",
            chaos_metadata=json.dumps({"chaos_type": "node_kill"}),
            commands_json="[]",
            operator_data_json="{}",
        )
        await db.insert_trial(trial)

        from eval.export import export_campaign_html
        html = await export_campaign_html(db, campaign_id)

        assert "<!DOCTYPE html>" in html
        assert "e2e-test" in html
        assert "node_kill" in html
        # Verify JSON blob is parseable
        marker = "window.__EXPORT_DATA__ = "
        start = html.index(marker) + len(marker)
        end = html.index(";</script>", start)
        embedded_json = html[start:end]
        data = json.loads(embedded_json)
        assert data["campaign"]["name"] == "e2e-test"
        assert len(data["trials"]) == 1
        assert data["trials"][0]["outcome"] == "success"
