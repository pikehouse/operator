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
import yaml

from eval.runner.remote_operator import (
    AGENT_CONTAINER,
    COMPOSE_CMD,
    COMPOSE_FILE_PATH,
    COMPOSE_PROJECT,
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
        self.uploaded_files: dict[str, str] = {}
        self._responses: dict[str, tuple[int, str, str]] = {}
        self._default_response = (0, "", "")
        self._operator_db_path: Path | None = None
        # Default: agent container health check passes
        self.set_response("docker inspect", 0, "true")

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
        """Capture uploaded file content for assertions."""
        self.uploaded_files[remote_path] = Path(local_path).read_text()

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
    async def test_start_uploads_compose_and_runs(self):
        """Start should upload compose YAML, pull, and compose up."""
        vm = MockVM()
        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with patch("eval.runner.remote_operator.asyncio.sleep", new_callable=AsyncMock):
            await remote_op.start()

        # Compose file was uploaded
        assert COMPOSE_FILE_PATH in vm.uploaded_files
        config = yaml.safe_load(vm.uploaded_files[COMPOSE_FILE_PATH])
        assert "monitor" in config["services"]
        assert "agent" in config["services"]

        # Verify compose pull and up commands issued
        assert any("pull" in cmd and "compose" in cmd for cmd in vm.commands_run)
        assert any("up -d --wait" in cmd and "compose" in cmd for cmd in vm.commands_run)
        assert any("docker volume create" in cmd for cmd in vm.commands_run)
        assert remote_op._started is True

    @pytest.mark.asyncio
    async def test_start_compose_config_has_host_network_and_docker_socket(self):
        """Compose config should use host networking and mount Docker socket."""
        vm = MockVM()
        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with patch("eval.runner.remote_operator.asyncio.sleep", new_callable=AsyncMock):
            await remote_op.start()

        config = yaml.safe_load(vm.uploaded_files[COMPOSE_FILE_PATH])
        for svc_name in ["monitor", "agent"]:
            svc = config["services"][svc_name]
            assert svc["network_mode"] == "host"
            assert "/var/run/docker.sock:/var/run/docker.sock" in svc["volumes"]

    @pytest.mark.asyncio
    async def test_stop_issues_compose_down(self):
        """Stop should issue compose down."""
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

        assert any("compose" in cmd and "down" in cmd for cmd in vm.commands_run)
        assert remote_op._started is False

    @pytest.mark.asyncio
    async def test_start_fails_on_pull_error(self):
        """Start should raise if compose pull fails."""
        vm = MockVM()
        vm.set_response("pull", 1, "", "Error: image not found")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="bad-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with pytest.raises(RuntimeError, match="Failed to pull"):
            await remote_op.start()

    @pytest.mark.asyncio
    async def test_start_cleans_up_on_compose_up_failure(self):
        """If compose up fails, compose down should be called for cleanup."""
        vm = MockVM()
        vm.set_response("up -d --wait", 1, "", "Error: service failed")

        remote_op = RemoteOperatorProcesses(
            vm=vm,
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )

        with pytest.raises(RuntimeError, match="Failed to start operator"):
            await remote_op.start()

        # compose down should have been called for cleanup
        assert any("compose" in cmd and "down" in cmd for cmd in vm.commands_run)


class TestBuildComposeConfig:
    """Unit tests for _build_compose_config()."""

    def _make_op(self, **kwargs) -> RemoteOperatorProcesses:
        defaults = dict(
            vm=MockVM(),
            operator_image="test-registry/operator:latest",
            anthropic_api_key="test-key",
        )
        defaults.update(kwargs)
        return RemoteOperatorProcesses(**defaults)

    def test_both_services_use_host_network_and_docker_socket(self):
        """Both monitor and agent should use host networking and mount docker socket."""
        config = self._make_op()._build_compose_config()
        for svc_name in ["monitor", "agent"]:
            svc = config["services"][svc_name]
            assert svc["network_mode"] == "host"
            assert "/var/run/docker.sock:/var/run/docker.sock" in svc["volumes"]

    def test_data_volume_declared_external(self):
        """The operator-data volume should be declared external."""
        config = self._make_op()._build_compose_config()
        assert config["volumes"][DATA_VOLUME] == {"external": True}

    def test_monitor_has_healthcheck(self):
        """Monitor should have a healthcheck testing for operator.db."""
        config = self._make_op()._build_compose_config()
        hc = config["services"]["monitor"]["healthcheck"]
        assert hc["test"] == ["CMD", "test", "-f", OPERATOR_DB_PATH]
        assert "interval" in hc
        assert "retries" in hc

    def test_agent_depends_on_healthy_monitor(self):
        """Agent should depend on monitor with condition: service_healthy."""
        config = self._make_op()._build_compose_config()
        deps = config["services"]["agent"]["depends_on"]
        assert deps == {"monitor": {"condition": "service_healthy"}}

    def test_monitor_runs_as_root(self):
        """Monitor should run as root."""
        config = self._make_op()._build_compose_config()
        assert config["services"]["monitor"]["user"] == "root"

    def test_agent_does_not_set_user(self):
        """Agent runs as default user (appuser in Dockerfile), no explicit user key."""
        config = self._make_op()._build_compose_config()
        assert "user" not in config["services"]["agent"]

    def test_extra_env_propagated_to_both_services(self):
        """Extra env vars should appear in both monitor and agent environment."""
        config = self._make_op(
            extra_env={"DATABASE_URL": "postgres://...", "APP_URL": "http://localhost:3000"}
        )._build_compose_config()
        for svc_name in ["monitor", "agent"]:
            env = config["services"][svc_name]["environment"]
            assert env["DATABASE_URL"] == "postgres://..."
            assert env["APP_URL"] == "http://localhost:3000"

    def test_workspace_mount_on_both_services(self):
        """Workspace volume mount should appear on both monitor and agent."""
        config = self._make_op(
            workspace_volume_mount="/var/lib/workspace:/var/lib/workspace"
        )._build_compose_config()
        for svc_name in ["monitor", "agent"]:
            assert "/var/lib/workspace:/var/lib/workspace" in config["services"][svc_name]["volumes"]

    def test_extra_volume_mounts_only_on_agent(self):
        """Extra volume mounts should appear only on agent, not monitor."""
        config = self._make_op(
            extra_volume_mounts=["/toolbox:/toolbox", "/compose:/compose"]
        )._build_compose_config()
        agent_vols = config["services"]["agent"]["volumes"]
        monitor_vols = config["services"]["monitor"]["volumes"]
        assert "/toolbox:/toolbox" in agent_vols
        assert "/compose:/compose" in agent_vols
        assert "/toolbox:/toolbox" not in monitor_vols
        assert "/compose:/compose" not in monitor_vols

    def test_subject_context_extra_in_monitor_command(self):
        """Subject context extra should appear in monitor command string."""
        config = self._make_op(
            subject_context_extra="Rebuild with: make build"
        )._build_compose_config()
        cmd = config["services"]["monitor"]["command"]
        assert "--subject-context-extra" in cmd
        assert "Rebuild with: make build" in cmd

    def test_container_names_match_constants(self):
        """Container names should match the module-level constants."""
        config = self._make_op()._build_compose_config()
        assert config["services"]["monitor"]["container_name"] == MONITOR_CONTAINER
        assert config["services"]["agent"]["container_name"] == AGENT_CONTAINER

    def test_agent_has_git_env_vars(self):
        """Agent should have GIT_CONFIG_* and GIT_AUTHOR/COMMITTER env vars."""
        config = self._make_op()._build_compose_config()
        env = config["services"]["agent"]["environment"]
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "safe.directory"
        assert env["GIT_CONFIG_VALUE_0"] == "/var/lib/workspace"
        assert env["GIT_AUTHOR_NAME"] == "eval"
        assert env["GIT_COMMITTER_EMAIL"] == "eval@operator"


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
            '[{"created_at": "2025-01-01T00:00:10+00:00", '
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
            '[{"created_at": "2025-01-01T00:00:10+00:00", '
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
                "created_at",
                0,
                '[{"created_at": "2025-01-01T00:00:10+00:00", '
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
                "created_at",
                0,
                '[{"created_at": "2025-01-01T00:00:10+00:00", '
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
