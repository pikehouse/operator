"""
Operator Core Library

Core abstractions and interfaces for the AI-powered operator for distributed systems.
This package provides the foundational components including:

- Subject Protocol: Interface for subject systems (TiKV, Kafka, etc.)
- Deployment Protocol: Interface for deployment targets (local, cloud, etc.)
- Data Types: Store, Region, StoreMetrics, ClusterMetrics
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
from operator_core.subject import Subject
from operator_core.types import (
    ClusterMetrics,
    Region,
    RegionId,
    Store,
    StoreId,
    StoreMetrics,
)
# Re-export InvariantViolation from operator_protocols for convenience
from operator_protocols import InvariantViolation

__all__ = [
    "__version__",
    # Subject Protocol
    "Subject",
    # Data Types
    "Store",
    "StoreId",
    "Region",
    "RegionId",
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
