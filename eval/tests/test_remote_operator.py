"""Tests for remote operator integration in cloud eval trials.

Verifies the full data pipeline: SSH -> operator.db -> SCP -> extract
-> Trial record with populated metrics.
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.runner.remote_operator import (
    AGENT_CONTAINER,
    DATA_VOLUME,
    MONITOR_CONTAINER,
    OPERATOR_DB_PATH,
    RemoteOperatorProcesses,
)
from eval.types import Trial, VariantConfig


class MockVM:
    """Mock CloudVM that simulates SSH responses for testing."""

    def __init__(self):
        self.commands_run: list[str] = []
        self._responses: dict[str, tuple[int, str, str]] = {}
        self._default_response = (0, "", "")
        self._operator_db_path: Path | None = None
        # Default: agent container health check passes
        self.set_response("docker inspect", 0, "true")
        # Default: operator.db exists check passes
        self.set_response("test -f", 0, "exists")

    def set_response(self, pattern: str, exit_code: int, stdout: str, stderr: str = ""):
        """Set a canned response for commands matching a pattern."""
        self._responses[pattern] = (exit_code, stdout, stderr)

    def set_operator_db(self, db_path: Path):
        """Set the operator.db path for download_file simulation."""
        self._operator_db_path = db_path

    async def run_command(self, cmd: str, timeout_sec: float = 60.0) -> tuple[int, str, str]:
        """Simulate SSH command execution."""
        self.commands_run.append(cmd)

        # Check for pattern matches
        for pattern, response in self._responses.items():
            if pattern in cmd:
                return response

        return self._default_response

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Simulate SCP file download."""
        if self._operator_db_path and self._operator_db_path.exists():
            import shutil
            shutil.copy2(self._operator_db_path, local_path)

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Simulate SCP file upload."""
        pass

    @property
    def instance_id(self) -> str:
        return "test-vm-1234"

    @property
    def external_ip(self) -> str:
        return "1.2.3.4"


def create_test_operator_db(
    db_path: Path,
    ticket_created_at: str = "2025-01-01T00:00:10+00:00",
    resolved_at: str | None = "2025-01-01T00:01:00+00:00",
    commands: list[dict] | None = None,
) -> None:
    """Create a test operator.db with ticket and agent log data."""
    conn = sqlite3.connect(db_path)

    # Create tables (matching operator-core schema)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY,
            violation_key TEXT,
            severity TEXT DEFAULT 'warning',
            title TEXT,
            description TEXT,
            status TEXT DEFAULT 'open',
            first_seen_at TEXT,
            resolved_at TEXT,
            held INTEGER DEFAULT 0,
            variant_model TEXT,
            variant_system_prompt TEXT,
            variant_tools_config TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id TEXT PRIMARY KEY,
            started_at TEXT,
            ended_at TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_log_entries (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            entry_type TEXT,
            tool_name TEXT,
            tool_params TEXT,
            exit_code INTEGER,
            timestamp TEXT
        );
    """)

    # Insert ticket
    conn.execute(
        "INSERT INTO tickets (id, violation_key, title, status, first_seen_at, resolved_at) "
        "VALUES (1, 'test_violation', 'Test ticket', ?, ?, ?)",
        ("resolved" if resolved_at else "open", ticket_created_at, resolved_at),
    )

    # Insert agent session
    conn.execute(
        "INSERT INTO agent_sessions (session_id, started_at) VALUES ('session-1', '2025-01-01T00:00:05+00:00')"
    )

    # Insert commands
    if commands is None:
        commands = [
            {"tool_name": "shell", "tool_params": '{"command": "docker ps"}', "exit_code": 0},
            {"tool_name": "shell", "tool_params": '{"command": "docker start tikv-0"}', "exit_code": 0},
        ]

    for i, cmd in enumerate(commands):
        conn.execute(
            "INSERT INTO agent_log_entries (session_id, entry_type, tool_name, tool_params, exit_code, timestamp) "
            "VALUES ('session-1', 'tool_call', ?, ?, ?, ?)",
            (cmd["tool_name"], cmd["tool_params"], cmd["exit_code"], f"2025-01-01T00:00:{10+i:02d}+00:00"),
        )

    conn.commit()
    conn.close()


