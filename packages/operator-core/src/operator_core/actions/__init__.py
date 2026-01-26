"""
Actions module for the agent execution framework.

This module provides the data structures for action management:
- ActionStatus: Lifecycle states for actions
- ActionType: Source types for actions
- ActionProposal: Proposed actions awaiting validation/execution
- ActionRecord: Execution records for completed actions
- ActionDefinition: Action metadata for discovery
- ParamDef: Parameter definitions for actions
- ActionRegistry: Runtime action discovery from subjects
- AuditEvent: Audit log events for action lifecycle
- ActionAuditor: Audit logger for action lifecycle events

Exports:
    ActionStatus: Enum of action lifecycle states
    ActionType: Enum of action source types
    ActionProposal: Pydantic model for action proposals
    ActionRecord: Pydantic model for execution records
    ActionDefinition: Pydantic model for action metadata
    ParamDef: Pydantic model for parameter definitions
    ActionRegistry: Class for runtime action discovery
    AuditEvent: Pydantic model for audit events
    ActionAuditor: Audit logger class
"""

from operator_core.actions.audit import (
    ActionAuditor,
    AuditEvent,
)
from operator_core.actions.registry import (
    ActionDefinition,
    ActionRegistry,
    ParamDef,
)
from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)

__all__ = [
    "ActionAuditor",
    "ActionDefinition",
    "ActionProposal",
    "ActionRecord",
    "ActionRegistry",
    "ActionStatus",
    "ActionType",
    "AuditEvent",
    "ParamDef",
]
