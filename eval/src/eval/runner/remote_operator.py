"""Remote operator management for cloud eval trials.

Manages operator (monitor + agent) Docker containers on GCP VMs via SSH.
Mirrors the local OperatorProcesses class but works over SSH using the
CloudVM protocol.

The operator runs as Docker containers on the VM with:
- Host networking (for PD access at localhost:2379)
- Docker socket mount (for agent's shell tool)
- Shared data volume (for operator.db)
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from rich.console import Console

from eval.types import VariantConfig

logger = logging.getLogger(__name__)
console = Console()

# Container names on the VM
MONITOR_CONTAINER = "operator-monitor"
AGENT_CONTAINER = "operator-agent"
DATA_VOLUME = "operator-data"
OPERATOR_DB_PATH = "/data/operator.db"


class RemoteOperatorProcesses:
    """Manage operator monitor and agent as Docker containers on a GCP VM.

    The operator runs alongside the TiKV cluster on the same VM.
    All DB queries execute via SSH + docker exec (COS may not have
    sqlite3 natively, but the operator image has Python with sqlite3).
    """

    def __init__(
        self,
        vm: Any,  # CloudVM protocol
        operator_image: str,
        anthropic_api_key: str,
        subject_name: str = "tikv",
        extra_env: dict[str, str] | None = None,
        subject_context_extra: str = "",
        workspace_volume_mount: str = "",
        extra_volume_mounts: list[str] | None = None,
    ):
        """Initialize remote operator.

        Args:
            vm: CloudVM instance with run_command/download_file methods
            operator_image: Docker image URL for operator
                (e.g., us-central1-docker.pkg.dev/PROJECT/eval/operator:latest)
            anthropic_api_key: API key for the agent's LLM calls
            subject_name: Subject name for the monitor (e.g., 'tikv', 'chat-db-app')
            extra_env: Additional environment variables for operator containers
                (e.g., DATABASE_URL, APP_URL for chat-db-app)
            subject_context_extra: Additional agent prompt context (e.g., workspace
                rebuild commands). Passed via --subject-context-extra flag.
            workspace_volume_mount: Docker volume mount for workspace directory
                (e.g., '/var/lib/workspace:/var/lib/workspace'). Added to both
                monitor and agent containers so the agent can access source code.
            extra_volume_mounts: Additional volume mounts for the agent container
                (e.g., compose dir, toolbox config). Each entry is a Docker -v arg
                like '/host/path:/container/path'.
        """
        self.vm = vm
        self.operator_image = operator_image
        self.anthropic_api_key = anthropic_api_key
        self.subject_name = subject_name
        self.extra_env = extra_env or {}
        self.subject_context_extra = subject_context_extra
        self.workspace_volume_mount = workspace_volume_mount
        self.extra_volume_mounts = extra_volume_mounts or []
        self._started = False

    async def start(self) -> None:
        """Pull operator image and start monitor + agent containers.

        Creates a shared Docker volume for operator.db, then starts:
        1. operator-monitor (observes TiKV via PD at localhost:2379)
        2. operator-agent (diagnoses and resolves tickets)

        Both use host networking and Docker socket mount.
        """
        console.print("[bold blue]Starting remote operator...[/bold blue]")

        # Authenticate with Artifact Registry (COS has docker-credential-gcr)
        await self.vm.run_command(
            "docker-credential-gcr configure-docker --registries us-central1-docker.pkg.dev 2>/dev/null || true",
            timeout_sec=30.0,
        )

        # Pull operator image
        console.print(f"[dim]Pulling operator image: {self.operator_image}[/dim]")
        exit_code, stdout, stderr = await self.vm.run_command(
            f"docker pull {self.operator_image}",
            timeout_sec=300.0,
        )
        if exit_code != 0:
            raise RuntimeError(f"Failed to pull operator image: {stderr}")

        # Create shared data volume
        await self.vm.run_command(f"docker volume create {DATA_VOLUME}")

        # Ensure workspace and extra volume dirs are writable by container user (uid 1000)
        if self.workspace_volume_mount:
            host_path = self.workspace_volume_mount.split(":")[0]
            await self.vm.run_command(
                f"chmod -R a+rw {host_path} 2>/dev/null || true",
                timeout_sec=15.0,
            )
        for mount in self.extra_volume_mounts:
            host_path = mount.split(":")[0]
            await self.vm.run_command(
                f"chmod -R a+rw {host_path} 2>/dev/null || true",
                timeout_sec=15.0,
            )

        # Build extra env flags for docker run
        extra_env_flags = "".join(
            f"-e {k}={v} " for k, v in self.extra_env.items()
        )

        # Build optional volume mounts for workspace and extras
        workspace_mount_flag = ""
        if self.workspace_volume_mount:
            workspace_mount_flag = f"-v {self.workspace_volume_mount} "
        extra_mounts_flag = "".join(
            f"-v {m} " for m in self.extra_volume_mounts
        )

        # Build optional subject-context-extra flag for monitor
        context_extra_flag = ""
        if self.subject_context_extra:
            # Escape single quotes in the context string for shell
            escaped_context = self.subject_context_extra.replace("'", "'\\''")
            context_extra_flag = f" --subject-context-extra '{escaped_context}'"

        # Start monitor container (runs as root — doesn't use Agent SDK)
        console.print(f"[blue]Starting operator monitor ({self.subject_name}, 5s interval)...[/blue]")
        exit_code, _, stderr = await self.vm.run_command(
            f"docker run -d --name {MONITOR_CONTAINER} --network=host "
            f"--user root "
            f"-v /var/run/docker.sock:/var/run/docker.sock "
            f"-v {DATA_VOLUME}:/data "
            f"{workspace_mount_flag}"
            f"-e ANTHROPIC_API_KEY={self.anthropic_api_key} "
            f"{extra_env_flags}"
            f"{self.operator_image} "
            f"uv run operator monitor run --subject {self.subject_name} --db {OPERATOR_DB_PATH} --interval 5"
            f"{context_extra_flag}",
            timeout_sec=30.0,
        )
        if exit_code != 0:
            raise RuntimeError(f"Failed to start monitor: {stderr}")

        # Wait for monitor to create operator.db, then make it writable
        # by the agent's non-root user. The monitor creates the DB
        # asynchronously after startup, so we poll until it exists.
        for _ in range(15):
            exit_code, stdout, _ = await self.vm.run_command(
                f"docker exec {MONITOR_CONTAINER} test -f {OPERATOR_DB_PATH} && echo exists",
                timeout_sec=5.0,
            )
            if exit_code == 0 and "exists" in stdout:
                break
            await asyncio.sleep(1)
        await self.vm.run_command(
            f"docker exec {MONITOR_CONTAINER} chmod -R 777 /data",
            timeout_sec=10.0,
        )

        # Make Docker socket accessible to non-root agent user.
        # COS uses GID 412 for the socket, which doesn't match the container's
        # docker group (999). Making it world-accessible is safe since the VM
        # is single-purpose and ephemeral.
        await self.vm.run_command(
            "sudo chmod 666 /var/run/docker.sock 2>/dev/null || true",
            timeout_sec=5.0,
        )

        # Start agent container (runs as non-root appuser for bypassPermissions)
        # Git env vars ensure the agent can commit in cross-user workspaces:
        # - GIT_CONFIG_* sets safe.directory (bypasses ownership check)
        # - GIT_AUTHOR/COMMITTER_* sets identity (no .gitconfig needed)
        git_env = (
            "-e GIT_CONFIG_COUNT=2 "
            "-e GIT_CONFIG_KEY_0=safe.directory "
            "-e GIT_CONFIG_VALUE_0=/ "
            "-e GIT_CONFIG_KEY_1=safe.directory "
            "-e GIT_CONFIG_VALUE_1=/var/lib/workspace "
            "-e GIT_AUTHOR_NAME=eval "
            "-e GIT_AUTHOR_EMAIL=eval@operator "
            "-e GIT_COMMITTER_NAME=eval "
            "-e GIT_COMMITTER_EMAIL=eval@operator "
        )
        console.print("[blue]Starting operator agent...[/blue]")
        exit_code, _, stderr = await self.vm.run_command(
            f"docker run -d --name {AGENT_CONTAINER} --network=host "
            f"-v /var/run/docker.sock:/var/run/docker.sock "
            f"-v {DATA_VOLUME}:/data "
            f"{workspace_mount_flag}"
            f"{extra_mounts_flag}"
            f"-e ANTHROPIC_API_KEY={self.anthropic_api_key} "
            f"-e HOME=/home/appuser "
            f"{git_env}"
            f"{extra_env_flags}"
            f"{self.operator_image} "
            f"uv run operator agent start --db {OPERATOR_DB_PATH}",
            timeout_sec=30.0,
        )
        if exit_code != 0:
            # Clean up monitor before raising
            await self.vm.run_command(
                f"docker rm -f {MONITOR_CONTAINER}", timeout_sec=10.0
            )
            raise RuntimeError(f"Failed to start agent: {stderr}")

        # Health check: wait a few seconds then verify agent is still running
        await asyncio.sleep(3)
        exit_code, stdout, _ = await self.vm.run_command(
            f"docker inspect -f '{{{{.State.Running}}}}' {AGENT_CONTAINER} 2>/dev/null",
            timeout_sec=10.0,
        )
        if exit_code != 0 or "true" not in stdout.lower():
            # Agent crashed on startup - capture logs
            _, agent_logs, _ = await self.vm.run_command(
                f"docker logs {AGENT_CONTAINER} 2>&1 | tail -50",
                timeout_sec=10.0,
            )
            console.print(f"[red]Agent container crashed on startup![/red]")
            console.print(f"[red]Agent logs:\n{agent_logs}[/red]")
            # Clean up
            await self.vm.run_command(
                f"docker rm -f {AGENT_CONTAINER} {MONITOR_CONTAINER}",
                timeout_sec=10.0,
            )
            raise RuntimeError(f"Agent container crashed on startup: {agent_logs}")

        self._started = True
        console.print("[green]Remote operator started[/green]")

    async def stop(self) -> None:
        """Stop and remove operator containers."""
        if not self._started:
            return

        console.print("[blue]Stopping remote operator...[/blue]")

        # Capture container logs before removal for debugging
        for container in [AGENT_CONTAINER, MONITOR_CONTAINER]:
            _, logs, _ = await self.vm.run_command(
                f"docker logs {container} 2>&1 | tail -30",
                timeout_sec=10.0,
            )
            if logs.strip():
                console.print(f"[dim]{container} logs (last 30 lines):\n{logs}[/dim]")

        # Stop agent first, then monitor
        for container in [AGENT_CONTAINER, MONITOR_CONTAINER]:
            await self.vm.run_command(
                f"docker rm -f {container} 2>/dev/null || true",
                timeout_sec=15.0,
            )

        self._started = False
        console.print("[green]Remote operator stopped[/green]")

    async def _run_db_query(self, query: str) -> str:
        """Execute a SQLite query on operator.db via SSH + docker exec.

        Uses the monitor container's Python stdlib sqlite3 since COS
        may not have the sqlite3 binary.

        Args:
            query: SQL query to execute

        Returns:
            JSON string of query results
        """
        # Escape single quotes in query for shell
        escaped_query = query.replace("'", "\\'")

        python_script = (
            "import sqlite3, json; "
            f"conn = sqlite3.connect('{OPERATOR_DB_PATH}'); "
            "conn.row_factory = sqlite3.Row; "
            f"rows = conn.execute('{escaped_query}').fetchall(); "
            "print(json.dumps([dict(r) for r in rows])); "
            "conn.close()"
        )

        exit_code, stdout, stderr = await self.vm.run_command(
            f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
            timeout_sec=10.0,
        )

        if exit_code != 0:
            logger.debug(f"DB query failed: {stderr}")
            return "[]"

        return stdout.strip()

    async def _run_db_execute(self, statement: str) -> int:
        """Execute a SQLite write statement on operator.db via SSH.

        Args:
            statement: SQL statement to execute

        Returns:
            Number of rows affected
        """
        escaped_stmt = statement.replace("'", "\\'")

        python_script = (
            "import sqlite3; "
            f"conn = sqlite3.connect('{OPERATOR_DB_PATH}'); "
            f"cur = conn.execute('{escaped_stmt}'); "
            "conn.commit(); "
            "print(cur.rowcount); "
            "conn.close()"
        )

        exit_code, stdout, stderr = await self.vm.run_command(
            f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
            timeout_sec=10.0,
        )

        if exit_code != 0:
            logger.debug(f"DB execute failed: {stderr}")
            return 0

        try:
            return int(stdout.strip())
        except ValueError:
            return 0

    async def inject_ticket(
        self,
        invariant_name: str,
        message: str,
        subject_context: str = "",
        severity: str = "warning",
    ) -> None:
        """Inject a synthetic operator-override ticket into operator.db.

        Creates a ticket with type='operator-override' and held=1 so the
        monitor's auto-resolve won't clear it (no matching violation exists).

        Uses a parameterized Python script to avoid shell/SQL escaping issues.

        Args:
            invariant_name: Name for the injected invariant
            message: Human-readable task description for the agent
            subject_context: Optional agent prompt context
            severity: Ticket severity level
        """
        import base64

        violation_key = f"override:{invariant_name}"

        # Encode values as base64 to avoid all shell/quote escaping issues
        params = {
            "violation_key": violation_key,
            "invariant_name": invariant_name,
            "message": message,
            "severity": severity,
            "subject_context": subject_context,
        }
        params_b64 = base64.b64encode(json.dumps(params).encode()).decode()

        python_script = (
            "import sqlite3, json, base64; "
            f"p = json.loads(base64.b64decode('{params_b64}')); "
            f"conn = sqlite3.connect('{OPERATOR_DB_PATH}'); "
            "from datetime import datetime as dt; "
            "now = dt.utcnow().isoformat(); "
            "conn.execute("
            "'INSERT INTO tickets "
            "(violation_key, invariant_name, message, severity, "
            "first_seen_at, last_seen_at, status, held, type, subject_context) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)', "
            "[p['violation_key'], p['invariant_name'], p['message'], p['severity'], "
            "now, now, 'open', 'operator-override', p['subject_context']]); "
            "conn.commit(); conn.close(); print('OK')"
        )

        exit_code, stdout, stderr = await self.vm.run_command(
            f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
            timeout_sec=10.0,
        )

        if exit_code != 0:
            logger.warning(f"inject_ticket failed: {stderr}")
            console.print(f"[red]Failed to inject ticket: {stderr}[/red]")
        else:
            console.print(f"[green]Injected operator-override ticket: {invariant_name}[/green]")

    async def force_resolve_all_tickets(self) -> int:
        """Force-resolve all open tickets before injecting chaos.

        Returns:
            Number of tickets resolved
        """
        count = await self._run_db_execute(
            "UPDATE tickets SET status = \\'resolved\\', "
            "resolved_at = datetime(\\'now\\'), held = 0 "
            "WHERE status != \\'resolved\\'"
        )
        if count > 0:
            console.print(f"[dim]Force-resolved {count} startup ticket(s)[/dim]")
        return count

    async def get_max_ticket_id(self) -> int:
        """Get the maximum ticket ID in operator.db.

        Returns:
            Max ticket ID, or 0 if no tickets exist
        """
        result = await self._run_db_query("SELECT MAX(id) as max_id FROM tickets")
        try:
            rows = json.loads(result)
            if rows and rows[0].get("max_id") is not None:
                return rows[0]["max_id"]
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        return 0

    async def wait_for_ticket_resolution(
        self,
        timeout_sec: float = 300.0,
        min_ticket_id: int = 0,
    ) -> tuple[str | None, str | None]:
        """Wait for a ticket to be created and resolved.

        Args:
            timeout_sec: Maximum time to wait
            min_ticket_id: Only consider tickets with ID > this value

        Returns:
            Tuple of (ticket_created_at, resolved_at) or (None, None) if timeout
        """
        start = asyncio.get_running_loop().time()
        ticket_created_at: str | None = None

        console.print(f"[dim]Waiting up to {timeout_sec}s for ticket resolution...[/dim]")
        if min_ticket_id > 0:
            console.print(f"[dim]Looking for tickets with ID > {min_ticket_id}[/dim]")

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            result = await self._run_db_query(
                f"SELECT first_seen_at, resolved_at, status FROM tickets "
                f"WHERE id > {min_ticket_id} ORDER BY id DESC LIMIT 1"
            )

            try:
                rows = json.loads(result)
                if rows:
                    row = rows[0]
                    created = row.get("first_seen_at")
                    resolved = row.get("resolved_at")
                    status = row.get("status")

                    if created:
                        if ticket_created_at is None:
                            ticket_created_at = created
                            console.print(f"[cyan]Ticket detected (status: {status})[/cyan]")

                        if status == "resolved" and resolved:
                            elapsed = asyncio.get_running_loop().time() - start
                            console.print(f"[green]Ticket resolved after {elapsed:.1f}s[/green]")
                            return created, resolved
            except (json.JSONDecodeError, IndexError, KeyError):
                pass

            await asyncio.sleep(2.0)

        elapsed = asyncio.get_running_loop().time() - start
        console.print(
            f"[yellow]Timeout after {elapsed:.1f}s "
            f"(ticket_found={ticket_created_at is not None})[/yellow]"
        )
        return ticket_created_at, None

    async def update_ticket_variant(
        self,
        variant_config: VariantConfig,
        timeout_sec: float = 30.0,
    ) -> bool:
        """Update the most recent ticket with variant config.

        Waits for a ticket to exist before updating.

        Args:
            variant_config: Variant configuration to write
            timeout_sec: Maximum time to wait for a ticket

        Returns:
            True if update succeeded
        """
        start = asyncio.get_running_loop().time()

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            # Check if ticket exists
            result = await self._run_db_query("SELECT MAX(id) as max_id FROM tickets")
            try:
                rows = json.loads(result)
                if rows and rows[0].get("max_id") is not None:
                    # Ticket exists - update it
                    tools_json = json.dumps(variant_config.tools_config).replace("'", "\\'")
                    model = variant_config.model.replace("'", "\\'")
                    prompt = variant_config.system_prompt.replace("'", "\\'")

                    await self._run_db_execute(
                        f"UPDATE tickets SET "
                        f"variant_model = \\'{model}\\', "
                        f"variant_system_prompt = \\'{prompt}\\', "
                        f"variant_tools_config = \\'{tools_json}\\' "
                        f"WHERE id = (SELECT MAX(id) FROM tickets)"
                    )
                    return True
            except (json.JSONDecodeError, IndexError, KeyError):
                pass

            await asyncio.sleep(1.0)

        console.print("[yellow]Warning: Could not update ticket variant (no ticket created)[/yellow]")
        return False

    async def download_operator_db(self, local_path: Path) -> Path:
        """Download operator.db from the VM.

        The operator.db is on a Docker volume, so we first copy it
        to a host path, then download via SCP.

        Args:
            local_path: Local destination path for operator.db

        Returns:
            Path to the downloaded file
        """
        # Copy from Docker volume to host filesystem
        temp_remote_path = "/tmp/operator.db"
        await self.vm.run_command(
            f"docker cp {MONITOR_CONTAINER}:{OPERATOR_DB_PATH} {temp_remote_path}",
            timeout_sec=30.0,
        )

        # Download to local
        local_path.parent.mkdir(parents=True, exist_ok=True)
        await self.vm.download_file(temp_remote_path, str(local_path))

        console.print(f"[dim]Downloaded operator.db to {local_path}[/dim]")
        return local_path
