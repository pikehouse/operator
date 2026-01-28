"""Tests for DockerActionExecutor lifecycle operations."""

import pytest
from unittest.mock import MagicMock, patch

from operator_core.docker.actions import DockerActionExecutor
from python_on_whales.exceptions import NoSuchContainer


@pytest.mark.asyncio
async def test_start_container_success():
    """Test starting a stopped container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        # Mock container in stopped state initially
        mock_container_stopped = MagicMock()
        mock_container_stopped.id = "abc123"
        mock_container_stopped.name = "test-container"
        mock_container_stopped.state.status = "exited"
        mock_container_stopped.state.running = False

        # Mock container in running state after start
        mock_container_running = MagicMock()
        mock_container_running.id = "abc123"
        mock_container_running.name = "test-container"
        mock_container_running.state.status = "running"
        mock_container_running.state.running = True

        # First inspect returns stopped, second returns running
        mock_docker.container.inspect.side_effect = [
            mock_container_stopped,
            mock_container_running,
        ]

        executor = DockerActionExecutor()
        result = await executor.start_container("test-container")

        assert result["container_id"] == "abc123"
        assert result["name"] == "test-container"
        assert result["state"] == "running"
        assert result["running"] is True
        mock_docker.container.start.assert_called_once_with("test-container")


@pytest.mark.asyncio
async def test_start_container_already_running():
    """Test starting an already running container (idempotent)."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "test-container"
        mock_container.state.status = "running"
        mock_container.state.running = True

        mock_docker.container.inspect.return_value = mock_container

        executor = DockerActionExecutor()
        result = await executor.start_container("test-container")

        assert result["container_id"] == "abc123"
        assert result["running"] is True
        # Should not call start since already running
        mock_docker.container.start.assert_not_called()


@pytest.mark.asyncio
async def test_start_container_not_found():
    """Test starting a non-existent container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.inspect.side_effect = NoSuchContainer(
            "test-container", "container"
        )

        executor = DockerActionExecutor()
        with pytest.raises(NoSuchContainer):
            await executor.start_container("test-container")


@pytest.mark.asyncio
async def test_stop_container_success():
    """Test stopping a running container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        # Mock container in running state initially
        mock_container_running = MagicMock()
        mock_container_running.id = "abc123"
        mock_container_running.name = "test-container"
        mock_container_running.state.status = "running"
        mock_container_running.state.running = True

        # Mock container in stopped state after stop
        mock_container_stopped = MagicMock()
        mock_container_stopped.id = "abc123"
        mock_container_stopped.name = "test-container"
        mock_container_stopped.state.status = "exited"
        mock_container_stopped.state.running = False
        mock_container_stopped.state.exit_code = 0

        # First inspect returns running, second returns stopped
        mock_docker.container.inspect.side_effect = [
            mock_container_running,
            mock_container_stopped,
        ]

        executor = DockerActionExecutor()
        result = await executor.stop_container("test-container", timeout=10)

        assert result["container_id"] == "abc123"
        assert result["name"] == "test-container"
        assert result["state"] == "exited"
        assert result["exit_code"] == 0
        assert result["graceful_shutdown"] is False
        assert result["killed"] is False
        mock_docker.container.stop.assert_called_once_with("test-container", time=10)


@pytest.mark.asyncio
async def test_stop_container_already_stopped():
    """Test stopping an already stopped container (idempotent)."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "test-container"
        mock_container.state.status = "exited"
        mock_container.state.running = False
        mock_container.state.exit_code = 0

        mock_docker.container.inspect.return_value = mock_container

        executor = DockerActionExecutor()
        result = await executor.stop_container("test-container")

        assert result["container_id"] == "abc123"
        assert result["state"] == "exited"
        # Should not call stop since already stopped
        mock_docker.container.stop.assert_not_called()


@pytest.mark.asyncio
async def test_stop_container_graceful_exit():
    """Test graceful shutdown detection (exit code 143)."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        # Mock container in running state initially
        mock_container_running = MagicMock()
        mock_container_running.state.running = True

        # Mock container stopped with graceful exit code
        mock_container_stopped = MagicMock()
        mock_container_stopped.id = "abc123"
        mock_container_stopped.name = "test-container"
        mock_container_stopped.state.status = "exited"
        mock_container_stopped.state.running = False
        mock_container_stopped.state.exit_code = 143

        mock_docker.container.inspect.side_effect = [
            mock_container_running,
            mock_container_stopped,
        ]

        executor = DockerActionExecutor()
        result = await executor.stop_container("test-container")

        assert result["exit_code"] == 143
        assert result["graceful_shutdown"] is True
        assert result["killed"] is False


