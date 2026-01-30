"""Operator subprocess management for managed eval mode."""

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console

if TYPE_CHECKING:
    from eval.types import EvalSubject

console = Console()


class OperatorProcesses:
    """Manage operator monitor and agent subprocesses.

    The operator (monitor + agent) should be started AFTER the subject
    cluster is running, because the monitor needs to connect to the
    cluster's APIs (e.g., PD on localhost:2379 for TiKV).
    """

    def __init__(
        self,
        subject_name: str,
        operator_db_path: Path,
        project_root: Optional[Path] = None,
        eval_subject: Optional["EvalSubject"] = None,
    ):
        self.subject_name = subject_name
        self.operator_db_path = operator_db_path
        self.project_root = project_root or self._find_project_root()
        self.eval_subject = eval_subject  # Used to reset cluster before starting
        self.monitor_proc: Optional[subprocess.Popen] = None
        self.agent_proc: Optional[subprocess.Popen] = None
        self._started = False

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
        """Start monitor and agent subprocesses.

        If eval_subject was provided, resets the cluster first so the
        monitor can connect to the cluster's APIs.
        """
        # Reset the subject cluster FIRST so the monitor can connect
        if self.eval_subject is not None:
            console.print("[bold blue]Resetting subject cluster...[/bold blue]")
            await self.eval_subject.reset()
            console.print("[bold blue]Waiting for cluster to be healthy...[/bold blue]")
            healthy = await self.eval_subject.wait_healthy(timeout_sec=120.0)
            if not healthy:
                console.print("[yellow]Warning: Cluster may not be fully healthy[/yellow]")
            else:
                console.print("[green]Cluster healthy[/green]")

        # Ensure operator.db directory exists
        self.operator_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Environment for subprocesses
        env = os.environ.copy()
        env["OPERATOR_DB_PATH"] = str(self.operator_db_path)

        console.print(f"[dim]Starting operator in: {self.project_root}[/dim]")
        console.print(f"[dim]Using database: {self.operator_db_path}[/dim]")

        # Start monitor subprocess with fast check interval for eval
        console.print("[bold blue]Starting operator monitor (5s interval)...[/bold blue]")
        self.monitor_proc = subprocess.Popen(
            [
                "uv", "run", "operator", "monitor", "run",
                "--subject", self.subject_name,
                "--db", str(self.operator_db_path),
                "--interval", "5",  # Fast interval for eval
            ],
            cwd=self.project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Give monitor time to initialize
        await asyncio.sleep(3.0)

        if self.monitor_proc.poll() is not None:
            # Monitor exited early - read output for error
            stdout, _ = self.monitor_proc.communicate(timeout=1)
            raise RuntimeError(f"Monitor failed to start: {stdout}")

        console.print(f"[green]Monitor started (PID {self.monitor_proc.pid})[/green]")

        # Start agent subprocess
        console.print("[bold blue]Starting operator agent...[/bold blue]")
        self.agent_proc = subprocess.Popen(
            [
                "uv", "run", "operator", "agent", "start",
                "--db", str(self.operator_db_path),
            ],
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
        self._started = True

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