class TestRemoteOperatorProcesses:
    """Tests for RemoteOperatorProcesses lifecycle."""

    @pytest.mark.asyncio
    async def test_start_pulls_image_and_runs_containers(self):
        """Start should pull image, create volume, and run monitor + agent."""
        vm = MockVM()
        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with patch("eval.runner.remote_operator.asyncio.sleep", new_callable=AsyncMock):
            await remote_op.start()

        # Verify commands were issued
        assert any("docker pull" in cmd for cmd in vm.commands_run)
        assert any("docker volume create" in cmd for cmd in vm.commands_run)
        assert any(MONITOR_CONTAINER in cmd and "docker run" in cmd for cmd in vm.commands_run)
        assert any(AGENT_CONTAINER in cmd and "docker run" in cmd for cmd in vm.commands_run)
        assert remote_op._started is True

    @pytest.mark.asyncio
    async def test_start_uses_host_network_and_docker_socket(self):
        """Containers should use host networking and mount Docker socket."""
        vm = MockVM()
        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with patch("eval.runner.remote_operator.asyncio.sleep", new_callable=AsyncMock):
            await remote_op.start()

        # Find the docker run commands
        run_cmds = [cmd for cmd in vm.commands_run if "docker run" in cmd]
        for cmd in run_cmds:
            assert "--network=host" in cmd
            assert "/var/run/docker.sock" in cmd

    @pytest.mark.asyncio
    async def test_stop_removes_containers(self):
        """Stop should remove both containers."""
        vm = MockVM()
        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with patch("eval.runner.remote_operator.asyncio.sleep", new_callable=AsyncMock):
            await remote_op.start()
        vm.commands_run.clear()
        await remote_op.stop()

        assert any(AGENT_CONTAINER in cmd for cmd in vm.commands_run)
        assert any(MONITOR_CONTAINER in cmd for cmd in vm.commands_run)
        assert remote_op._started is False

    @pytest.mark.asyncio
    async def test_start_fails_on_pull_error(self):
        """Start should raise if image pull fails."""
        vm = MockVM()
        vm.set_response("docker pull", 1, "", "Error: image not found")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="bad-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with pytest.raises(RuntimeError, match="Failed to pull"):
            await remote_op.start()

    @pytest.mark.asyncio
    async def test_start_cleans_up_monitor_if_agent_fails(self):
        """If agent container fails to start, monitor should be cleaned up."""
        vm = MockVM()
        # Agent run command fails
        vm.set_response(f"--name {AGENT_CONTAINER}", 1, "", "Error: agent failed")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with pytest.raises(RuntimeError, match="Failed to start agent"):
            await remote_op.start()

        # Monitor should have been cleaned up
        assert any("docker rm -f" in cmd and MONITOR_CONTAINER in cmd for cmd in vm.commands_run)


class TestRemoteOperatorDBQueries:
    """Tests for remote DB query methods."""

    @pytest.mark.asyncio
    async def test_get_max_ticket_id_returns_max(self):
        """get_max_ticket_id should return the highest ticket ID."""
        vm = MockVM()
        vm.set_response(
            "python3",
            0,
            '[{"max_id": 5}]',
        )

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        result = await remote_op.get_max_ticket_id()
        assert result == 5

    @pytest.mark.asyncio
    async def test_get_max_ticket_id_returns_zero_when_empty(self):
        """get_max_ticket_id should return 0 when no tickets exist."""
        vm = MockVM()
        vm.set_response(
            "python3",
            0,
            '[{"max_id": null}]',
        )

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        result = await remote_op.get_max_ticket_id()
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_max_ticket_id_handles_query_failure(self):
        """get_max_ticket_id should return 0 on query failure."""
        vm = MockVM()
        vm.set_response("python3", 1, "", "Error")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        result = await remote_op.get_max_ticket_id()
        assert result == 0


