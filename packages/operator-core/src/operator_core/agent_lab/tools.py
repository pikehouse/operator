"""Shell tool for agent with @beta_tool decorator."""

import subprocess

from anthropic import beta_tool

# Global state for capturing shell execution results.
# Needed because tool_runner doesn't yield results separately.
_last_shell_result: dict | None = None


def get_last_result() -> dict | None:
    """Get and clear the last shell result."""
    global _last_shell_result
    result = _last_shell_result
    _last_shell_result = None
    return result


@beta_tool
def shell(command: str, reasoning: str) -> str:
    """Execute a shell command.

    Args:
        command: The shell command to execute
        reasoning: Why this command is being run (for audit trail)

    Returns:
        Command output (stdout, or stdout+stderr on non-zero exit)
    """
    global _last_shell_result
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=120,
            text=True,
        )
        output = result.stdout
        exit_code = result.returncode
        if exit_code != 0:
            output += f"\n\nSTDERR: {result.stderr}\nExit code: {exit_code}"
        _last_shell_result = {
            "output": output,
            "exit_code": exit_code,
            "command": command,
            "reasoning": reasoning,
        }
        return output
    except subprocess.TimeoutExpired:
        output = "Command timed out after 120 seconds"
        _last_shell_result = {
            "output": output,
            "exit_code": 124,
            "command": command,
            "reasoning": reasoning,
        }
        return output
    except Exception as e:
        output = f"Error: {e}"
        _last_shell_result = {
            "output": output,
            "exit_code": 1,
            "command": command,
            "reasoning": reasoning,
        }
        return output
