"""
Operator Core Library

Core abstractions and interfaces for the AI-powered operator for distributed systems.
This package provides the foundational components including:

- Subject Protocol: Interface for subject systems (TiKV, Kafka, etc.)
- Deployment Protocol: Interface for deployment targets (local, cloud, etc.)
- CLI infrastructure: Typer-based command structure
"""

__version__ = "0.1.0"

# Re-export public types for convenient imports
from operator_core.deploy import (
    DeploymentStatus,
    DeploymentTarget,
    LocalDeployment,
    ServiceStatus,
    create_local_deployment,
)

__all__ = [
    "__version__",
    "DeploymentTarget",
    "LocalDeployment",
    "ServiceStatus",
    "DeploymentStatus",
    "create_local_deployment",
]