class TestRemoteOperatorTicketResolution:
    """Tests for ticket resolution waiting."""

    @pytest.mark.asyncio
    async def test_wait_resolves_immediately_if_already_resolved(self):
        """Should return immediately if ticket is already resolved."""
        vm = MockVM()
        vm.set_response(
            "python3",
            0,
            '[{"first_seen_at": "2025-01-01T00:00:10+00:00", '
            '"resolved_at": "2025-01-01T00:01:00+00:00", '
            '"status": "resolved"}]',
        )

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        created, resolved = await remote_op.wait_for_ticket_resolution(
            timeout_sec=5.0, min_ticket_id=0,
        )
        assert created == "2025-01-01T00:00:10+00:00"
        assert resolved == "2025-01-01T00:01:00+00:00"

    @pytest.mark.asyncio
    async def test_wait_returns_none_on_timeout(self):
        """Should return (None, None) if no ticket appears before timeout."""
        vm = MockVM()
        vm.set_response("python3", 0, "[]")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        created, resolved = await remote_op.wait_for_ticket_resolution(
            timeout_sec=1.0, min_ticket_id=0,
        )
        assert created is None
        assert resolved is None

    @pytest.mark.asyncio
    async def test_wait_returns_created_on_timeout_if_detected(self):
        """Should return (created, None) if ticket detected but not resolved."""
        vm = MockVM()
        vm.set_response(
            "python3",
            0,
            '[{"first_seen_at": "2025-01-01T00:00:10+00:00", '
            '"resolved_at": null, '
            '"status": "open"}]',
        )

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        remote_op._started = True

        created, resolved = await remote_op.wait_for_ticket_resolution(
            timeout_sec=1.0, min_ticket_id=0,
        )
        assert created == "2025-01-01T00:00:10+00:00"
        assert resolved is None


class TestOperatorTrialIntegration:
    """Integration tests verifying the full trial data pipeline.

    These tests verify that trial state captured on the remote VM
    via operator.db makes it through to the Trial record.
    """

    @pytest.mark.asyncio
    async def test_operator_trial_captures_all_metrics(self):
        """Trial with operator should have ticket_created_at, resolved_at, and commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test operator.db
            db_path = Path(tmpdir) / "operator.db"
            create_test_operator_db(
                db_path,
                ticket_created_at="2025-01-01T00:00:10+00:00",
                resolved_at="2025-01-01T00:01:00+00:00",
                commands=[
                    {"tool_name": "shell", "tool_params": '{"command": "docker ps"}', "exit_code": 0},
                    {"tool_name": "shell", "tool_params": '{"command": "docker start tikv-0"}', "exit_code": 0},
                ],
            )

            # Mock VM that returns ticket data and serves the db file
            vm = MockVM()
            vm.set_operator_db(db_path)

            # Set up responses for the full trial lifecycle
            # force_resolve returns 0 tickets resolved
            vm.set_response("UPDATE tickets", 0, "0")
            # get_max_ticket_id returns 0
            vm.set_response("MAX(id)", 0, '[{"max_id": 0}]')
            # wait_for_ticket_resolution finds resolved ticket
            vm.set_response(
                "first_seen_at",
                0,
                '[{"first_seen_at": "2025-01-01T00:00:10+00:00", '
                '"resolved_at": "2025-01-01T00:01:00+00:00", '
                '"status": "resolved"}]',
            )
            # docker cp succeeds
            vm.set_response("docker cp", 0, "")

            remote_op = RemoteOperatorProcesses(
                vm=vm,
                operator_image="test-registry/operator:latest",
                anthropic_api_key="test-key",
            )
            remote_op._started = True

            # Run the ticket resolution + command extraction flow
            created, resolved = await remote_op.wait_for_ticket_resolution(
                timeout_sec=5.0, min_ticket_id=0,
            )

            # Download and extract commands
            from eval.runner.harness import extract_commands_from_operator_db

            local_db = Path(tmpdir) / "downloaded.db"
            await remote_op.download_operator_db(local_db)
            commands = await extract_commands_from_operator_db(local_db)

            # Verify all metrics are populated
            assert created is not None
            assert resolved is not None
            assert len(commands) == 2
            assert commands[0]["tool_name"] == "shell"
            assert "docker ps" in commands[0]["tool_params"]

    @pytest.mark.asyncio
    async def test_operator_trial_timeout_preserves_partial_state(self):
        """Trial where agent detects but doesn't resolve should still have ticket_created_at."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create operator.db with unresolved ticket
            db_path = Path(tmpdir) / "operator.db"
            create_test_operator_db(
                db_path,
                ticket_created_at="2025-01-01T00:00:10+00:00",
                resolved_at=None,  # Not resolved
                commands=[
                    {"tool_name": "shell", "tool_params": '{"command": "docker ps"}', "exit_code": 0},
                ],
            )

            vm = MockVM()
            vm.set_operator_db(db_path)
            vm.set_response("docker cp", 0, "")

            # Ticket exists but not resolved
            vm.set_response(
                "first_seen_at",
                0,
                '[{"first_seen_at": "2025-01-01T00:00:10+00:00", '
                '"resolved_at": null, '
                '"status": "open"}]',
            )

            remote_op = RemoteOperatorProcesses(
                vm=vm,
                operator_image="test-registry/operator:latest",
                anthropic_api_key="test-key",
            )
            remote_op._started = True

            created, resolved = await remote_op.wait_for_ticket_resolution(
                timeout_sec=1.0, min_ticket_id=0,
            )

            # Detection happened, but resolution timed out
            assert created == "2025-01-01T00:00:10+00:00"
            assert resolved is None

            # Commands should still be extractable
            from eval.runner.harness import extract_commands_from_operator_db

            local_db = Path(tmpdir) / "downloaded.db"
            await remote_op.download_operator_db(local_db)
            commands = await extract_commands_from_operator_db(local_db)
            assert len(commands) == 1

    @pytest.mark.asyncio
    async def test_no_operator_trial_unchanged(self):
        """Trial without operator should have None ticket/commands (existing behavior)."""
        from eval.types import Trial

        # This mirrors the no-operator path in worker._run_trial
        trial = Trial(
            campaign_id=1,
            started_at="2025-01-01T00:00:00+00:00",
            chaos_injected_at="2025-01-01T00:00:05+00:00",
            ticket_created_at=None,
            resolved_at="2025-01-01T00:01:00+00:00",
            ended_at="2025-01-01T00:01:05+00:00",
            initial_state="{}",
            final_state="{}",
            chaos_metadata="{}",
            commands_json="[]",
        )

        assert trial.ticket_created_at is None
        assert trial.commands_json == "[]"


