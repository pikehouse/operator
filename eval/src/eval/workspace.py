"""Git-tracked code workspace for eval subjects.

Manages a git-initialized copy of a subject's source code so the agent
can read, edit, rebuild, and commit changes during a trial. The workspace
IS the docker compose project directory.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CodeWorkspace:
    """Lifecycle manager for a git-tracked source code workspace.

    The workspace directory contains docker-compose.yaml, Dockerfiles,
    and app source. All Docker operations go through ``compose_command``,
    which both the eval harness and the agent use identically.
    """

    def __init__(self, workspace_dir: Path, compose_project: str) -> None:
        self.workspace_dir = workspace_dir
        self.compose_project = compose_project
        self.initial_commit: str | None = None

    @classmethod
    def create_from(
        cls,
        source_dir: Path,
        workspace_dir: Path,
        compose_project: str,
    ) -> "CodeWorkspace":
        """Copy source into workspace and initialise a git repo.

        Args:
            source_dir: Path to the subject's service/ directory.
            workspace_dir: Where to create the workspace copy.
            compose_project: Docker Compose project name for isolation.

        Returns:
            A ready-to-use CodeWorkspace.
        """
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)

        shutil.copytree(source_dir, workspace_dir)

        ws = cls(workspace_dir, compose_project)

        # Initialise git repo
        ws._run_git("init")
        ws._run_git("add", ".")
        ws._run_git("commit", "-m", "initial")

        ws.initial_commit = ws._run_git("rev-parse", "HEAD").strip()
        return ws

    # ------------------------------------------------------------------
    # Docker Compose helpers
    # ------------------------------------------------------------------

    @property
    def compose_command(self) -> str:
        """Base compose command with ``-f`` and ``-p`` flags.

        Both the harness and the agent use this exact prefix.
        """
        compose_file = self.workspace_dir / "docker-compose.yaml"
        return f"docker compose -f {compose_file} -p {self.compose_project}"

    def _run_compose(self, *args: str, timeout: int = 300) -> str:
        """Run a docker compose subcommand."""
        cmd = self.compose_command.split() + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(
                "compose %s failed (rc=%d): %s",
                " ".join(args),
                result.returncode,
                result.stderr[:500],
            )
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result.stdout

    def build_and_start(self) -> None:
        """Build images and start all services.

        This is the SAME sequence the agent uses after editing code.
        """
        self._run_compose("build")
        self._run_compose("up", "-d")

    def stop(self) -> None:
        """Stop and remove all containers and volumes."""
        self._run_compose("down", "--volumes", "--remove-orphans")

    def rebuild_app(self) -> None:
        """Rebuild and restart only the app service.

        The agent runs exactly these commands after editing source.
        """
        self._run_compose("build", "app")
        self._run_compose("up", "-d", "app")

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _run_git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.workspace_dir)] + list(args),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                ["git"] + list(args),
                result.stdout,
                result.stderr,
            )
        return result.stdout

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of the current git state."""
        commit_hash = self._run_git("rev-parse", "HEAD").strip()
        tree_hash = self._run_git("rev-parse", "HEAD^{tree}").strip()

        # Check for uncommitted changes
        dirty_result = subprocess.run(
            ["git", "-C", str(self.workspace_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        dirty = bool(dirty_result.stdout.strip())

        diff_stat = ""
        if self.initial_commit and commit_hash != self.initial_commit:
            diff_stat = self._run_git(
                "diff", "--stat", f"{self.initial_commit}..HEAD"
            ).strip()

        log = self._run_git("log", "--oneline").strip()

        return {
            "commit_hash": commit_hash,
            "tree_hash": tree_hash,
            "dirty": dirty,
            "diff_stat": diff_stat,
            "log": log,
        }

    def full_diff(self) -> str:
        """Full diff from the initial commit to HEAD."""
        if not self.initial_commit:
            return ""
        head = self._run_git("rev-parse", "HEAD").strip()
        if head == self.initial_commit:
            return ""
        return self._run_git("diff", f"{self.initial_commit}..HEAD")

    def git_log(self) -> str:
        """Full git log with diffs."""
        return self._run_git("log", "-p")

    def save_bundle(self, output_path: Path) -> Path:
        """Save the entire repo as a git bundle file."""
        self._run_git("bundle", "create", str(output_path), "--all")
        return output_path

    def reset(self) -> None:
        """Restore source to the initial commit and rebuild."""
        if self.initial_commit:
            self._run_git("checkout", self.initial_commit, "--", ".")
            self._run_git("clean", "-fd")
        self.build_and_start()
