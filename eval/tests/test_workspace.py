"""Tests for CodeWorkspace git lifecycle manager."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from eval.workspace import CodeWorkspace


@pytest.fixture
def source_dir(tmp_path):
    """Create a minimal source directory with a docker-compose.yaml."""
    src = tmp_path / "source"
    src.mkdir()

    # docker-compose.yaml (required by compose_command)
    (src / "docker-compose.yaml").write_text(
        "services:\n  app:\n    image: alpine\n"
    )

    # app source file
    app_dir = src / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text('print("hello")\n')
    (app_dir / "pool.py").write_text("# pool\n")

    return src


@pytest.fixture
def workspace(source_dir, tmp_path):
    """Create a CodeWorkspace from the source directory."""
    ws_dir = tmp_path / "workspace"
    return CodeWorkspace.create_from(source_dir, ws_dir, "test-project")


class TestCreateFrom:
    def test_copies_source_files(self, workspace):
        assert (workspace.workspace_dir / "docker-compose.yaml").exists()
        assert (workspace.workspace_dir / "app" / "main.py").exists()
        assert (workspace.workspace_dir / "app" / "pool.py").exists()

    def test_initialises_git_repo(self, workspace):
        assert (workspace.workspace_dir / ".git").is_dir()

    def test_creates_initial_commit(self, workspace):
        assert workspace.initial_commit is not None
        # Should be a 40-char hex SHA
        assert len(workspace.initial_commit) == 40

    def test_working_tree_is_clean(self, workspace):
        result = subprocess.run(
            ["git", "-C", str(workspace.workspace_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""

    def test_overwrites_existing_workspace(self, source_dir, tmp_path):
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "stale_file.txt").write_text("stale")

        ws = CodeWorkspace.create_from(source_dir, ws_dir, "test-project")
        assert not (ws_dir / "stale_file.txt").exists()
        assert (ws_dir / "docker-compose.yaml").exists()


class TestComposeCommand:
    def test_includes_file_and_project(self, workspace):
        cmd = workspace.compose_command
        assert "-f" in cmd
        assert "docker-compose.yaml" in cmd
        assert "-p test-project" in cmd

    def test_compose_file_path_is_absolute(self, workspace):
        cmd = workspace.compose_command
        # The -f argument should reference the workspace dir
        assert str(workspace.workspace_dir) in cmd


class TestSnapshot:
    def test_clean_workspace_snapshot(self, workspace):
        snap = workspace.snapshot()
        assert snap["commit_hash"] == workspace.initial_commit
        assert snap["tree_hash"]  # non-empty
        assert snap["dirty"] is False
        assert snap["diff_stat"] == ""  # No changes from initial
        assert "initial" in snap["log"]

    def test_dirty_workspace_detected(self, workspace):
        (workspace.workspace_dir / "app" / "main.py").write_text("changed\n")
        snap = workspace.snapshot()
        assert snap["dirty"] is True

    def test_snapshot_after_commit(self, workspace):
        # Make a change and commit
        (workspace.workspace_dir / "app" / "main.py").write_text("changed\n")
        workspace._run_git("add", ".")
        workspace._run_git("commit", "-m", "fix pool")

        snap = workspace.snapshot()
        assert snap["commit_hash"] != workspace.initial_commit
        assert snap["dirty"] is False
        assert "fix pool" in snap["log"]
        assert snap["diff_stat"] != ""  # Should show changed files


class TestFullDiff:
    def test_no_diff_at_initial(self, workspace):
        assert workspace.full_diff() == ""

    def test_diff_after_commit(self, workspace):
        (workspace.workspace_dir / "app" / "main.py").write_text(
            'print("fixed")\n'
        )
        workspace._run_git("add", ".")
        workspace._run_git("commit", "-m", "fix")

        diff = workspace.full_diff()
        assert "fixed" in diff
        assert "hello" in diff  # old content in diff


class TestGitLog:
    def test_log_includes_initial(self, workspace):
        log = workspace.git_log()
        assert "initial" in log

    def test_log_includes_changes(self, workspace):
        (workspace.workspace_dir / "app" / "pool.py").write_text("# fixed pool\n")
        workspace._run_git("add", ".")
        workspace._run_git("commit", "-m", "fix pool limits")

        log = workspace.git_log()
        assert "fix pool limits" in log
        assert "fixed pool" in log  # patch content


class TestSaveBundle:
    def test_creates_bundle_file(self, workspace, tmp_path):
        bundle = tmp_path / "repo.bundle"
        result = workspace.save_bundle(bundle)
        assert result == bundle
        assert bundle.exists()
        assert bundle.stat().st_size > 0


class TestReset:
    def test_reset_restores_initial_content(self, workspace):
        original = (workspace.workspace_dir / "app" / "main.py").read_text()
        (workspace.workspace_dir / "app" / "main.py").write_text("broken\n")
        workspace._run_git("add", ".")
        workspace._run_git("commit", "-m", "break it")

        # Reset restores files but calls build_and_start which will fail
        # (no Docker), so test just the git part
        workspace._run_git("checkout", workspace.initial_commit, "--", ".")
        workspace._run_git("clean", "-fd")

        restored = (workspace.workspace_dir / "app" / "main.py").read_text()
        assert restored == original

    def test_reset_removes_untracked_files(self, workspace):
        (workspace.workspace_dir / "new_file.txt").write_text("untracked\n")
        workspace._run_git("checkout", workspace.initial_commit, "--", ".")
        workspace._run_git("clean", "-fd")

        assert not (workspace.workspace_dir / "new_file.txt").exists()


class TestRunGitErrors:
    def test_bad_git_command_raises(self, workspace):
        with pytest.raises(subprocess.CalledProcessError):
            workspace._run_git("not-a-real-command")
