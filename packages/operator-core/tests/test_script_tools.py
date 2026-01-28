"""Integration tests for execute_script tool registration.

Tests verify that execute_script is properly registered as an agent-discoverable
tool with correct parameters, risk level, and approval requirements.
"""

from unittest.mock import patch

import pytest

from operator_core.actions.tools import TOOL_EXECUTORS, execute_tool, get_general_tools
from operator_core.actions.types import ActionType
from operator_core.scripts import ExecutionResult, ScriptExecutor


def test_execute_script_discoverable():
    """Test execute_script appears in get_general_tools()."""
    tools = get_general_tools()
    tool_names = [t.name for t in tools]

    assert "execute_script" in tool_names, "execute_script not discoverable"


def test_execute_script_parameters():
    """Test execute_script has correct parameters."""
    tools = get_general_tools()
    execute_script_tool = next((t for t in tools if t.name == "execute_script"), None)

    assert execute_script_tool is not None, "execute_script tool not found"

    # Check required parameters
    params = execute_script_tool.parameters
    assert "script_content" in params, "Missing script_content parameter"
    assert params["script_content"].required, "script_content should be required"

    assert "script_type" in params, "Missing script_type parameter"
    assert params["script_type"].required, "script_type should be required"

    # Check optional parameter
    assert "timeout" in params, "Missing timeout parameter"
    assert not params["timeout"].required, "timeout should be optional"
    assert params["timeout"].default == 60, "timeout default should be 60"


def test_execute_script_risk_and_approval():
    """Test execute_script has high risk level and requires approval."""
    tools = get_general_tools()
    execute_script_tool = next((t for t in tools if t.name == "execute_script"), None)

    assert execute_script_tool is not None, "execute_script tool not found"
    assert (
        execute_script_tool.risk_level == "high"
    ), "execute_script should be high risk"
    assert (
        execute_script_tool.requires_approval is True
    ), "execute_script should require approval"


def test_execute_script_action_type():
    """Test execute_script is registered as TOOL type."""
    tools = get_general_tools()
    execute_script_tool = next((t for t in tools if t.name == "execute_script"), None)

    assert execute_script_tool is not None, "execute_script tool not found"
    assert (
        execute_script_tool.action_type == ActionType.TOOL
    ), "execute_script should be ActionType.TOOL"


def test_execute_script_description():
    """Test execute_script description mentions sandbox and validation."""
    tools = get_general_tools()
    execute_script_tool = next((t for t in tools if t.name == "execute_script"), None)

    assert execute_script_tool is not None, "execute_script tool not found"

    description = execute_script_tool.description.lower()
    assert "sandbox" in description or "isolated" in description, (
        "Description should mention sandbox"
    )
    assert "validation" in description or "checking" in description, (
        "Description should mention validation"
    )


def test_execute_script_in_tool_executors():
    """Test execute_script is mapped in TOOL_EXECUTORS."""
    assert (
        "execute_script" in TOOL_EXECUTORS
    ), "execute_script not in TOOL_EXECUTORS"


@pytest.mark.asyncio
async def test_execute_tool_calls_script_executor():
    """Test execute_tool routes to ScriptExecutor.execute()."""
    # Mock ScriptExecutor.execute to verify it gets called
    with patch.object(
        ScriptExecutor,
        "execute",
        return_value=ExecutionResult(
            success=True,
            stdout="Hello from script",
            stderr="",
            exit_code=0,
        ),
    ) as mock_execute:
        # Call execute_tool with execute_script
        result = await execute_tool(
            "execute_script",
            {
                "script_content": "print('Hello from script')",
                "script_type": "python",
                "timeout": 30,
            },
        )

        # Verify ScriptExecutor.execute was called with correct parameters
        # Lambda wrapper maps script_content -> content
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert call_args[1]["content"] == "print('Hello from script')"
        assert call_args[1]["script_type"] == "python"
        assert call_args[1]["timeout"] == 30

        # Verify result
        assert result.success is True
        assert result.stdout == "Hello from script"


@pytest.mark.asyncio
async def test_execute_tool_uses_default_timeout():
    """Test execute_tool uses default timeout when not specified."""
    # Mock ScriptExecutor.execute
    with patch.object(
        ScriptExecutor,
        "execute",
        return_value=ExecutionResult(
            success=True,
            stdout="",
            stderr="",
            exit_code=0,
        ),
    ) as mock_execute:
        # Call execute_tool without timeout parameter
        await execute_tool(
            "execute_script",
            {
                "script_content": "echo 'test'",
                "script_type": "bash",
            },
        )

        # Verify ScriptExecutor.execute was called
        # Lambda wrapper maps script_content -> content
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert call_args[1]["content"] == "echo 'test'"
        assert call_args[1]["script_type"] == "bash"


@pytest.mark.asyncio
async def test_execute_tool_validation_error():
    """Test execute_tool handles validation errors from ScriptExecutor."""
    # Mock ScriptExecutor.execute to return validation error
    with patch.object(
        ScriptExecutor,
        "execute",
        return_value=ExecutionResult(
            success=False,
            validation_error="Secret detected: hardcoded password",
        ),
    ) as mock_execute:
        # Call execute_tool with script containing secrets
        result = await execute_tool(
            "execute_script",
            {
                "script_content": "password = 'secret123'",
                "script_type": "python",
            },
        )

        # Verify validation error returned
        assert result.success is False
        assert result.validation_error is not None
        assert "secret" in result.validation_error.lower()
