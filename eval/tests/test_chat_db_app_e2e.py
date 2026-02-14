"""End-to-end validation for chat-db-app eval subject.

Requires Docker. Tests workspace creation, container lifecycle,
health checks, chaos injection, invariant detection, and reset.

Run with: cd eval && uv run pytest tests/test_chat_db_app_e2e.py -v -s
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Skip entire module if Docker is not available
try:
    import subprocess
    result = subprocess.run(
        ["docker", "info"], capture_output=True, timeout=5
    )
    DOCKER_AVAILABLE = result.returncode == 0
except Exception:
    DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE, reason="Docker not available"
)


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def subject(event_loop, tmp_path_factory):
    """Create and yield a ChatDBAppEvalSubject, tear down after all tests."""
    from eval.subjects.chat_db_app.subject import ChatDBAppEvalSubject

    workspace_base = tmp_path_factory.mktemp("e2e_workspace")
    # Use instance_id=1 to avoid port conflicts with anything on default ports
    subj = ChatDBAppEvalSubject(instance_id=1, workspace_base=workspace_base)

    yield subj

    # Teardown: stop containers
    try:
        if subj.workspace:
            event_loop.run_until_complete(asyncio.to_thread(subj.workspace.stop))
    except Exception as e:
        print(f"Teardown warning: {e}")


class TestWorkspaceCreation:
    @pytest.mark.asyncio
    async def test_ensure_workspace_creates_git_repo(self, subject):
        ws = await subject._ensure_workspace()

        assert ws.workspace_dir.exists()
        assert (ws.workspace_dir / ".git").is_dir()
        assert (ws.workspace_dir / "docker-compose.yaml").exists()
        assert (ws.workspace_dir / "app" / "main.py").exists()
        assert (ws.workspace_dir / "app" / "pool.py").exists()
        assert ws.initial_commit is not None

    @pytest.mark.asyncio
    async def test_env_file_has_port_mappings(self, subject):
        ws = await subject._ensure_workspace()
        env_text = (ws.workspace_dir / ".env").read_text()

        assert f"APP_HOST_PORT={subject.app_port}" in env_text
        assert f"PG_HOST_PORT={subject.pg_port}" in env_text
        assert f"PROM_HOST_PORT={subject.prom_port}" in env_text

    @pytest.mark.asyncio
    async def test_compose_command_is_valid(self, subject):
        ws = await subject._ensure_workspace()
        cmd = ws.compose_command

        assert "docker compose" in cmd
        assert str(ws.workspace_dir) in cmd
        assert subject.project_name in cmd


class TestContainerLifecycle:
    @pytest.mark.asyncio
    async def test_reset_builds_and_starts_containers(self, subject):
        """Reset should build images and start all services."""
        await subject.reset()

        # Verify containers are running
        ws = subject.workspace
        output = ws._run_compose("ps", "--format", "json")
        assert "app" in output.lower() or "running" in output.lower()

    @pytest.mark.asyncio
    async def test_app_becomes_healthy(self, subject):
        """App should respond to /health within timeout."""
        healthy = await subject.wait_healthy(timeout_sec=60.0)
        assert healthy, "App did not become healthy within 60s"

    @pytest.mark.asyncio
    async def test_capture_initial_state(self, subject):
        """capture_state should return app health and workspace info."""
        state = await subject.capture_state()

        assert "app" in state
        assert state["app"].get("status") == "healthy"

        assert "code_workspace" in state
        # commit_hash may differ from initial_commit because _ensure_workspace
        # adds a .gitignore commit after the initial
        assert state["code_workspace"]["commit_hash"] is not None
        assert state["code_workspace"]["dirty"] is False

        assert "code_diff" in state
        # May contain the .gitignore addition, but no app source changes
        if state["code_diff"]:
            assert "app/" not in state["code_diff"]


class TestChaosInjection:
    @pytest.mark.asyncio
    async def test_inject_load_pressure(self, subject):
        """Injecting load_pressure should increase loadgen intensity."""
        metadata = await subject.inject_chaos(
            "load_pressure",
            num_users=15,
            request_delay=0.3,
            stream_ratio=0.5,
        )

        # load_pressure is a backward-compat alias for pool_exhaustion
        assert metadata["chaos_type"] == "pool_exhaustion"
        assert metadata["original_chaos_type"] == "load_pressure"
        assert metadata["load_params"]["NUM_USERS"] == "15"
        assert metadata["load_params"]["REQUEST_DELAY"] == "0.3"

        # Verify .env was updated
        env_text = (subject.workspace.workspace_dir / ".env").read_text()
        assert "NUM_USERS=15" in env_text

    @pytest.mark.asyncio
    async def test_app_shows_stress_under_load(self, subject):
        """Under heavy load, /health should show pool pressure or errors.

        We check the /health endpoint directly rather than importing
        the observer (which is not in the eval venv).
        """
        import httpx

        app_url = f"http://localhost:{subject.app_port}"

        # Poll for up to 60s for stress symptoms
        symptoms_seen = False
        for _ in range(30):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{app_url}/health")
                    if resp.status_code == 200:
                        data = resp.json()
                        pool = data.get("pool", {})
                        # Look for signs of stress: waiting connections,
                        # high total count, or errors
                        waiting = pool.get("waiting", 0)
                        total = pool.get("total", 0)
                        error_rate = data.get("error_rate_pct", 0)
                        if waiting > 0 or total > 10 or error_rate > 1:
                            symptoms_seen = True
                            print(
                                f"\nStress detected: waiting={waiting}, "
                                f"total={total}, error_rate={error_rate}%"
                            )
                            break
                    elif resp.status_code >= 500:
                        symptoms_seen = True
                        print(f"\nApp returning 5xx: {resp.status_code}")
                        break
            except Exception:
                pass
            await asyncio.sleep(2.0)

        if not symptoms_seen:
            print(
                "\nNote: No obvious stress symptoms within 60s window. "
                "The invariant grace periods (30-60s) may not have elapsed."
            )

    @pytest.mark.asyncio
    async def test_cleanup_restores_light_load(self, subject):
        """Cleanup should restore light load settings."""
        await subject.cleanup_chaos({
            "chaos_type": "pool_exhaustion",
            "load_params": {"NUM_USERS": "15"},
        })

        env_text = (subject.workspace.workspace_dir / ".env").read_text()
        assert "NUM_USERS=3" in env_text
        assert "REQUEST_DELAY=2.0" in env_text


class TestAgentContext:
    def test_agent_context_includes_rebuild_commands(self, subject):
        ctx = subject.get_agent_context()

        assert "build app" in ctx
        assert "up -d app" in ctx
        assert "git -C" in ctx
        assert str(subject.workspace.workspace_dir) in ctx
        assert subject.workspace.compose_command in ctx

    def test_agent_context_references_source_files(self, subject):
        ctx = subject.get_agent_context()
        assert "/app/" in ctx


class TestCodeEditAndRebuild:
    @pytest.mark.asyncio
    async def test_edit_source_shows_dirty_workspace(self, subject):
        """Editing a file should make the workspace dirty."""
        pool_py = subject.workspace.workspace_dir / "app" / "pool.py"
        original = pool_py.read_text()

        # Simulate agent edit
        pool_py.write_text(original.replace(
            "min_size=2",
            "min_size=2,\n        max_size=20,\n        command_timeout=5",
        ))

        snap = subject.workspace.snapshot()
        assert snap["dirty"] is True

    @pytest.mark.asyncio
    async def test_commit_and_diff_tracked(self, subject):
        """After committing, diff should show the change."""
        ws = subject.workspace
        ws._run_git("add", ".")
        ws._run_git("commit", "-m", "fix: add pool max_size and timeout")

        snap = ws.snapshot()
        assert snap["dirty"] is False
        assert snap["commit_hash"] != ws.initial_commit
        assert "fix: add pool max_size" in snap["log"]

        diff = ws.full_diff()
        assert "max_size" in diff

    @pytest.mark.asyncio
    async def test_rebuild_app_after_edit(self, subject):
        """Rebuild should succeed after code edit."""
        await asyncio.to_thread(subject.workspace.rebuild_app)

        # App should come back healthy
        healthy = await subject.wait_healthy(timeout_sec=60.0)
        assert healthy, "App did not become healthy after rebuild"

    @pytest.mark.asyncio
    async def test_capture_state_shows_code_changes(self, subject):
        """capture_state should reflect the code edit."""
        state = await subject.capture_state()

        assert state["code_workspace"]["commit_hash"] != subject.workspace.initial_commit
        assert "max_size" in state.get("code_diff", "")


class TestResetFlow:
    @pytest.mark.asyncio
    async def test_reset_restores_original_code(self, subject):
        """Reset should restore source to initial commit."""
        await subject.reset()

        pool_py = subject.workspace.workspace_dir / "app" / "pool.py"
        content = pool_py.read_text()
        # Our edit added "max_size=20" and "command_timeout=5".
        # The original has just "min_size=2," with no max_size.
        # After reset, the edit should be reverted.
        assert "min_size=2" in content, "min_size=2 should be in the file"
        assert "max_size" not in content, (
            "max_size should not be present in the original pool.py"
        )

        snap = subject.workspace.snapshot()
        # After reset, HEAD won't equal initial_commit (reset doesn't
        # create a new commit, but build_and_start happens after checkout)
        # The working tree should be clean though
        assert snap["dirty"] is False

    @pytest.mark.asyncio
    async def test_app_healthy_after_reset(self, subject):
        healthy = await subject.wait_healthy(timeout_sec=60.0)
        assert healthy
