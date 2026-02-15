"""Remote operator management for cloud eval trials.

Manages operator (monitor + agent) Docker containers on GCP VMs via SSH.
Mirrors the local OperatorProcesses class but works over SSH using the
CloudVM protocol.

The operator runs as Docker containers on the VM with:
- Host networking (for PD access at localhost:2379)
- Docker socket mount (for agent's shell tool)
- Shared data volume (for operator.db)

Container orchestration uses docker-compose (declarative YAML) rather than
imperative `docker run` commands. The compose file is generated at runtime
and uploaded to the VM. Startup ordering is handled via healthchecks and
depends_on rather than polling loops.
"""

import asyncio
import json
import logging
import shlex
import tempfile
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from eval.types import VariantConfig

logger = logging.getLogger(__name__)
console = Console()

# Container names on the VM
MONITOR_CONTAINER = "operator-monitor"
AGENT_CONTAINER = "operator-agent"
DATA_VOLUME = "operator-data"
OPERATOR_DB_PATH = "/data/operator.db"

# Compose config
COMPOSE_FILE_PATH = "/tmp/operator-compose.yaml"
COMPOSE_PROJECT = "operator"
# COS VMs have compose installed as a CLI plugin via install_compose_plugin()
COMPOSE_CMD = "docker --config /var/lib/toolbox/docker-config compose"


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

    def _build_compose_config(self) -> dict:
        """Build a docker-compose config dict for monitor + agent services.

        Returns a Python dict that will be serialized to YAML and uploaded
        to the VM. Both services use host networking, mount the docker socket
        and shared data volume. The monitor has a healthcheck that the agent
        depends on via `depends_on: condition: service_healthy`.
        """
        # Shared environment for both services
        shared_env: dict[str, str] = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            **self.extra_env,
        }

        # Shared volume mounts for both services
        shared_volumes = [
            "/var/run/docker.sock:/var/run/docker.sock",
            f"{DATA_VOLUME}:/data",
        ]
        if self.workspace_volume_mount:
            shared_volumes.append(self.workspace_volume_mount)

        # Build monitor command
        # Pass all 3 PD endpoints for failover (enables FailoverPDClient)
        pd_endpoints = "http://localhost:2379,http://localhost:2381,http://localhost:2382"
        monitor_cmd = (
            f"uv run operator monitor run"
            f" --subject {self.subject_name}"
            f" --pd {pd_endpoints}"
            f" --db {OPERATOR_DB_PATH}"
            f" --interval 5"
        )
        if self.subject_context_extra:
            monitor_cmd += f" --subject-context-extra {shlex.quote(self.subject_context_extra)}"

        # Monitor service — runs as root, has healthcheck
        monitor_service: dict[str, Any] = {
            "image": self.operator_image,
            "container_name": MONITOR_CONTAINER,
            "network_mode": "host",
            "user": "root",
            "volumes": list(shared_volumes),
            "environment": shared_env,
            "command": monitor_cmd,
            "healthcheck": {
                "test": ["CMD", "test", "-f", OPERATOR_DB_PATH],
                "interval": "2s",
                "timeout": "2s",
                "retries": 15,
                "start_period": "3s",
            },
        }

        # Agent gets extra env for git config + identity
        agent_env: dict[str, str] = {
            **shared_env,
            "HOME": "/home/appuser",
            # Git safe.directory config via env vars
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "/var/lib/workspace",
            # Git identity via env vars (no .gitconfig file needed)
            "GIT_AUTHOR_NAME": "eval",
            "GIT_AUTHOR_EMAIL": "eval@operator",
            "GIT_COMMITTER_NAME": "eval",
            "GIT_COMMITTER_EMAIL": "eval@operator",
        }

        # Agent volumes: shared + extra mounts (compose dir, toolbox, etc.)
        agent_volumes = list(shared_volumes) + list(self.extra_volume_mounts)

        # Agent service — runs as appuser, depends on healthy monitor
        agent_service: dict[str, Any] = {
            "image": self.operator_image,
            "container_name": AGENT_CONTAINER,
            "network_mode": "host",
            "volumes": agent_volumes,
            "environment": agent_env,
            "command": f"uv run operator agent start --db {OPERATOR_DB_PATH}",
            "depends_on": {
                "monitor": {"condition": "service_healthy"},
            },
        }

        return {
            "services": {
                "monitor": monitor_service,
                "agent": agent_service,
            },
            "volumes": {
                DATA_VOLUME: {"external": True},
            },
        }

    async def _upload_compose_file(self) -> None:
        """Generate and upload the compose YAML to the VM."""
        config = self._build_compose_config()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f, default_flow_style=False)
            local_path = f.name
        try:
            await self.vm.upload_file(local_path, COMPOSE_FILE_PATH)
        finally:
            Path(local_path).unlink(missing_ok=True)

    def _compose(self, subcmd: str) -> str:
        """Build a full compose command string with project and file flags."""
        return (
            f"{COMPOSE_CMD}"
            f" -p {COMPOSE_PROJECT}"
            f" -f {COMPOSE_FILE_PATH}"
            f" {subcmd}"
        )

    async def start(self) -> None:
        """Pull operator image and start monitor + agent via docker-compose.

        Generates a compose YAML, uploads it to the VM, then uses
        `compose up -d --wait` to start both services. The monitor's
        healthcheck (test -f operator.db) gates agent startup via
        depends_on, eliminating the need for manual polling loops.
        """
        console.print("[bold blue]Starting remote operator...[/bold blue]")

        # Authenticate with Artifact Registry (COS has docker-credential-gcr)
        await self.vm.run_command(
            "docker-credential-gcr configure-docker --registries us-central1-docker.pkg.dev 2>/dev/null || true",
            timeout_sec=30.0,
        )

        # Clean data volume from previous trials to prevent stale tickets
        await self.vm.run_command(f"docker volume rm {DATA_VOLUME} 2>/dev/null || true")
        await self.vm.run_command(f"docker volume create {DATA_VOLUME}")

        # Make Docker socket accessible to non-root agent user.
        # COS uses GID 412 for the socket, which doesn't match the container's
        # docker group (999). Making it world-accessible is safe since the VM
        # is single-purpose and ephemeral.
        await self.vm.run_command(
            "sudo chmod 666 /var/run/docker.sock 2>/dev/null || true",
            timeout_sec=5.0,
        )

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

        # Upload compose file
        await self._upload_compose_file()

        # Pull image via compose (retry once on Docker socket errors)
        console.print(f"[dim]Pulling operator image: {self.operator_image}[/dim]")
        for attempt in range(2):
            exit_code, stdout, stderr = await self.vm.run_command(
                self._compose("pull"),
                timeout_sec=300.0,
            )
            if exit_code == 0:
                break
            # Check if image was actually pulled despite the error
            # (Docker socket reset can cause non-zero exit after successful pull)
            check_rc, check_out, _ = await self.vm.run_command(
                f"docker image inspect {self.operator_image} --format '{{{{.Id}}}}'",
                timeout_sec=15.0,
            )
            if check_rc == 0 and check_out.strip():
                console.print(f"[dim]Image pulled despite exit code {exit_code}[/dim]")
                break
            if attempt == 0:
                console.print(f"[yellow]Pull attempt 1 failed, retrying...[/yellow]")
                await asyncio.sleep(5)
            else:
                raise RuntimeError(f"Failed to pull operator image: {stderr}")

        # Start services — --wait blocks until all healthchecks pass.
        # The monitor's healthcheck confirms operator.db exists, and the
        # agent's depends_on ensures it starts only after the monitor is healthy.
        console.print(f"[blue]Starting operator monitor ({self.subject_name}, 5s interval) + agent...[/blue]")
        exit_code, stdout, stderr = await self.vm.run_command(
            self._compose("up -d --wait"),
            timeout_sec=120.0,
        )
        if exit_code != 0:
            # Capture logs and clean up before raising
            _, logs, _ = await self.vm.run_command(
                self._compose("logs"), timeout_sec=15.0
            )
            await self.vm.run_command(
                self._compose("down"), timeout_sec=15.0
            )
            raise RuntimeError(f"Failed to start operator: {stderr}\nLogs:\n{logs}")

        # Make data volume writable by the non-root agent user
        await self.vm.run_command(
            f"docker exec {MONITOR_CONTAINER} chmod -R 777 /data",
            timeout_sec=30.0,
        )

        # Defense-in-depth: verify agent didn't crash shortly after starting
        await asyncio.sleep(3)
        exit_code, stdout, _ = await self.vm.run_command(
            f"docker inspect -f '{{{{.State.Running}}}}' {AGENT_CONTAINER} 2>/dev/null",
            timeout_sec=30.0,
        )
        if exit_code != 0 or "true" not in stdout.lower():
            _, agent_logs, _ = await self.vm.run_command(
                self._compose("logs agent"), timeout_sec=10.0
            )
            console.print("[red]Agent container crashed on startup![/red]")
            console.print(f"[red]Agent logs:\n{agent_logs}[/red]")
            await self.vm.run_command(
                self._compose("down"), timeout_sec=15.0
            )
            raise RuntimeError(f"Agent container crashed on startup: {agent_logs}")

        self._started = True
        console.print("[green]Remote operator started[/green]")

    async def restart_operator(self) -> None:
        """Restart both monitor and agent containers to clear all in-memory state.

        After force-resolving startup tickets:
        - Monitor restart clears the invariant checker's _first_seen dict,
          preventing immediate re-creation of tickets for lingering violations.
        - Agent restart kills any in-progress Claude SDK session from startup
          ticket processing (force-resolve only changes DB, not in-flight work).

        Uses compose restart which preserves volumes and network config.
        """
        exit_code, _, stderr = await self.vm.run_command(
            self._compose("restart"),
            timeout_sec=60.0,
        )
        if exit_code != 0:
            console.print(f"[yellow]Operator restart failed: {stderr}[/yellow]")
            return

        # Wait for both containers to be running
        await asyncio.sleep(5)
        for container in (MONITOR_CONTAINER, AGENT_CONTAINER):
            exit_code, stdout, _ = await self.vm.run_command(
                f"docker inspect -f '{{{{.State.Running}}}}' {container} 2>/dev/null",
                timeout_sec=10.0,
            )
            if exit_code != 0 or "true" not in stdout.lower():
                console.print(f"[yellow]{container} may not have restarted cleanly[/yellow]")

    async def stop(self) -> None:
        """Stop and remove operator containers via compose down."""
        if not self._started:
            return

        console.print("[blue]Stopping remote operator...[/blue]")

        # Capture logs before teardown for debugging
        _, logs, _ = await self.vm.run_command(
            self._compose("logs --tail=30"), timeout_sec=15.0
        )
        if logs.strip():
            console.print(f"[dim]operator logs (last 30 lines):\n{logs}[/dim]")

        # Stops + removes containers; preserves the data volume
        await self.vm.run_command(
            self._compose("down"), timeout_sec=15.0
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

        try:
            exit_code, stdout, stderr = await self.vm.run_command(
                f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
                timeout_sec=30.0,
            )
        except (TimeoutError, Exception) as e:
            logger.debug(f"DB query timed out or failed: {e}")
            return "[]"

        if exit_code != 0:
            logger.debug(f"DB query failed: {stderr}")
            return "[]"

        return stdout.strip()

    async def _run_db_execute(self, statement: str, params: list | None = None) -> int:
        """Execute a SQLite write statement on operator.db via SSH.

        Uses base64-encoded JSON to avoid shell/SQL escaping issues.

        Args:
            statement: SQL statement with ? placeholders for params
            params: Optional list of parameter values for ? placeholders

        Returns:
            Number of rows affected
        """
        import base64

        payload = {
            "sql": statement,
            "params": params or [],
            "db_path": OPERATOR_DB_PATH,
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

        python_script = (
            "import sqlite3, json, base64; "
            f"p = json.loads(base64.b64decode('{payload_b64}')); "
            "conn = sqlite3.connect(p['db_path']); "
            "cur = conn.execute(p['sql'], p['params']); "
            "conn.commit(); "
            "print(cur.rowcount); "
            "conn.close()"
        )

        try:
            exit_code, stdout, stderr = await self.vm.run_command(
                f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
                timeout_sec=30.0,
            )
        except (TimeoutError, Exception) as e:
            logger.debug(f"DB execute timed out or failed: {e}")
            return 0

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

        try:
            exit_code, stdout, stderr = await self.vm.run_command(
                f'docker exec {MONITOR_CONTAINER} python3 -c "{python_script}"',
                timeout_sec=30.0,
            )
        except (TimeoutError, Exception) as e:
            logger.warning(f"inject_ticket timed out: {e}")
            console.print(f"[yellow]inject_ticket timed out: {e}[/yellow]")
            return

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
            "UPDATE tickets SET status = 'resolved', "
            "resolved_at = datetime('now'), held = 0 "
            "WHERE status != 'resolved'"
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
                f"SELECT created_at, resolved_at, status FROM tickets "
                f"WHERE id > {min_ticket_id} ORDER BY id DESC LIMIT 1"
            )

            try:
                rows = json.loads(result)
                if rows:
                    row = rows[0]
                    created = row.get("created_at")
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
                    tools_json = json.dumps(variant_config.tools_config)

                    await self._run_db_execute(
                        "UPDATE tickets SET "
                        "variant_model = ?, "
                        "variant_system_prompt = ?, "
                        "variant_tools_config = ? "
                        "WHERE id = (SELECT MAX(id) FROM tickets)",
                        [variant_config.model, variant_config.system_prompt, tools_json],
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
