"""Operator subprocess management for managed eval mode."""

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


class OperatorProcesses:
    """Manage operator monitor and agent subprocesses."""

    def __init__(
        self,
        subject: str,
        operator_db_path: Path,
        project_root: Optional[Path] = None,
    ):
        self.subject = subject
        self.operator_db_path = operator_db_path
        self.project_root = project_root or self._find_project_root()
        self.monitor_proc: Optional[subprocess.Popen] = None
        self.agent_proc: Optional[subprocess.Popen] = None

    def _find_project_root(self) -> Path:
        """Find the operator project root (parent of eval/)."""
        # Start from current working directory
        cwd = Path.cwd()

        # If we're in eval/, go up one level
        if cwd.name == "eval":
            return cwd.parent

        # If we're in operator/, we're good
        if (cwd / "packages" / "operator-core").exists():
            return cwd

        # Try parent directories
        for parent in cwd.parents:
            if (parent / "packages" / "operator-core").exists():
                return parent

        # Default to parent of eval
        return cwd.parent

    async def start(self) -> None:
        """Start monitor and agent subprocesses."""
        # Ensure operator.db directory exists
        self.operator_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Environment for subprocesses
        env = os.environ.copy()
        env["OPERATOR_DB_PATH"] = str(self.operator_db_path)

        console.print(f"[dim]Starting operator in: {self.project_root}[/dim]")
        console.print(f"[dim]Using database: {self.operator_db_path}[/dim]")

        # Start monitor subprocess
        console.print("[bold blue]Starting operator monitor...[/bold blue]")
        self.monitor_proc = subprocess.Popen(
            ["uv", "run", "operator", "monitor", "run", "--subject", self.subject],
            cwd=self.project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Give monitor time to initialize
        await asyncio.sleep(2.0)

        if self.monitor_proc.poll() is not None:
            # Monitor exited early - read output for error
            stdout, _ = self.monitor_proc.communicate(timeout=1)
            raise RuntimeError(f"Monitor failed to start: {stdout}")

        console.print(f"[green]Monitor started (PID {self.monitor_proc.pid})[/green]")

        # Start agent subprocess
        console.print("[bold blue]Starting operator agent...[/bold blue]")
        self.agent_proc = subprocess.Popen(
            ["uv", "run", "operator", "agent", "run"],
            cwd=self.project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Give agent time to initialize
        await asyncio.sleep(2.0)

        if self.agent_proc.poll() is not None:
            # Agent exited early - read output for error
            stdout, _ = self.agent_proc.communicate(timeout=1)
            # Stop monitor before raising
            self._stop_process(self.monitor_proc, "monitor")
            raise RuntimeError(f"Agent failed to start: {stdout}")

        console.print(f"[green]Agent started (PID {self.agent_proc.pid})[/green]")

    def _stop_process(self, proc: Optional[subprocess.Popen], name: str) -> None:
        """Stop a subprocess gracefully."""
        if proc is None or proc.poll() is not None:
            return

        console.print(f"[dim]Stopping {name} (PID {proc.pid})...[/dim]")

        # Send SIGTERM for graceful shutdown
        proc.terminate()

        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            # Force kill if graceful shutdown fails
            console.print(f"[yellow]Force killing {name}...[/yellow]")
            proc.kill()
            proc.wait(timeout=2.0)

    async def stop(self) -> None:
        """Stop monitor and agent subprocesses."""
        console.print("[bold blue]Stopping operator processes...[/bold blue]")

        # Stop agent first (it depends on monitor)
        self._stop_process(self.agent_proc, "agent")
        self.agent_proc = None

        # Then stop monitor
        self._stop_process(self.monitor_proc, "monitor")
        self.monitor_proc = None

        console.print("[green]Operator processes stopped[/green]")

    async def __aenter__(self) -> "OperatorProcesses":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
