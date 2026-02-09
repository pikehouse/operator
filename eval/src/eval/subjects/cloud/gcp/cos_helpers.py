"""Shared helpers for Container-Optimized OS (COS) VMs.

COS has specific constraints:
- /home and /tmp have noexec (no binaries can run from there)
- Docker Compose is not pre-installed
- docker-credential-gcr is available but gcloud CLI is not
- /var/lib/toolbox is exec-enabled and writable via sudo
"""

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class _VM(Protocol):
    """Minimal VM protocol for COS helpers."""

    async def run_command(
        self, cmd: str, timeout_sec: float = 60.0
    ) -> tuple[int, str, str]: ...

    async def upload_file(self, local_path: str, remote_path: str) -> None: ...


async def install_compose_plugin(vm: _VM) -> None:
    """Install Docker Compose plugin on a COS VM.

    Downloads the compose binary to /tmp (noexec), then copies to
    /var/lib/toolbox (exec-enabled) as a Docker CLI plugin.
    Use ``docker --config /var/lib/toolbox/docker-config compose``
    to invoke.
    """
    await vm.run_command(
        "curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 "
        "-o /tmp/docker-compose-download && "
        "sudo mkdir -p /var/lib/toolbox/docker-config/cli-plugins && "
        "sudo cp /tmp/docker-compose-download /var/lib/toolbox/docker-config/cli-plugins/docker-compose && "
        "sudo chmod +x /var/lib/toolbox/docker-config/cli-plugins/docker-compose && "
        "rm -f /tmp/docker-compose-download",
        timeout_sec=60.0,
    )


async def configure_artifact_registry(vm: _VM) -> None:
    """Configure Artifact Registry auth on a COS VM.

    Uses docker-credential-gcr (pre-installed on COS) to configure
    both the default Docker config and the toolbox Docker config
    used by the compose plugin.
    """
    await vm.run_command(
        "docker-credential-gcr configure-docker --registries=us-central1-docker.pkg.dev",
        timeout_sec=30.0,
    )
    await vm.run_command(
        "sudo cp ~/.docker/config.json /var/lib/toolbox/docker-config/config.json && "
        "sudo chmod 644 /var/lib/toolbox/docker-config/config.json",
        timeout_sec=10.0,
    )


async def upload_directory(vm: _VM, local_dir: str, remote_dir: str) -> None:
    """Upload a local directory to a remote VM via tar-over-SSH.

    Creates the remote directory and extracts a tar archive of the
    local directory contents into it. Handles the case where GCPVM
    only supports single-file uploads by using tar piping.

    Args:
        vm: VM instance with run_command and upload_file methods
        local_dir: Local directory path to upload
        remote_dir: Remote directory path to create and populate
    """
    import os
    import subprocess
    import tempfile

    # Create tar of local directory
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tar_path = tmp.name

    try:
        subprocess.run(
            ["tar", "-czf", tar_path, "-C", local_dir, "."],
            check=True,
            capture_output=True,
        )

        # Create remote directory
        await vm.run_command(f"mkdir -p {remote_dir}")

        # Upload tar file
        remote_tar = f"/tmp/upload-{os.path.basename(tar_path)}"
        await vm.upload_file(tar_path, remote_tar)

        # Extract on remote
        await vm.run_command(
            f"tar -xzf {remote_tar} -C {remote_dir} && rm -f {remote_tar}",
            timeout_sec=30.0,
        )
    finally:
        os.unlink(tar_path)
