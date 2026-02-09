"""Chat DB App evaluation subject implementing EvalSubject protocol.

Uses CodeWorkspace for all Docker operations and git tracking.
The app has intentional bugs that manifest under load — chaos injection
is simply increasing load intensity.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from eval.workspace import CodeWorkspace

logger = logging.getLogger(__name__)

# Port allocation for parallel instances
BASE_APP_PORT = 8000
BASE_PG_PORT = 5432
BASE_PROM_PORT = 9090
PORT_INCREMENT = 10000

# Load profiles
LIGHT_LOAD = {
    "NUM_USERS": "3",
    "REQUEST_DELAY": "2.0",
    "STREAM_RATIO": "0.3",
    "RAMP_UP_SECONDS": "10",
}

HEAVY_LOAD = {
    "NUM_USERS": "20",
    "REQUEST_DELAY": "0.5",
    "STREAM_RATIO": "0.5",
    "RAMP_UP_SECONDS": "5",
}


class ChatDBAppEvalSubject:
    """Chat DB App evaluation subject.

    Implements EvalSubject protocol for the naive chat application.
    Uses CodeWorkspace to manage a git-tracked copy of the service
    source that the agent can read, edit, and rebuild.
    """

    def __init__(
        self,
        instance_id: int = 0,
        workspace_base: Path | None = None,
    ) -> None:
        self.instance_id = instance_id

        # Port allocation for parallel isolation
        port_offset = instance_id * PORT_INCREMENT
        self.app_port = BASE_APP_PORT + port_offset
        self.pg_port = BASE_PG_PORT + port_offset
        self.prom_port = BASE_PROM_PORT + port_offset

        # Project name for Docker Compose isolation
        self.project_name = (
            f"chat-db-eval-{instance_id}" if instance_id > 0 else "chat-db-app"
        )

        # Workspace paths
        if workspace_base is None:
            workspace_base = Path("/tmp/eval-workspaces")
        self.workspace_base = workspace_base
        self.workspace_dir = workspace_base / f"chat-db-app-{instance_id}"

        # Source directory (subjects/chat-db-app/service/)
        # __file__ = eval/src/eval/subjects/chat_db_app/subject.py
        # parents[5] = repo root
        self.source_dir = (
            Path(__file__).parents[5]
            / "subjects"
            / "chat-db-app"
            / "service"
        )

        self.workspace: CodeWorkspace | None = None
        self._chaos_load_active = False

    async def _ensure_workspace(self) -> CodeWorkspace:
        """Create workspace if it doesn't exist yet."""
        if self.workspace is not None:
            return self.workspace

        self.workspace = await asyncio.to_thread(
            CodeWorkspace.create_from,
            self.source_dir,
            self.workspace_dir,
            self.project_name,
        )

        # Add .env to .gitignore so it doesn't dirty the workspace
        # (.env changes between light/heavy load across trials)
        gitignore = self.workspace_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".env\n")
            await asyncio.to_thread(self.workspace._run_git, "add", ".gitignore")
            await asyncio.to_thread(
                self.workspace._run_git, "commit", "-m", "add .gitignore"
            )
            # Update initial_commit to include .gitignore so reset() restores
            # to this clean baseline rather than the bare initial commit
            self.workspace.initial_commit = (
                await asyncio.to_thread(self.workspace._run_git, "rev-parse", "HEAD")
            ).strip()

        # Write instance-specific .env for port isolation
        env_file = self.workspace_dir / ".env"
        env_file.write_text(
            f"PG_HOST_PORT={self.pg_port}\n"
            f"APP_HOST_PORT={self.app_port}\n"
            f"PROM_HOST_PORT={self.prom_port}\n"
            # Start with light load
            f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}\n"
            f"REQUEST_DELAY={LIGHT_LOAD['REQUEST_DELAY']}\n"
            f"STREAM_RATIO={LIGHT_LOAD['STREAM_RATIO']}\n"
            f"RAMP_UP_SECONDS={LIGHT_LOAD['RAMP_UP_SECONDS']}\n"
        )

        return self.workspace

    async def reset(self) -> None:
        """Reset to initial code and rebuild all containers."""
        ws = await self._ensure_workspace()

        # Stop running containers
        try:
            await asyncio.to_thread(ws.stop)
        except Exception as e:
            logger.debug("Stop during reset: %s", e)

        # If workspace already existed from a previous trial, restore code
        if ws.initial_commit:
            try:
                # Reset HEAD, index, and working tree to initial state
                await asyncio.to_thread(
                    ws._run_git, "reset", "--hard", ws.initial_commit
                )
                await asyncio.to_thread(ws._run_git, "clean", "-fd")
            except Exception as e:
                logger.debug("Git reset: %s", e)

        # Rewrite .env with light load (reset chaos)
        env_file = self.workspace_dir / ".env"
        env_file.write_text(
            f"PG_HOST_PORT={self.pg_port}\n"
            f"APP_HOST_PORT={self.app_port}\n"
            f"PROM_HOST_PORT={self.prom_port}\n"
            f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}\n"
            f"REQUEST_DELAY={LIGHT_LOAD['REQUEST_DELAY']}\n"
            f"STREAM_RATIO={LIGHT_LOAD['STREAM_RATIO']}\n"
            f"RAMP_UP_SECONDS={LIGHT_LOAD['RAMP_UP_SECONDS']}\n"
        )

        self._chaos_load_active = False

        # Build and start everything
        await asyncio.to_thread(ws.build_and_start)

    async def wait_healthy(self, timeout_sec: float = 120.0) -> bool:
        """Wait for the app to respond to /health."""
        start = asyncio.get_running_loop().time()
        url = f"http://localhost:{self.app_port}/health"

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("status") == "healthy":
                            logger.debug("App healthy after %.1fs", asyncio.get_running_loop().time() - start)
                            return True
            except Exception:
                pass
            await asyncio.sleep(2.0)

        logger.warning("Health check timeout after %.0fs", timeout_sec)
        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture app health, metrics, and code workspace state."""
        state: dict[str, Any] = {}

        # App health
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"http://localhost:{self.app_port}/health"
                )
                state["app"] = resp.json()
        except Exception as e:
            state["app"] = {"error": str(e)}

        # Code workspace snapshot
        if self.workspace:
            try:
                snapshot = await asyncio.to_thread(self.workspace.snapshot)
                state["code_workspace"] = snapshot
                state["code_diff"] = await asyncio.to_thread(
                    self.workspace.full_diff
                )
            except Exception as e:
                state["code_workspace"] = {"error": str(e)}

        return state

    def get_chaos_types(self) -> list[str]:
        """Return supported chaos types.

        For chat-db-app, the bugs are already in the code. Chaos is
        just increasing load until the naive patterns break.
        """
        return ["load_pressure"]

    async def inject_chaos(
        self, chaos_type: str, **params: Any
    ) -> dict[str, Any]:
        """Inject load pressure to trigger the app's latent bugs.

        Args:
            chaos_type: Must be "load_pressure"
            **params: Optional overrides for NUM_USERS, REQUEST_DELAY,
                STREAM_RATIO.

        Returns:
            Chaos metadata dict.
        """
        if chaos_type != "load_pressure":
            raise ValueError(
                f"Unknown chaos type: {chaos_type}. "
                f"Supported: {self.get_chaos_types()}"
            )

        ws = await self._ensure_workspace()

        # Merge defaults with overrides
        load = dict(HEAVY_LOAD)
        for key in ("num_users", "request_delay", "stream_ratio"):
            if key in params:
                load[key.upper()] = str(params[key])

        # Rewrite .env with heavy load settings
        env_file = self.workspace_dir / ".env"
        env_file.write_text(
            f"PG_HOST_PORT={self.pg_port}\n"
            f"APP_HOST_PORT={self.app_port}\n"
            f"PROM_HOST_PORT={self.prom_port}\n"
            f"NUM_USERS={load['NUM_USERS']}\n"
            f"REQUEST_DELAY={load['REQUEST_DELAY']}\n"
            f"STREAM_RATIO={load['STREAM_RATIO']}\n"
            f"RAMP_UP_SECONDS={load.get('RAMP_UP_SECONDS', '5')}\n"
        )

        # Restart loadgen with new env
        try:
            await asyncio.to_thread(
                ws._run_compose, "up", "-d", "--force-recreate", "loadgen"
            )
        except Exception as e:
            logger.warning("Failed to restart loadgen: %s", e)

        self._chaos_load_active = True

        return {
            "chaos_type": "load_pressure",
            "load_params": load,
            "previous_load": LIGHT_LOAD,
        }

    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Revert load back to light levels."""
        if not chaos_metadata or chaos_metadata.get("chaos_type") != "load_pressure":
            return

        ws = await self._ensure_workspace()

        # Restore light load
        env_file = self.workspace_dir / ".env"
        env_file.write_text(
            f"PG_HOST_PORT={self.pg_port}\n"
            f"APP_HOST_PORT={self.app_port}\n"
            f"PROM_HOST_PORT={self.prom_port}\n"
            f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}\n"
            f"REQUEST_DELAY={LIGHT_LOAD['REQUEST_DELAY']}\n"
            f"STREAM_RATIO={LIGHT_LOAD['STREAM_RATIO']}\n"
            f"RAMP_UP_SECONDS={LIGHT_LOAD['RAMP_UP_SECONDS']}\n"
        )

        try:
            await asyncio.to_thread(
                ws._run_compose, "up", "-d", "--force-recreate", "loadgen"
            )
        except Exception as e:
            logger.warning("Failed to restart loadgen during cleanup: %s", e)

        self._chaos_load_active = False

    def get_agent_context(self) -> str:
        """Return the prompt context for the agent.

        Includes workspace path and the exact compose commands the agent
        should use to rebuild the app after editing code.
        """
        if not self.workspace:
            return ""

        ws = self.workspace
        workspace_path = ws.workspace_dir

        return f"""
Directory layout:
- docker-compose.yaml is at: {workspace_path}/docker-compose.yaml
- Editable source code is at: {workspace_path}/app/
  (main.py, pool.py, models.py, streaming.py, Dockerfile)

Rebuild after editing code:
    {ws.compose_command} build app
    {ws.compose_command} up -d app

Other useful commands:
    {ws.compose_command} ps
    {ws.compose_command} logs app --tail 50
    git -C {workspace_path} diff
"""
