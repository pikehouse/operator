"""Shell execution tool for autonomous agent."""
import asyncio
from asyncio.subprocess import PIPE


async def shell(command: str, reasoning: str, timeout: float = 120.0) -> dict:
    """Execute a shell command with timeout.

    This is a pure execution function - it runs commands and returns results,
    but does not perform any logging. The agent loop (Phase 31) is responsible
    for logging tool calls via SessionAuditor.log_tool_call().

    Args:
        command: Shell command to execute (passed directly to shell, no sanitization)
        reasoning: Why this command is being executed (logged by caller, not validated here)
        timeout: Maximum execution time in seconds (default: 120.0)

    Returns:
        dict with keys:
            - stdout (str): Standard output, decoded as UTF-8, empty string if none
            - stderr (str): Standard error, decoded as UTF-8, error message if timeout
            - exit_code (int): Process return code, -1 if timeout
            - timed_out (bool): True if command exceeded timeout

    Note:
        - Commands are NOT sanitized or validated - "let Claude cook"
        - On timeout, process is killed and zombie prevention is handled
        - Decode errors are handled gracefully with 'replace' error handling
    """
    try:
        # Create subprocess with pipes for stdout/stderr
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=PIPE,
            stderr=PIPE
        )

        # Wait for completion with timeout
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )

            # Decode output
            stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "timed_out": False,
            }

        except asyncio.TimeoutError:
            # Kill the process and wait for cleanup to prevent zombies
            proc.kill()
            await proc.wait()

            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
                "exit_code": -1,
                "timed_out": True,
            }

    except Exception as e:
        # Handle unexpected errors during process creation
        return {
            "stdout": "",
            "stderr": f"Failed to execute command: {str(e)}",
            "exit_code": -1,
            "timed_out": False,
        }