@pytest.mark.asyncio
async def test_stop_container_killed_exit():
    """Test force killed detection (exit code 137)."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        # Mock container in running state initially
        mock_container_running = MagicMock()
        mock_container_running.state.running = True

        # Mock container stopped with killed exit code
        mock_container_stopped = MagicMock()
        mock_container_stopped.id = "abc123"
        mock_container_stopped.name = "test-container"
        mock_container_stopped.state.status = "exited"
        mock_container_stopped.state.running = False
        mock_container_stopped.state.exit_code = 137

        mock_docker.container.inspect.side_effect = [
            mock_container_running,
            mock_container_stopped,
        ]

        executor = DockerActionExecutor()
        result = await executor.stop_container("test-container")

        assert result["exit_code"] == 137
        assert result["graceful_shutdown"] is False
        assert result["killed"] is True


@pytest.mark.asyncio
async def test_restart_container_success():
    """Test restarting a container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "test-container"
        mock_container.state.status = "running"
        mock_container.state.running = True

        mock_docker.container.inspect.return_value = mock_container

        executor = DockerActionExecutor()
        result = await executor.restart_container("test-container", timeout=10)

        assert result["container_id"] == "abc123"
        assert result["name"] == "test-container"
        assert result["state"] == "running"
        assert result["running"] is True
        mock_docker.container.restart.assert_called_once_with("test-container", time=10)


@pytest.mark.asyncio
async def test_inspect_container_success():
    """Test inspecting a container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        from datetime import datetime, timezone

        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "test-container"
        mock_container.config.image = "nginx:latest"
        mock_container.state.status = "running"
        mock_container.state.running = True
        mock_container.state.paused = False
        mock_container.state.exit_code = 0
        mock_container.state.started_at = datetime(2026, 1, 28, 12, 0, 0, tzinfo=timezone.utc)
        mock_container.network_settings.networks = {"bridge": MagicMock()}

        mock_docker.container.inspect.return_value = mock_container

        executor = DockerActionExecutor()
        result = await executor.inspect_container("test-container")

        assert result["id"] == "abc123"
        assert result["name"] == "test-container"
        assert result["image"] == "nginx:latest"
        assert result["state"]["status"] == "running"
        assert result["state"]["running"] is True
        assert result["state"]["paused"] is False
        assert result["state"]["exit_code"] == 0
        assert result["state"]["started_at"] == "2026-01-28T12:00:00+00:00"
        assert result["networks"] == ["bridge"]


@pytest.mark.asyncio
async def test_inspect_container_not_found():
    """Test inspecting a non-existent container."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.inspect.side_effect = NoSuchContainer(
            "test-container", "container"
        )

        executor = DockerActionExecutor()
        with pytest.raises(NoSuchContainer):
            await executor.inspect_container("test-container")


@pytest.mark.asyncio
async def test_inspect_container_no_started_at():
    """Test inspecting a container with no started_at timestamp."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "test-container"
        mock_container.config.image = "nginx:latest"
        mock_container.state.status = "created"
        mock_container.state.running = False
        mock_container.state.paused = False
        mock_container.state.exit_code = 0
        mock_container.state.started_at = None
        mock_container.network_settings.networks = {}

        mock_docker.container.inspect.return_value = mock_container

        executor = DockerActionExecutor()
        result = await executor.inspect_container("test-container")

        assert result["state"]["started_at"] is None
        assert result["networks"] == []


# ===== Logs Tests =====


@pytest.mark.asyncio
async def test_get_logs_default_tail():
    """Test getting logs with default tail limit."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.logs.return_value = "line1\nline2\nline3"

        executor = DockerActionExecutor()
        result = await executor.get_container_logs("test-container")

        assert result["container_id"] == "test-container"
        assert result["logs"] == "line1\nline2\nline3"
        assert result["line_count"] == 3
        assert result["tail_limit"] == 100
        assert result["truncated"] is False
        mock_docker.container.logs.assert_called_once_with(
            "test-container",
            tail=100,
            since=None,
            timestamps=True,
            follow=False,
        )


@pytest.mark.asyncio
async def test_get_logs_custom_tail():
    """Test getting logs with custom tail limit."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.logs.return_value = "line1\nline2"

        executor = DockerActionExecutor()
        result = await executor.get_container_logs("test-container", tail=500)

        assert result["tail_limit"] == 500
        assert result["truncated"] is False
        mock_docker.container.logs.assert_called_once_with(
            "test-container",
            tail=500,
            since=None,
            timestamps=True,
            follow=False,
        )


@pytest.mark.asyncio
async def test_get_logs_max_tail_enforced():
    """Test that tail limit is capped at MAX_TAIL (10000)."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.logs.return_value = "log data"

        executor = DockerActionExecutor()
        result = await executor.get_container_logs("test-container", tail=20000)

        # Should be capped at 10000
        assert result["tail_limit"] == 10000
        assert result["truncated"] is True
        mock_docker.container.logs.assert_called_once_with(
            "test-container",
            tail=10000,
            since=None,
            timestamps=True,
            follow=False,
        )


