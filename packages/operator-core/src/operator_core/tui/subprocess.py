"""
SubprocessManager for spawning and managing daemon subprocesses.

This module provides infrastructure for running monitor and agent daemons
as real processes with live output capture. Following patterns from 08-RESEARCH.md:

- Pattern 1: PYTHONUNBUFFERED=1 for unbuffered output
- Pattern 2: asyncio.wait_for(readline(), timeout=0.1) for responsive shutdown
- Pattern 3: SIGTERM -> wait -> SIGKILL for graceful termination
- Pattern 4: start_new_session=True for orphan prevention
"""

import asyncio
import os
import sys
from dataclasses import dataclass

from operator_core.tui.buffer import OutputBuffer


@dataclass
class ManagedProcess:
    """
    Wrapper for a subprocess with its output buffer.

    Attributes:
        process: The asyncio subprocess handle
        buffer: Ring buffer for captured output
        name: Identifier for this process (e.g., "monitor", "agent")
    """

    process: asyncio.subprocess.Process
    buffer: OutputBuffer
    name: str


class SubprocessManager:
    """
    Manages subprocess lifecycle for TUI daemons.

    Handles spawning, output capture, and graceful shutdown of subprocesses.
    Designed for integration with TUIController's TaskGroup.

    Example:
        mgr = SubprocessManager()
        proc = await mgr.spawn("monitor", ["monitor", "run", "-i", "5"])
        read_task = asyncio.create_task(mgr.read_output(proc))
        # ... later ...
        await mgr.terminate_all()
    """

    def __init__(self) -> None:
        """Initialize subprocess manager with empty process registry."""
        self._processes: dict[str, ManagedProcess] = {}
        self._shutdown = asyncio.Event()

    @property
    def shutdown(self) -> asyncio.Event:
        """Return shutdown event for external coordination."""
        return self._shutdown

    async def spawn(
        self,
        name: str,
        command: list[str],
        buffer_size: int = 50,
        env: dict[str, str] | None = None,
    ) -> ManagedProcess:
        """
        Spawn a subprocess with output capture.

        Uses PYTHONUNBUFFERED=1 for immediate output (Pattern 1).
        Creates process in new session for clean termination (Pattern 4).

        Args:
            name: Identifier for this process (e.g., "monitor", "agent")
            command: CLI arguments (passed to Python -c or as module args)
            buffer_size: Maximum lines in output buffer
            env: Optional environment variables to add (merged with current env)

        Returns:
            ManagedProcess with process handle and output buffer
        """
        # Start with current environment (preserves PATH, HOME, etc.)
        subprocess_env = os.environ.copy()
        subprocess_env["PYTHONUNBUFFERED"] = "1"

        # Merge caller-provided environment variables
        if env:
            subprocess_env.update(env)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=subprocess_env,
            start_new_session=True,
        )

        buffer = OutputBuffer(maxlen=buffer_size)
        managed = ManagedProcess(process=proc, buffer=buffer, name=name)
        self._processes[name] = managed
        return managed

    async def read_output(self, managed: ManagedProcess) -> None:
        """
        Read output from subprocess into buffer.

        Runs until shutdown event is set or process exits.
        Uses short timeout (0.1s) for responsive shutdown (Pattern 2).
        Handles CancelledError gracefully for TaskGroup compatibility.

        Args:
            managed: The ManagedProcess to read from
        """
        proc = managed.process
        buffer = managed.buffer

        try:
            while not self._shutdown.is_set() and proc.returncode is None:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=0.1,
                    )
                    if line:
                        buffer.append(line.decode("utf-8", errors="replace"))
                    elif proc.returncode is not None:
                        break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass  # Normal shutdown via TaskGroup

    async def terminate(
        self,
        name: str,
        timeout: float = 5.0,
    ) -> None:
        """
        Gracefully terminate a subprocess.

        Sends SIGTERM, waits for exit, escalates to SIGKILL if needed (Pattern 3).
        Always awaits proc.wait() to prevent zombies.

        Args:
            name: Identifier of process to terminate
            timeout: Seconds to wait before SIGKILL
        """
        if name not in self._processes:
            return

        managed = self._processes[name]
        proc = managed.process

        if proc.returncode is not None:
            # Already exited, just clean up registry
            del self._processes[name]
            return

        # Graceful termination (SIGTERM)
        proc.terminate()

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill (SIGKILL)
            proc.kill()
            await proc.wait()

        del self._processes[name]

    async def terminate_all(self, timeout: float = 5.0) -> None:
        """
        Terminate all managed subprocesses.

        Sets shutdown event first to signal reader tasks, then
        terminates each process.

        Args:
            timeout: Seconds to wait for each process before SIGKILL
        """
        self._shutdown.set()
        for name in list(self._processes.keys()):
            await self.terminate(name, timeout=timeout)

    def get_buffer(self, name: str) -> OutputBuffer | None:
        """
        Get output buffer for a subprocess.

        Args:
            name: Identifier of the process

        Returns:
            OutputBuffer if process exists, None otherwise
        """
        if name in self._processes:
            return self._processes[name].buffer
        return None