class TestCampaignOperatorConfig:
    """Tests for operator config in campaign YAML."""

    def test_cloud_config_with_operator(self):
        """CloudConfig should accept operator configuration."""
        from eval.runner.campaign import CloudConfig, OperatorConfig

        config = CloudConfig(
            provider="gcp",
            operator=OperatorConfig(
                enabled=True,
                image="us-central1-docker.pkg.dev/myproject/eval/operator:latest",
            ),
        )

        assert config.operator is not None
        assert config.operator.enabled is True
        assert "operator:latest" in config.operator.image

    def test_cloud_config_without_operator(self):
        """CloudConfig should work without operator (backward compat)."""
        from eval.runner.campaign import CloudConfig

        config = CloudConfig(provider="gcp")

        assert config.operator is None

    def test_cloud_config_operator_disabled_by_default(self):
        """OperatorConfig.enabled should default to False."""
        from eval.runner.campaign import OperatorConfig

        config = OperatorConfig()

        assert config.enabled is False
        assert config.image == ""

    def test_campaign_yaml_with_operator(self):
        """Campaign config should parse operator section from YAML."""
        from eval.runner.campaign import CampaignConfig

        config = CampaignConfig.model_validate({
            "name": "full-eval",
            "subjects": ["tikv"],
            "chaos_types": [{"type": "node_kill"}],
            "cloud": {
                "provider": "gcp",
                "operator": {
                    "enabled": True,
                    "image": "us-central1-docker.pkg.dev/proj/eval/operator:latest",
                },
            },
        })

        assert config.cloud is not None
        assert config.cloud.operator is not None
        assert config.cloud.operator.enabled is True

    def test_campaign_yaml_without_operator(self):
        """Campaign config without operator section should work."""
        from eval.runner.campaign import CampaignConfig

        config = CampaignConfig.model_validate({
            "name": "simple",
            "subjects": ["tikv"],
            "chaos_types": [{"type": "node_kill"}],
            "cloud": {
                "provider": "gcp",
            },
        })

        assert config.cloud is not None
        assert config.cloud.operator is None
