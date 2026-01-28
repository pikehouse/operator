"""Script execution in sandboxed Docker containers.

Executes validated Python and Bash scripts in isolated Docker containers with:
- Network isolation (--network none)
- Resource limits (512MB memory, 1 CPU, 100 PIDs)
- Non-root execution (user=nobody)
- Read-only filesystem
- Timeout enforcement
- Output capture (stdout, stderr, exit code)
"""

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from python_on_whales import docker
from python_on_whales.exceptions import DockerException

from operator_core.scripts.validation import ScriptValidator, ValidationResult


@dataclass
class ExecutionResult:
    """Result of script execution in sandbox.

    Attributes:
        success: Whether the script executed without errors
        stdout: Standard output from script execution
        stderr: Standard error from script execution
        exit_code: Process exit code
        timeout: Whether execution timed out
        validation_error: Validation error message if validation failed
    """

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timeout: bool = False
    validation_error: str | None = None


class ScriptExecutor:
    """Executor for Python and Bash scripts in sandboxed Docker containers.

    Validates scripts before execution and runs them in isolated containers
    with strict security constraints per SCRP-01 through SCRP-09.
    """

    # Container images for each script type (SCRP-02)
    IMAGES = {
        "python": "python:3.11-slim",
        "bash": "bash:5.2-alpine",
    }

    # Maximum timeout for script execution (SCRP-07)
    MAX_TIMEOUT = 300  # 5 minutes
    DEFAULT_TIMEOUT = 60  # 1 minute

    def __init__(self):
        """Initialize script executor with validator."""
        self._validator = ScriptValidator()
        self._docker = docker

    async def execute(
        self,
        content: str,
        script_type: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> ExecutionResult:
        """Execute script in sandboxed Docker container.

        Args:
            content: Script content to execute
            script_type: Either "python" or "bash"
            timeout: Execution timeout in seconds (default: 60, max: 300)

        Returns:
            ExecutionResult with stdout, stderr, exit_code, and flags

        Raises:
            ValueError: If script_type is invalid
        """
        # Validate script_type
        if script_type not in self.IMAGES:
            raise ValueError(
                f"Invalid script_type '{script_type}'. Must be 'python' or 'bash'"
            )

        # Clamp timeout to MAX_TIMEOUT
        effective_timeout = min(timeout, self.MAX_TIMEOUT)

        # Layer 1-4: Multi-layer validation (VALD-01 through VALD-06)
        validation = self._validator.validate(content, script_type)
        if not validation.valid:
            return ExecutionResult(
                success=False,
                validation_error=validation.error,
            )

        # Layer 5: Bash syntax validation with bash -n (VALD-02)
        if script_type == "bash":
            syntax_check = await self._validate_bash_syntax(content)
            if not syntax_check.valid:
                return ExecutionResult(
                    success=False,
                    validation_error=syntax_check.error,
                )

        # Execute in sandboxed Docker container
        try:
            result = await asyncio.wait_for(
                self._execute_in_sandbox(content, script_type),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                stderr=f"Script execution timed out after {effective_timeout}s",
                exit_code=-1,
                timeout=True,
            )

    async def _validate_bash_syntax(self, content: str) -> ValidationResult:
        """Validate Bash syntax using bash -n subprocess.

        Args:
            content: Bash script content

        Returns:
            ValidationResult with syntax error if invalid
        """
        try:
            # Create temporary file for syntax check
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False
            ) as f:
                f.write(content)
                temp_path = f.name

            try:
                # Run bash -n (syntax check only, no execution)
                proc = await asyncio.create_subprocess_exec(
                    "bash",
                    "-n",
                    temp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != 0:
                    return ValidationResult(
                        valid=False,
                        error=f"Bash syntax error: {stderr.decode()}",
                        layer="syntax",
                    )

                return ValidationResult(valid=True)
            finally:
                # Clean up temp file
                Path(temp_path).unlink(missing_ok=True)
        except Exception as e:
            return ValidationResult(
                valid=False,
                error=f"Bash syntax validation failed: {str(e)}",
                layer="syntax",
            )

    async def _execute_in_sandbox(
        self, content: str, script_type: str
    ) -> ExecutionResult:
        """Execute script in sandboxed Docker container.

        Args:
            content: Script content to execute
            script_type: Either "python" or "bash"

        Returns:
            ExecutionResult with captured output
        """
        loop = asyncio.get_running_loop()

        def _blocking_execute():
            try:
                # Determine command based on script type
                if script_type == "python":
                    command = ["python", "-c", content]
                else:  # bash
                    command = ["bash", "-c", content]

                # Execute in sandboxed container (SCRP-03 through SCRP-06)
                output = self._docker.run(
                    image=self.IMAGES[script_type],
                    command=command,
                    networks=["none"],  # SCRP-03: Network isolation
                    memory="512m",  # SCRP-04: Memory limit
                    cpus=1.0,  # SCRP-04: CPU limit
                    pids_limit=100,  # SCRP-04: PID limit
                    user="nobody",  # SCRP-05: Non-root execution
                    read_only=True,  # SCRP-05: Read-only filesystem
                    remove=True,  # SCRP-06: Ephemeral container
                    detach=False,  # Wait for completion
                )

                # Success - capture stdout (SCRP-08, SCRP-09)
                return ExecutionResult(
                    success=True,
                    stdout=output,
                    stderr="",
                    exit_code=0,
                )

            except DockerException as e:
                # Docker execution failed - parse error message
                error_msg = str(e)

                # Extract exit code if present in error message
                exit_code = 1
                if "exit code" in error_msg.lower():
                    try:
                        # Try to extract numeric exit code
                        parts = error_msg.split("exit code")
                        if len(parts) > 1:
                            code_str = parts[1].strip().split()[0].strip(":")
                            exit_code = int(code_str)
                    except (ValueError, IndexError):
                        pass

                # Capture stderr from error message (SCRP-08, SCRP-09)
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=error_msg,
                    exit_code=exit_code,
                )

        # Use run_in_executor for blocking Docker call
        return await loop.run_in_executor(None, _blocking_execute)