@pytest.mark.asyncio
async def test_get_logs_with_since():
    """Test getting logs with since parameter."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.logs.return_value = "recent log"

        executor = DockerActionExecutor()
        result = await executor.get_container_logs(
            "test-container",
            since="2026-01-28T00:00:00Z"
        )

        assert result["logs"] == "recent log"
        mock_docker.container.logs.assert_called_once_with(
            "test-container",
            tail=100,
            since="2026-01-28T00:00:00Z",
            timestamps=True,
            follow=False,
        )


@pytest.mark.asyncio
async def test_get_logs_empty_container():
    """Test getting logs from container with no logs."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.logs.return_value = ""

        executor = DockerActionExecutor()
        result = await executor.get_container_logs("test-container")

        assert result["logs"] == ""
        assert result["line_count"] == 0


# ===== Network Tests =====


@pytest.mark.asyncio
async def test_connect_to_network_success():
    """Test connecting container to network."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_docker.container.inspect.return_value = mock_container
        mock_docker.network.exists.return_value = True

        executor = DockerActionExecutor()
        result = await executor.connect_container_to_network(
            "test-container",
            "test-network",
            alias="web"
        )

        assert result["container_id"] == "test-container"
        assert result["network"] == "test-network"
        assert result["alias"] == "web"
        assert result["connected"] is True
        mock_docker.network.connect.assert_called_once_with(
            "test-network",
            "test-container",
            alias="web",
        )


@pytest.mark.asyncio
async def test_connect_network_not_found():
    """Test connecting to non-existent network."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_container = MagicMock()
        mock_docker.container.inspect.return_value = mock_container
        mock_docker.network.exists.return_value = False

        executor = DockerActionExecutor()
        with pytest.raises(ValueError, match="Network 'test-network' not found"):
            await executor.connect_container_to_network(
                "test-container",
                "test-network"
            )


@pytest.mark.asyncio
async def test_connect_container_not_found():
    """Test connecting non-existent container to network."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.inspect.side_effect = NoSuchContainer(
            "test-container", "container"
        )

        executor = DockerActionExecutor()
        with pytest.raises(NoSuchContainer):
            await executor.connect_container_to_network(
                "test-container",
                "test-network"
            )


@pytest.mark.asyncio
async def test_disconnect_from_network_success():
    """Test disconnecting container from network."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        executor = DockerActionExecutor()
        result = await executor.disconnect_container_from_network(
            "test-container",
            "test-network"
        )

        assert result["container_id"] == "test-container"
        assert result["network"] == "test-network"
        assert result["disconnected"] is True
        mock_docker.network.disconnect.assert_called_once_with(
            "test-network",
            "test-container",
            force=False,
        )


@pytest.mark.asyncio
async def test_disconnect_with_force():
    """Test disconnecting with force flag."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        executor = DockerActionExecutor()
        result = await executor.disconnect_container_from_network(
            "test-container",
            "test-network",
            force=True
        )

        assert result["disconnected"] is True
        mock_docker.network.disconnect.assert_called_once_with(
            "test-network",
            "test-container",
            force=True,
        )


# ===== Exec Tests =====


@pytest.mark.asyncio
async def test_execute_command_success():
    """Test executing command successfully."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.execute.return_value = "command output"

        executor = DockerActionExecutor()
        result = await executor.execute_command(
            "test-container",
            ["echo", "hello"]
        )

        assert result["container_id"] == "test-container"
        assert result["command"] == ["echo", "hello"]
        assert result["success"] is True
        assert result["output"] == "command output"
        assert result["error"] is None
        mock_docker.container.execute.assert_called_once_with(
            "test-container",
            ["echo", "hello"],
            user=None,
            workdir=None,
            tty=False,
            interactive=False,
        )


@pytest.mark.asyncio
async def test_execute_command_failure():
    """Test executing command with error."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.execute.side_effect = Exception("Command failed")

        executor = DockerActionExecutor()
        result = await executor.execute_command(
            "test-container",
            ["false"]
        )

        assert result["container_id"] == "test-container"
        assert result["command"] == ["false"]
        assert result["success"] is False
        assert result["output"] == ""
        assert result["error"] == "Command failed"


@pytest.mark.asyncio
async def test_execute_command_with_user():
    """Test executing command with specific user."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.execute.return_value = "output"

        executor = DockerActionExecutor()
        result = await executor.execute_command(
            "test-container",
            ["whoami"],
            user="nobody"
        )

        assert result["success"] is True
        mock_docker.container.execute.assert_called_once_with(
            "test-container",
            ["whoami"],
            user="nobody",
            workdir=None,
            tty=False,
            interactive=False,
        )


@pytest.mark.asyncio
async def test_execute_command_with_workdir():
    """Test executing command with specific working directory."""
    with patch("operator_core.docker.actions.docker") as mock_docker:
        mock_docker.container.execute.return_value = "output"

        executor = DockerActionExecutor()
        result = await executor.execute_command(
            "test-container",
            ["pwd"],
            workdir="/app"
        )

        assert result["success"] is True
        mock_docker.container.execute.assert_called_once_with(
            "test-container",
            ["pwd"],
            user=None,
            workdir="/app",
            tty=False,
            interactive=False,
        )
