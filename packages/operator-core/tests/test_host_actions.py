"""Tests for HostActionExecutor service/process operations and validation."""

import asyncio
import os
import signal
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from operator_core.host.validation import ServiceWhitelist, validate_pid
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


# ===== PID Validation Tests =====


class TestPidValidation:
    """Tests for validate_pid function."""

    def test_pid_1_rejected(self):
        """PID 1 (init process) should be rejected with clear error."""
        with pytest.raises(ValueError, match="init process"):
            validate_pid(1)

    def test_pid_0_rejected(self):
        """PID 0 should be rejected."""
        with pytest.raises(ValueError, match="PID 0"):
            validate_pid(0)

    def test_negative_pid_rejected(self):
        """Negative PIDs should be rejected."""
        with pytest.raises(ValueError, match="PID -1"):
            validate_pid(-1)

        with pytest.raises(ValueError, match="PID -100"):
            validate_pid(-100)

    def test_kernel_thread_pid_rejected(self):
        """PIDs < 300 (likely kernel threads) should be rejected."""
        with pytest.raises(ValueError, match="kernel thread"):
            validate_pid(2)

        with pytest.raises(ValueError, match="kernel thread"):
            validate_pid(100)

        with pytest.raises(ValueError, match="kernel thread"):
            validate_pid(299)

    def test_valid_pid_accepted(self):
        """Valid PIDs >= 300 should be accepted (if process exists)."""
        with patch("operator_core.host.validation.os.kill") as mock_kill:
            # Mock os.kill to succeed (process exists and we have permission)
            mock_kill.return_value = None

            # Should not raise for valid PID
            validate_pid(300)
            validate_pid(1000)
            validate_pid(65535)

            # Verify os.kill was called with signal 0
            assert mock_kill.call_count == 3
            mock_kill.assert_any_call(300, 0)
            mock_kill.assert_any_call(1000, 0)
            mock_kill.assert_any_call(65535, 0)

    def test_nonexistent_pid_raises(self):
        """ProcessLookupError should be raised for non-existent PIDs."""
        with patch("operator_core.host.validation.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError("No such process")

            with pytest.raises(ProcessLookupError):
                validate_pid(99999)

    def test_permission_denied_raises(self):
        """PermissionError should be raised when no permission to signal."""
        with patch("operator_core.host.validation.os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError("Operation not permitted")

            with pytest.raises(PermissionError):
                validate_pid(500)

    def test_non_integer_pid_rejected(self):
        """Non-integer PIDs should be rejected."""
        with pytest.raises(ValueError, match="must be integer"):
            validate_pid("1000")  # type: ignore

        with pytest.raises(ValueError, match="must be integer"):
            validate_pid(1000.5)  # type: ignore

        with pytest.raises(ValueError, match="must be integer"):
            validate_pid(None)  # type: ignore


# ===== Host Kill Process Tests =====


class TestHostKillProcess:
    """Tests for HostActionExecutor.kill_process method."""

    @pytest.mark.asyncio
    async def test_kill_sends_sigterm_by_default(self):
        """kill_process should send SIGTERM by default."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Mock process exits immediately after SIGTERM
            mock_kill.side_effect = [
                None,  # First call sends SIGTERM
                ProcessLookupError(),  # Second call (check if exists) - process exited
                ProcessLookupError(),  # Final state check - process gone
            ]

            executor = HostActionExecutor()
            result = await executor.kill_process(1234)

            # Verify SIGTERM was sent (first os.kill call)
            mock_kill.assert_any_call(1234, signal.SIGTERM)

            # Verify result
            assert result["pid"] == 1234
            assert result["signal"] == "SIGTERM"
            assert result["escalated"] is False
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_kill_sends_sigkill_when_specified(self):
        """kill_process should send SIGKILL when signal_type='SIGKILL'."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill:

            # Mock process gone after SIGKILL
            mock_kill.side_effect = [
                None,  # Send SIGKILL
                ProcessLookupError(),  # Final state check - process gone
            ]

            executor = HostActionExecutor()
            result = await executor.kill_process(1234, signal_type="SIGKILL")

            # Verify SIGKILL was sent
            mock_kill.assert_any_call(1234, signal.SIGKILL)

            assert result["signal"] == "SIGKILL"
            assert result["escalated"] is False  # No escalation for direct SIGKILL
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_graceful_escalation(self):
        """If process doesn't die after SIGTERM, SIGKILL should be sent."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Process stays running during graceful timeout, then dies after SIGKILL
            call_count = [0]

            def kill_side_effect(pid, sig):
                call_count[0] += 1
                if sig == signal.SIGTERM:
                    return None  # SIGTERM sent
                elif sig == 0:
                    # Process still running during timeout
                    return None
                elif sig == signal.SIGKILL:
                    return None  # SIGKILL sent
                return None

            # Process exists during all timeout checks, then gone after SIGKILL
            mock_kill.side_effect = [
                None,  # SIGTERM sent
                *([None] * 50),  # Process still exists for 50 checks (5 seconds at 100ms each)
                None,  # SIGKILL sent
                ProcessLookupError(),  # Final check - process gone
            ]

            executor = HostActionExecutor()
            result = await executor.kill_process(1234, graceful_timeout=5)

            assert result["escalated"] is True
            assert result["success"] is True
            assert result["signal"] == "SIGTERM"  # Original signal

    @pytest.mark.asyncio
    async def test_graceful_exit_no_escalation(self):
        """Process dying before timeout should not trigger escalation."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Process exits after first existence check
            mock_kill.side_effect = [
                None,  # SIGTERM sent
                ProcessLookupError(),  # First existence check - process gone
                ProcessLookupError(),  # Final state check
            ]

            executor = HostActionExecutor()
            result = await executor.kill_process(1234)

            assert result["escalated"] is False
            assert result["success"] is True
            assert result["still_running"] is False

    @pytest.mark.asyncio
    async def test_pid_validation_integrated(self):
        """PID 1 should raise ValueError (integration with validate_pid)."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="init process"):
            await executor.kill_process(1)

    @pytest.mark.asyncio
    async def test_kernel_thread_pid_rejected(self):
        """Kernel thread PIDs should raise ValueError."""
        executor = HostActionExecutor()

        with pytest.raises(ValueError, match="kernel thread"):
            await executor.kill_process(100)

    @pytest.mark.asyncio
    async def test_return_structure(self):
        """Result should have all expected fields."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill:

            mock_kill.side_effect = [None, ProcessLookupError()]

            executor = HostActionExecutor()
            result = await executor.kill_process(1234, signal_type="SIGKILL")

            # Verify all expected fields
            assert "pid" in result
            assert "signal" in result
            assert "escalated" in result
            assert "still_running" in result
            assert "success" in result

            # Verify types
            assert isinstance(result["pid"], int)
            assert isinstance(result["signal"], str)
            assert isinstance(result["escalated"], bool)
            assert isinstance(result["still_running"], bool)
            assert isinstance(result["success"], bool)

    @pytest.mark.asyncio
    async def test_custom_graceful_timeout(self):
        """graceful_timeout parameter should be respected."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Process exits immediately
            mock_kill.side_effect = [None, ProcessLookupError(), ProcessLookupError()]

            executor = HostActionExecutor()

            # Test with different timeout (should complete quickly since process exits immediately)
            result = await executor.kill_process(1234, graceful_timeout=10)

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_process_not_found_raises(self):
        """ProcessLookupError should be raised if process doesn't exist."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate:
            mock_validate.side_effect = ProcessLookupError("No such process")

            executor = HostActionExecutor()

            with pytest.raises(ProcessLookupError):
                await executor.kill_process(99999)

    @pytest.mark.asyncio
    async def test_permission_denied_raises(self):
        """PermissionError should be raised if no permission to signal."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate:
            mock_validate.side_effect = PermissionError("Operation not permitted")

            executor = HostActionExecutor()

            with pytest.raises(PermissionError):
                await executor.kill_process(500)

    @pytest.mark.asyncio
    async def test_still_running_after_sigkill(self):
        """Handle edge case where process survives SIGKILL (zombie, etc.)."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Process never dies (stuck/zombie)
            mock_kill.return_value = None  # All signals "succeed" but process stays

            executor = HostActionExecutor()
            result = await executor.kill_process(1234, graceful_timeout=1)

            # Process still running
            assert result["still_running"] is True
            assert result["success"] is False
            assert result["escalated"] is True

    @pytest.mark.asyncio
    async def test_zero_graceful_timeout(self):
        """graceful_timeout=0 should skip waiting and not escalate."""
        with patch("operator_core.host.actions.validate_pid") as mock_validate, \
             patch("operator_core.host.actions.os.kill") as mock_kill, \
             patch("operator_core.host.actions.asyncio.sleep") as mock_sleep:

            # Process still running after SIGTERM
            mock_kill.return_value = None

            executor = HostActionExecutor()
            result = await executor.kill_process(1234, graceful_timeout=0)

            # With timeout=0, no waiting occurs, no escalation
            assert result["escalated"] is False
            # sleep should not have been called for timeout loop
            # (though it might be called for SIGKILL wait if that happened)

    def test_executor_has_kill_process_method(self):
        """HostActionExecutor should have kill_process method."""
        executor = HostActionExecutor()

        assert hasattr(executor, "kill_process")
        assert asyncio.iscoroutinefunction(executor.kill_process)


# ===== Host Action Integration Tests =====


class TestHostActionIntegration:
    """Integration tests for host action tool registration."""

    def test_host_tools_in_general_tools(self):
        """Host tools included in get_general_tools()."""
        from operator_core.actions.tools import get_general_tools

        tools = get_general_tools()
        tool_names = [t.name for t in tools]

        assert "host_service_start" in tool_names
        assert "host_service_stop" in tool_names
        assert "host_service_restart" in tool_names
        assert "host_kill_process" in tool_names

    def test_host_tools_have_action_type_tool(self):
        """All host tools have ActionType.TOOL."""
        from operator_core.host.actions import get_host_tools
        from operator_core.actions.types import ActionType

        for tool in get_host_tools():
            assert tool.action_type == ActionType.TOOL

    def test_host_tools_in_executors(self):
        """All host tools have executors registered."""
        from operator_core.actions.tools import TOOL_EXECUTORS

        assert "host_service_start" in TOOL_EXECUTORS
        assert "host_service_stop" in TOOL_EXECUTORS
        assert "host_service_restart" in TOOL_EXECUTORS
        assert "host_kill_process" in TOOL_EXECUTORS

    def test_host_tool_risk_levels(self):
        """Host tools have correct risk levels."""
        from operator_core.host.actions import get_host_tools

        tools = {t.name: t for t in get_host_tools()}

        # Service ops: start and restart are medium (recoverable)
        assert tools["host_service_start"].risk_level == "medium"
        assert tools["host_service_restart"].risk_level == "medium"

        # High risk: stop service and kill process (availability impact)
        assert tools["host_service_stop"].risk_level == "high"
        assert tools["host_kill_process"].risk_level == "high"

    def test_host_tools_require_approval(self):
        """All host tools require approval."""
        from operator_core.host.actions import get_host_tools

        for tool in get_host_tools():
            assert tool.requires_approval is True

    @pytest.mark.asyncio
    async def test_execute_tool_dispatches_to_host_executor(self):
        """execute_tool routes host actions to HostActionExecutor."""
        from operator_core.actions.tools import execute_tool

        # Calling with invalid service should raise ValueError (from whitelist)
        with pytest.raises(ValueError, match="not in whitelist"):
            await execute_tool("host_service_start", {"service_name": "nonexistent_service"})

    def test_lazy_host_executor_initialization(self):
        """Host executor is lazily initialized to avoid circular imports."""
        from operator_core.actions.tools import _get_host_executor

        executor = _get_host_executor()
        assert executor is not None

        # Second call returns same instance
        executor2 = _get_host_executor()
        assert executor is executor2

    def test_total_tool_count(self):
        """Verify total tool count after host integration."""
        from operator_core.actions.tools import get_general_tools

        tools = get_general_tools()
        # 2 base (wait, log_message) + 8 Docker + 4 Host = 14
        assert len(tools) == 14

    def test_host_tools_have_parameters(self):
        """All host tools have properly defined parameters."""
        from operator_core.host.actions import get_host_tools

        for tool in get_host_tools():
            assert tool.parameters is not None
            assert len(tool.parameters) > 0

            # Service tools have service_name parameter
            if tool.name.startswith("host_service_"):
                assert "service_name" in tool.parameters
                assert tool.parameters["service_name"].required is True

            # Kill process has pid parameter
            if tool.name == "host_kill_process":
                assert "pid" in tool.parameters
                assert tool.parameters["pid"].required is True
                assert "signal" in tool.parameters
                assert tool.parameters["signal"].required is False
                assert "graceful_timeout" in tool.parameters
                assert tool.parameters["graceful_timeout"].required is False

    def test_host_tools_have_descriptions(self):
        """All host tools have meaningful descriptions."""
        from operator_core.host.actions import get_host_tools

        for tool in get_host_tools():
            assert tool.description is not None
            assert len(tool.description) > 10  # Meaningful description, not empty

    def test_get_host_tools_returns_list(self):
        """get_host_tools returns a list of ActionDefinitions."""
        from operator_core.host.actions import get_host_tools
        from operator_core.actions.registry import ActionDefinition

        tools = get_host_tools()

        assert isinstance(tools, list)
        assert len(tools) == 4
        for tool in tools:
            assert isinstance(tool, ActionDefinition)
