"""GCP Compute Engine VM management."""

import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_ssh_keys() -> str:
    """Ensure SSH keys exist for gcloud compute ssh. Returns public key content."""
    ssh_dir = Path.home() / ".ssh"
    key_path = ssh_dir / "google_compute_engine"

    if not key_path.exists():
        ssh_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-b", "2048", "-f", str(key_path), "-N", "", "-q"],
            check=True,
        )
        logger.info(f"Generated SSH key pair at {key_path}")

    return key_path.with_suffix(".pub").read_text().strip()


class GCPVM:
    """GCP Compute Engine VM for eval execution.

    Uses gcloud CLI for VM operations. Requires:
    - gcloud CLI installed and configured
    - Compute Engine API enabled
    - Proper IAM permissions

    VMs use Container-Optimized OS (COS) for Docker support.
    """

    def __init__(
        self,
        project: str | None = None,
        zone: str = "us-central1-a",
        machine_type: str = "e2-standard-4",
        name_prefix: str = "eval-worker",
        disk_size_gb: int = 50,
    ):
        """Initialize GCP VM configuration.

        Args:
            project: GCP project ID (uses gcloud default if not specified)
            zone: GCP zone for the VM
            machine_type: VM machine type
            name_prefix: Prefix for VM name (UUID suffix added)
            disk_size_gb: Boot disk size in GB
        """
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.zone = zone
        self.machine_type = machine_type
        self.name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
        self.disk_size_gb = disk_size_gb
        self._instance_id: str | None = None
        self._external_ip: str | None = None

    @property
    def instance_id(self) -> str:
        """Return the instance name (ID in GCP)."""
        if not self._instance_id:
            raise RuntimeError("VM not created yet")
        return self._instance_id

    @property
    def external_ip(self) -> str:
        """Return the external IP address."""
        if not self._external_ip:
            raise RuntimeError("VM not created yet or has no external IP")
        return self._external_ip

    async def create(self) -> str:
        """Create the VM instance.

        Uses Container-Optimized OS with Docker pre-installed.

        Returns:
            Instance name

        Raises:
            RuntimeError: If creation fails
        """
        logger.info(f"Creating GCP VM: {self.name}")

        # Ensure SSH keys exist and get the public key
        pub_key = _ensure_ssh_keys()
        # Format: "username:ssh-rsa AAAA... comment"
        # COS disables root SSH, so use a regular username
        self._ssh_user = os.environ.get("USER", "eval_worker")
        if self._ssh_user == "root":
            self._ssh_user = "eval_worker"
        ssh_metadata = f"{self._ssh_user}:{pub_key}"

        # Build gcloud command
        cmd = [
            "gcloud", "compute", "instances", "create", self.name,
            f"--zone={self.zone}",
            f"--machine-type={self.machine_type}",
            "--image-family=cos-stable",
            "--image-project=cos-cloud",
            f"--boot-disk-size={self.disk_size_gb}GB",
            "--scopes=cloud-platform",
            f"--metadata=ssh-keys={ssh_metadata}",
            "--format=json",
        ]
        if self.project:
            cmd.append(f"--project={self.project}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to create VM: {stderr.decode()}"
            )

        import json
        result = json.loads(stdout.decode())
        if result:
            self._instance_id = self.name
            # Extract external IP from network interfaces
            network_interfaces = result[0].get("networkInterfaces", [])
            if network_interfaces:
                access_configs = network_interfaces[0].get("accessConfigs", [])
                if access_configs:
                    self._external_ip = access_configs[0].get("natIP")

        # Wait for SSH to be ready
        await self._wait_for_ssh()

        logger.info(f"VM created: {self.name} ({self._external_ip})")
        return self.name

    async def delete(self) -> None:
        """Delete the VM instance."""
        if not self._instance_id:
            return  # Nothing to delete

        logger.info(f"Deleting GCP VM: {self.name}")

        cmd = [
            "gcloud", "compute", "instances", "delete", self.name,
            f"--zone={self.zone}",
            "--quiet",
        ]
        if self.project:
            cmd.append(f"--project={self.project}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        self._instance_id = None
        self._external_ip = None

    async def run_command(
        self,
        cmd: str,
        timeout_sec: float = 60.0,
    ) -> tuple[int, str, str]:
        """Run a command on the VM via SSH.

        Uses gcloud compute ssh for connection.

        Args:
            cmd: Shell command to execute
            timeout_sec: Maximum execution time

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        if not self._instance_id:
            raise RuntimeError("VM not created yet")

        # Use user@instance format to ensure correct SSH username
        ssh_target = self.name
        if hasattr(self, "_ssh_user") and self._ssh_user:
            ssh_target = f"{self._ssh_user}@{self.name}"

        ssh_cmd = [
            "gcloud", "compute", "ssh", ssh_target,
            f"--zone={self.zone}",
            "--command", cmd,
            "--strict-host-key-checking=no",
        ]
        if self.project:
            ssh_cmd.append(f"--project={self.project}")

        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_sec,
            )
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout_sec}s")

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Upload a file to the VM using gcloud scp."""
        if not self._instance_id:
            raise RuntimeError("VM not created yet")

        scp_target = self.name
        if hasattr(self, "_ssh_user") and self._ssh_user:
            scp_target = f"{self._ssh_user}@{self.name}"

        cmd = [
            "gcloud", "compute", "scp",
            local_path,
            f"{scp_target}:{remote_path}",
            f"--zone={self.zone}",
            "--strict-host-key-checking=no",
        ]
        if self.project:
            cmd.append(f"--project={self.project}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to upload file: {stderr.decode()}")

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Download a file from the VM using gcloud scp."""
        if not self._instance_id:
            raise RuntimeError("VM not created yet")

        scp_target = self.name
        if hasattr(self, "_ssh_user") and self._ssh_user:
            scp_target = f"{self._ssh_user}@{self.name}"

        cmd = [
            "gcloud", "compute", "scp",
            f"{scp_target}:{remote_path}",
            local_path,
            f"--zone={self.zone}",
            "--strict-host-key-checking=no",
        ]
        if self.project:
            cmd.append(f"--project={self.project}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to download file: {stderr.decode()}")

    async def _wait_for_ssh(self, timeout_sec: float = 120.0) -> None:
        """Wait for SSH to be ready on the VM."""
        start = asyncio.get_running_loop().time()

        while (asyncio.get_running_loop().time() - start) < timeout_sec:
            try:
                exit_code, _, _ = await self.run_command("echo ready", timeout_sec=10.0)
                if exit_code == 0:
                    return
            except Exception:
                pass
            await asyncio.sleep(5.0)

        raise RuntimeError(f"SSH not ready after {timeout_sec}s")
