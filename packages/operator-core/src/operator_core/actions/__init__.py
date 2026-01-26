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
- ValidationError: Exception for parameter validation failures
- validate_action_params: Pre-flight parameter validation
- AuditEvent: Audit log events for action lifecycle
- ActionAuditor: Audit logger for action lifecycle events
- SafetyController: Kill switch and observe-only mode
- SafetyMode: Enum for safety modes (OBSERVE, EXECUTE)
- ObserveOnlyError: Exception when execution blocked
- ActionExecutor: Orchestrator for proposal and execution flow

Exports:
    ActionStatus: Enum of action lifecycle states
    ActionType: Enum of action source types
    ActionProposal: Pydantic model for action proposals
    ActionRecord: Pydantic model for execution records
    ActionDefinition: Pydantic model for action metadata
    ParamDef: Pydantic model for parameter definitions
    ActionRegistry: Class for runtime action discovery
    ValidationError: Exception for validation failures
    validate_action_params: Parameter validation function
    AuditEvent: Pydantic model for audit events
    ActionAuditor: Audit logger class
    SafetyController: Kill switch and mode management
    SafetyMode: Safety mode enum
    ObserveOnlyError: Observe mode exception
    ActionExecutor: Action proposal and execution orchestrator
"""

from operator_core.actions.audit import (
    ActionAuditor,
    AuditEvent,
)
from operator_core.actions.executor import ActionExecutor
from operator_core.actions.registry import (
    ActionDefinition,
    ActionRegistry,
    ParamDef,
)
from operator_core.actions.safety import (
    ObserveOnlyError,
    SafetyController,
    SafetyMode,
)
from operator_core.actions.types import (
    ActionProposal,
    ActionRecord,
    ActionStatus,
    ActionType,
)
from operator_core.actions.validation import (
    ValidationError,
    validate_action_params,
)

__all__ = [
    "ActionAuditor",
    "ActionDefinition",
    "ActionExecutor",
    "ActionProposal",
    "ActionRecord",
    "ActionRegistry",
    "ActionStatus",
    "ActionType",
    "AuditEvent",
    "ObserveOnlyError",
    "ParamDef",
    "SafetyController",
    "SafetyMode",
    "ValidationError",
    "validate_action_params",
]
