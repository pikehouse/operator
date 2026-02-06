"""Base classes and protocols for cloud subjects."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CloudVM(Protocol):
    """Protocol for cloud VM management.

    Abstracts cloud provider details (GCP, AWS, etc.) so subjects
    can work with any provider implementing this interface.
    """

    @property
    def instance_id(self) -> str:
        """Return the cloud instance ID."""
        ...

    @property
    def external_ip(self) -> str:
        """Return the external IP address of the VM."""
        ...

    async def create(self) -> str:
        """Create the VM instance.

        Returns:
            Instance ID

        Raises:
            RuntimeError: If creation fails
        """
        ...

    async def delete(self) -> None:
        """Delete the VM instance.

        Should be idempotent - safe to call multiple times.
        """
        ...

    async def run_command(
        self,
        cmd: str,
        timeout_sec: float = 60.0,
    ) -> tuple[int, str, str]:
        """Run a command on the VM via SSH.

        Args:
            cmd: Shell command to execute
            timeout_sec: Maximum execution time

        Returns:
            Tuple of (exit_code, stdout, stderr)

        Raises:
            TimeoutError: If command exceeds timeout
            RuntimeError: If SSH connection fails
        """
        ...

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Upload a file to the VM.

        Args:
            local_path: Local file path
            remote_path: Remote destination path
        """
        ...

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Download a file from the VM.

        Args:
            remote_path: Remote file path
            local_path: Local destination path
        """
        ...


class CloudSubjectBase(ABC):
    """Base class for cloud-based eval subjects.

    Provides common functionality for subjects running on cloud VMs:
    - VM lifecycle management
    - Docker Compose orchestration via SSH
    - Chaos injection via SSH

    Subclasses must implement the cloud-specific VM management.
    """

    def __init__(
        self,
        vm: CloudVM,
        compose_file: str,
        project_name: str = "eval",
    ):
        """Initialize cloud subject.

        Args:
            vm: CloudVM instance for VM operations
            compose_file: Path to docker-compose.yaml on the VM
            project_name: Docker Compose project name
        """
        self.vm = vm
        self.compose_file = compose_file
        self.project_name = project_name
        self._created = False

    async def setup(self) -> None:
        """Set up the cloud subject.

        Creates the VM and uploads necessary files.
        """
        if not self._created:
            await self.vm.create()
            await self._upload_compose_files()
            self._created = True

    async def cleanup(self) -> None:
        """Clean up the cloud subject.

        Deletes the VM and all associated resources.
        """
        if self._created:
            await self.vm.delete()
            self._created = False

    @abstractmethod
    async def _upload_compose_files(self) -> None:
        """Upload Docker Compose files to the VM.

        Subclasses must implement this to upload their specific
        compose configuration.
        """
        ...

    async def reset(self) -> None:
        """Reset subject via docker-compose down/up on the VM."""
        if not self._created:
            await self.setup()

        # Down with volume cleanup
        await self.vm.run_command(
            f"cd {self.compose_file} && docker compose -p {self.project_name} down -v --remove-orphans"
        )

        # Up and wait
        await self.vm.run_command(
            f"cd {self.compose_file} && docker compose -p {self.project_name} up -d --wait"
        )

    async def wait_healthy(self, timeout_sec: float = 60.0) -> bool:
        """Wait for subject to be healthy on the VM.

        Default implementation polls docker-compose ps for healthy status.
        """
        if not self._created:
            return False

        start = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                exit_code, stdout, _ = await self.vm.run_command(
                    f"docker compose -p {self.project_name} ps --format json"
                )
                if exit_code == 0:
                    # Check all containers are running
                    import json
                    containers = json.loads(stdout) if stdout.strip() else []
                    if all(c.get("State") == "running" for c in containers):
                        return True
            except Exception as e:
                logger.debug(f"Health check error: {e}")

            await asyncio.sleep(2.0)

        return False

    async def capture_state(self) -> dict[str, Any]:
        """Capture current state from the VM."""
        # Default: return container states
        try:
            exit_code, stdout, _ = await self.vm.run_command(
                f"docker compose -p {self.project_name} ps --format json"
            )
            if exit_code == 0:
                import json
                containers = json.loads(stdout) if stdout.strip() else []
                return {"containers": containers}
        except Exception as e:
            return {"error": str(e)}
        return {}

    @abstractmethod
    def get_chaos_types(self) -> list[str]:
        """Return list of supported chaos types.

        Cloud subjects can support dangerous chaos types that are
        unsafe for local execution.
        """
        ...

    @abstractmethod
    async def inject_chaos(self, chaos_type: str, **params: Any) -> dict[str, Any]:
        """Inject chaos on the cloud VM."""
        ...

    @abstractmethod
    async def cleanup_chaos(self, chaos_metadata: dict[str, Any]) -> None:
        """Clean up chaos on the cloud VM."""
        ...
