"""
Deployment abstractions for managing distributed system infrastructure.

This module provides:
- DeploymentTarget Protocol: Interface for deployment targets (local, AWS, etc.)
- LocalDeployment: Docker Compose-based local deployment implementation
- Status types: ServiceStatus and DeploymentStatus for structured status info
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from python_on_whales import DockerClient
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn


@dataclass
class ServiceStatus:
    """Status information for a single service."""

    name: str
    running: bool
    health: str  # "healthy", "unhealthy", "starting", "none"
    ports: list[str]  # "host:container" format


@dataclass
class DeploymentStatus:
    """Status information for an entire deployment."""

    services: list[ServiceStatus]
    all_healthy: bool


class DeploymentTarget(Protocol):
    """Interface for deployment targets (local, AWS, etc.).

    Implementations of this protocol provide the ability to manage
    distributed system deployments across different environments.
    """

    def up(self, wait: bool = True) -> None:
        """Start the deployment.

        Args:
            wait: If True, block until all services are healthy.
        """
        ...

    def down(self, remove_volumes: bool = False) -> None:
        """Stop the deployment.

        Args:
            remove_volumes: If True, also remove persistent volumes.
        """
        ...

    def status(self) -> DeploymentStatus:
        """Get status of all services.

        Returns:
            DeploymentStatus with information about all services.
        """
        ...

    def logs(
        self, service: str | None = None, follow: bool = False, tail: int = 100
    ) -> None:
        """Show logs from services.

        Args:
            service: Specific service name, or None for all services.
            follow: If True, stream logs continuously.
            tail: Number of lines to show from end of logs.
        """
        ...

    def restart(self, service: str) -> None:
        """Restart a specific service.

        Args:
            service: Name of the service to restart.
        """
        ...


class LocalDeployment:
    """Docker Compose-based local deployment.

    Uses python-on-whales to control Docker Compose for local development
    and testing of distributed systems.
    """

    def __init__(self, compose_file: Path, project_name: str | None = None):
        """Initialize a local deployment.

        Args:
            compose_file: Path to the docker-compose.yaml file.
            project_name: Optional project name for Docker Compose.
        """
        self.compose_file = compose_file
        self.docker = DockerClient(compose_files=[compose_file])
        self.console = Console()
        self.project_name = project_name

    def up(self, wait: bool = True) -> None:
        """Start the deployment.

        Args:
            wait: If True, block until all services are healthy.
        """
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("Starting containers...", total=None)
            self.docker.compose.up(detach=True, wait=wait)
            progress.update(task, description="[green]Cluster ready!")

        # Print service endpoints after startup
        self._print_endpoints()

    def down(self, remove_volumes: bool = False) -> None:
        """Stop the deployment.

        Args:
            remove_volumes: If True, also remove persistent volumes.
        """
        self.docker.compose.down(volumes=remove_volumes)
        self.console.print("[yellow]Cluster stopped[/yellow]")

    def status(self) -> DeploymentStatus:
        """Get status of all services.

        Returns:
            DeploymentStatus with information about all services.
        """
        containers = self.docker.compose.ps()
        services = []
        for c in containers:
            # Get health status if available
            health = "none"
            if hasattr(c, "state") and hasattr(c.state, "health"):
                health = c.state.health.status if c.state.health else "none"

            # Get port mappings
            ports = []
            if c.network_settings and c.network_settings.ports:
                for container_port, host_bindings in c.network_settings.ports.items():
                    if host_bindings:
                        for binding in host_bindings:
                            # binding is a dict with HostIp and HostPort keys
                            host_port = binding.get("HostPort") if isinstance(binding, dict) else binding.host_port
                            ports.append(f"{host_port}:{container_port}")

            services.append(
                ServiceStatus(
                    name=c.name,
                    running=c.state.running if hasattr(c, "state") else False,
                    health=health,
                    ports=ports,
                )
            )

        all_healthy = all(s.running for s in services)
        return DeploymentStatus(services=services, all_healthy=all_healthy)

    def logs(
        self, service: str | None = None, follow: bool = False, tail: int = 100
    ) -> None:
        """Show logs from services.

        Args:
            service: Specific service name, or None for all services.
            follow: If True, stream logs continuously.
            tail: Number of lines to show from end of logs.
        """
        if service:
            self.docker.compose.logs(services=[service], follow=follow, tail=str(tail))
        else:
            self.docker.compose.logs(follow=follow, tail=str(tail))

    def restart(self, service: str) -> None:
        """Restart a specific service.

        Args:
            service: Name of the service to restart.
        """
        self.docker.compose.restart(services=[service])
        self.console.print(f"[green]Restarted {service}[/green]")

    def _print_endpoints(self) -> None:
        """Print service endpoints after successful startup."""
        self.console.print("\n[bold]Services:[/bold]")
        status = self.status()
        for svc in status.services:
            if svc.ports:
                for port in svc.ports:
                    host_port = port.split(":")[0]
                    self.console.print(f"  {svc.name}: http://localhost:{host_port}")


def create_local_deployment(
    subject: str, base_path: Path | None = None
) -> LocalDeployment:
    """Create a LocalDeployment for a subject.

    Args:
        subject: Subject name (e.g., "tikv")
        base_path: Project root path. If None, uses current directory.

    Returns:
        LocalDeployment configured for the subject's compose file.

    Raises:
        FileNotFoundError: If the compose file doesn't exist.
    """
    if base_path is None:
        base_path = Path.cwd()

    compose_file = base_path / "subjects" / subject / "docker-compose.yaml"
    if not compose_file.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_file}")

    return LocalDeployment(compose_file, project_name=f"operator-{subject}")
