"""
Operator Core Library

Core abstractions and interfaces for the AI-powered operator for distributed systems.
This package provides the foundational components including:

- Deployment Protocol: Interface for deployment targets (local, cloud, etc.)
- Data Types: Store, StoreMetrics, ClusterMetrics (re-exported from operator_protocols)
- CLI infrastructure: Typer-based command structure
- Monitor loop: Continuous invariant checking
- Agent lab: Autonomous agent with shell access
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
from operator_core.types import (
    ClusterMetrics,
    Store,
    StoreId,
    StoreMetrics,
)
# Re-export InvariantViolation from operator_protocols for convenience
from operator_protocols import InvariantViolation

__all__ = [
    "__version__",
    # Data Types (re-exported from operator_protocols)
    "Store",
    "StoreId",
    "StoreMetrics",
    "ClusterMetrics",
    # Invariant types (from operator_protocols)
    "InvariantViolation",
    # Deployment
    "DeploymentTarget",
    "LocalDeployment",
    "ServiceStatus",
    "DeploymentStatus",
    "create_local_deployment",
]
