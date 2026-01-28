"""Tests for HostActionExecutor service operations and ServiceWhitelist validation."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from operator_core.host.validation import ServiceWhitelist
from operator_core.host.actions import HostActionExecutor


# ===== ServiceWhitelist Tests =====


class TestServiceWhitelist:
    """Tests for ServiceWhitelist validation class."""

    def test_default_whitelist_allows_common_services(self):
        """Common services should be allowed in default whitelist."""
        whitelist = ServiceWhitelist()

        # All default services should be allowed
        assert whitelist.is_allowed("nginx") is True
        assert whitelist.is_allowed("redis-server") is True
        assert whitelist.is_allowed("postgresql") is True
        assert whitelist.is_allowed("mysql") is True
        assert whitelist.is_allowed("docker") is True
        assert whitelist.is_allowed("tikv") is True
        assert whitelist.is_allowed("pd") is True
        assert whitelist.is_allowed("ratelimiter") is True

    def test_forbidden_services_always_blocked(self):
        """Forbidden services should be blocked even if in whitelist."""
        # Create whitelist that explicitly includes forbidden services
        whitelist = ServiceWhitelist(whitelist={
            "nginx",
            "systemd",  # Forbidden
            "ssh",      # Forbidden
            "dbus",     # Forbidden
        })

        # Forbidden services should be blocked even if manually added
        assert whitelist.is_allowed("systemd") is False
        assert whitelist.is_allowed("ssh") is False
        assert whitelist.is_allowed("sshd") is False
        assert whitelist.is_allowed("dbus") is False
        assert whitelist.is_allowed("networking") is False
        assert whitelist.is_allowed("network-manager") is False
        assert whitelist.is_allowed("systemd-resolved") is False
        assert whitelist.is_allowed("systemd-networkd") is False
        assert whitelist.is_allowed("init") is False

        # But nginx is still allowed
        assert whitelist.is_allowed("nginx") is True

    def test_custom_whitelist(self):
        """Custom whitelist should only allow specified services."""
        whitelist = ServiceWhitelist(whitelist={"custom-service", "another-service"})

        assert whitelist.is_allowed("custom-service") is True
        assert whitelist.is_allowed("another-service") is True
        assert whitelist.is_allowed("nginx") is False  # Not in custom whitelist
        assert whitelist.is_allowed("redis-server") is False

    def test_add_service_to_whitelist(self):
        """Runtime addition of services should work."""
        whitelist = ServiceWhitelist(whitelist={"nginx"})

        assert whitelist.is_allowed("custom-app") is False

        whitelist.add_service("custom-app")

        assert whitelist.is_allowed("custom-app") is True

    def test_add_forbidden_service_raises(self):
        """Adding forbidden services should raise ValueError."""
        whitelist = ServiceWhitelist()

        with pytest.raises(ValueError, match="Cannot whitelist forbidden service"):
            whitelist.add_service("systemd")

        with pytest.raises(ValueError, match="Cannot whitelist forbidden service"):
            whitelist.add_service("ssh")

        with pytest.raises(ValueError, match="Cannot whitelist forbidden service"):
            whitelist.add_service("dbus")

        with pytest.raises(ValueError, match="Cannot whitelist forbidden service"):
            whitelist.add_service("init")

    def test_path_traversal_blocked(self):
        """Path traversal attempts in service names should be blocked."""
        whitelist = ServiceWhitelist()

        with pytest.raises(ValueError, match="contains path separator"):
            whitelist.validate_service_name("../etc/passwd")

        with pytest.raises(ValueError, match="contains path separator"):
            whitelist.validate_service_name("nginx/../../ssh")

        with pytest.raises(ValueError, match="contains path separator"):
            whitelist.validate_service_name("/etc/passwd")

        with pytest.raises(ValueError, match="contains path traversal"):
            whitelist.validate_service_name("nginx..secret")

    def test_empty_whitelist(self):
        """Empty whitelist should block all non-default services."""
        whitelist = ServiceWhitelist(whitelist=set())

        assert whitelist.is_allowed("nginx") is False
        assert whitelist.is_allowed("any-service") is False

    def test_service_not_in_whitelist(self):
        """Services not in whitelist should be blocked."""
        whitelist = ServiceWhitelist()

        assert whitelist.is_allowed("random-service") is False
        assert whitelist.is_allowed("unknown") is False
        assert whitelist.is_allowed("malicious-service") is False


# ===== HostActionExecutor Tests =====


class TestHostActionExecutor:
    """Tests for HostActionExecutor service methods."""

    @pytest.mark.asyncio
    async def test_start_service_success(self):
        """Test starting a whitelisted service successfully."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful start
            mock_start_proc = AsyncMock()
            mock_start_proc.returncode = 0
            mock_start_proc.communicate = AsyncMock(return_value=(b"", b""))

            # Mock is-active check returning "active"
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"active\n", b""))

            mock_exec.side_effect = [mock_start_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.start_service("nginx")

            assert result["service_name"] == "nginx"
            assert result["command"] == "start"
            assert result["returncode"] == 0
            assert result["active"] is True
            assert result["success"] is True

            # Verify systemctl start was called with array args
            mock_exec.assert_any_call(
                "systemctl",
                "start",
                "nginx",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_start_service_not_in_whitelist(self):
        """Test starting a service not in whitelist raises ValueError."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="not in whitelist"):
            await executor.start_service("random-service")

    @pytest.mark.asyncio
    async def test_start_service_forbidden(self):
        """Test starting a forbidden service raises ValueError."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="not in whitelist"):
            await executor.start_service("systemd")

        with pytest.raises(ValueError, match="not in whitelist"):
            await executor.start_service("ssh")

    @pytest.mark.asyncio
    async def test_stop_service_success(self):
        """Test stopping a whitelisted service successfully."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful stop
            mock_stop_proc = AsyncMock()
            mock_stop_proc.returncode = 0
            mock_stop_proc.communicate = AsyncMock(return_value=(b"", b""))

            # Mock is-active check returning "inactive"
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"inactive\n", b""))

            mock_exec.side_effect = [mock_stop_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.stop_service("nginx")

            assert result["service_name"] == "nginx"
            assert result["command"] == "stop"
            assert result["returncode"] == 0
            assert result["active"] is False
            assert result["success"] is True

            # Verify systemctl stop was called
            mock_exec.assert_any_call(
                "systemctl",
                "stop",
                "nginx",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_restart_service_success(self):
        """Test restarting a whitelisted service successfully."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock successful restart
            mock_restart_proc = AsyncMock()
            mock_restart_proc.returncode = 0
            mock_restart_proc.communicate = AsyncMock(return_value=(b"", b""))

            # Mock is-active check returning "active"
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"active\n", b""))

            mock_exec.side_effect = [mock_restart_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.restart_service("nginx")

            assert result["service_name"] == "nginx"
            assert result["command"] == "restart"
            assert result["returncode"] == 0
            assert result["active"] is True
            assert result["success"] is True

            # Verify systemctl restart was called
            mock_exec.assert_any_call(
                "systemctl",
                "restart",
                "nginx",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_uses_create_subprocess_exec(self):
        """Verify asyncio.create_subprocess_exec is used (not subprocess.run with shell=True)."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"active\n", b""))
            mock_exec.return_value = mock_proc

            executor = HostActionExecutor()
            await executor.start_service("nginx")

            # Verify create_subprocess_exec was called (not shell-based execution)
            assert mock_exec.called
            # All calls should use array arguments
            for call in mock_exec.call_args_list:
                args = call[0]
                # First arg should be command, subsequent args are command parts
                assert args[0] == "systemctl"
                assert isinstance(args[1], str)  # Subcommand
                assert isinstance(args[2], str)  # Service name

    @pytest.mark.asyncio
    async def test_command_injection_prevented(self):
        """Service name with shell metacharacters should be passed literally (no shell parsing)."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1  # Will fail, but that's expected
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Failed"))
            mock_exec.return_value = mock_proc

            # Create executor with malicious service in whitelist (for testing purposes only)
            executor = HostActionExecutor(service_whitelist={"nginx; rm -rf /"})

            # This should fail validation due to path separator
            with pytest.raises(ValueError, match="contains path separator"):
                await executor.start_service("nginx; rm -rf /")

    @pytest.mark.asyncio
    async def test_stop_service_not_in_whitelist(self):
        """Test stopping a service not in whitelist raises ValueError."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="not in whitelist"):
            await executor.stop_service("unknown-service")

    @pytest.mark.asyncio
    async def test_restart_service_not_in_whitelist(self):
        """Test restarting a service not in whitelist raises ValueError."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="not in whitelist"):
            await executor.restart_service("unknown-service")

    @pytest.mark.asyncio
    async def test_start_service_fails_when_not_active(self):
        """Test start_service returns success=False when service doesn't become active."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock systemctl start succeeds but service still not active
            mock_start_proc = AsyncMock()
            mock_start_proc.returncode = 0
            mock_start_proc.communicate = AsyncMock(return_value=(b"", b""))

            # Mock is-active check returning "failed"
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"failed\n", b""))

            mock_exec.side_effect = [mock_start_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.start_service("nginx")

            # returncode is 0 but active is False, so success is False
            assert result["returncode"] == 0
            assert result["active"] is False
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_stop_service_fails_when_still_active(self):
        """Test stop_service returns success=False when service doesn't stop."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock systemctl stop succeeds but service still active
            mock_stop_proc = AsyncMock()
            mock_stop_proc.returncode = 0
            mock_stop_proc.communicate = AsyncMock(return_value=(b"", b""))

            # Mock is-active check returning "active" (service didn't stop)
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"active\n", b""))

            mock_exec.side_effect = [mock_stop_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.stop_service("nginx")

            # returncode is 0 but active is True, so success is False
            assert result["returncode"] == 0
            assert result["active"] is True
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_custom_whitelist_executor(self):
        """Test executor with custom whitelist."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"active\n", b""))
            mock_exec.return_value = mock_proc

            # Custom whitelist with only 'custom-app'
            executor = HostActionExecutor(service_whitelist={"custom-app"})

            # custom-app should work
            result = await executor.start_service("custom-app")
            assert result["service_name"] == "custom-app"

            # nginx should fail (not in custom whitelist)
            with pytest.raises(ValueError, match="not in whitelist"):
                await executor.start_service("nginx")

    @pytest.mark.asyncio
    async def test_path_traversal_in_executor(self):
        """Test that path traversal attempts are blocked at executor level."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="contains path separator"):
            await executor.start_service("../etc/passwd")

        with pytest.raises(ValueError, match="contains path traversal"):
            await executor.stop_service("nginx..secret")

        with pytest.raises(ValueError, match="contains path separator"):
            await executor.restart_service("/etc/init.d/nginx")

    @pytest.mark.asyncio
    async def test_check_service_active(self):
        """Test _check_service_active helper method."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Test when service is active
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"active\n", b""))
            mock_exec.return_value = mock_active_proc

            executor = HostActionExecutor()
            is_active = await executor._check_service_active("nginx")
            assert is_active is True

            # Test when service is inactive
            mock_inactive_proc = AsyncMock()
            mock_inactive_proc.communicate = AsyncMock(return_value=(b"inactive\n", b""))
            mock_exec.return_value = mock_inactive_proc

            is_active = await executor._check_service_active("nginx")
            assert is_active is False

            # Test when service is failed
            mock_failed_proc = AsyncMock()
            mock_failed_proc.communicate = AsyncMock(return_value=(b"failed\n", b""))
            mock_exec.return_value = mock_failed_proc

            is_active = await executor._check_service_active("nginx")
            assert is_active is False

    @pytest.mark.asyncio
    async def test_service_error_output(self):
        """Test that stderr is captured in result."""
        with patch("operator_core.host.actions.asyncio.create_subprocess_exec") as mock_exec:
            # Mock failed start with error message
            mock_start_proc = AsyncMock()
            mock_start_proc.returncode = 1
            mock_start_proc.communicate = AsyncMock(
                return_value=(b"", b"Failed to start nginx.service: Unit not found.\n")
            )

            # Mock is-active check
            mock_active_proc = AsyncMock()
            mock_active_proc.communicate = AsyncMock(return_value=(b"inactive\n", b""))

            mock_exec.side_effect = [mock_start_proc, mock_active_proc]

            executor = HostActionExecutor()
            result = await executor.start_service("nginx")

            assert result["returncode"] == 1
            assert result["success"] is False
            assert "Failed to start nginx.service" in result["stderr"]


# ===== Import Tests =====


class TestHostModuleImports:
    """Tests for host module imports."""

    def test_import_from_host_package(self):
        """Test importing from operator_core.host package."""
        from operator_core.host import HostActionExecutor, ServiceWhitelist

        assert HostActionExecutor is not None
        assert ServiceWhitelist is not None

    def test_executor_has_expected_methods(self):
        """Test that HostActionExecutor has all expected methods."""
        executor = HostActionExecutor()

        assert hasattr(executor, "start_service")
        assert hasattr(executor, "stop_service")
        assert hasattr(executor, "restart_service")
        assert hasattr(executor, "_check_service_active")

        # All service methods should be coroutines
        assert asyncio.iscoroutinefunction(executor.start_service)
        assert asyncio.iscoroutinefunction(executor.stop_service)
        assert asyncio.iscoroutinefunction(executor.restart_service)
        assert asyncio.iscoroutinefunction(executor._check_service_active)

    def test_whitelist_has_expected_attributes(self):
        """Test that ServiceWhitelist has expected class attributes."""
        assert hasattr(ServiceWhitelist, "DEFAULT_WHITELIST")
        assert hasattr(ServiceWhitelist, "FORBIDDEN_SERVICES")

        # Verify key services in defaults
        assert "nginx" in ServiceWhitelist.DEFAULT_WHITELIST
        assert "systemd" in ServiceWhitelist.FORBIDDEN_SERVICES
        assert "ssh" in ServiceWhitelist.FORBIDDEN_SERVICES
