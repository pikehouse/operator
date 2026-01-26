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
- ApprovalRequiredError: Exception when approval is required but not granted
- RetryConfig: Configuration for exponential backoff retry behavior
- get_general_tools: General tools available beyond subject actions
- execute_tool: Execute a general tool by name
- TOOL_EXECUTORS: Map of tool names to executor functions

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
    ApprovalRequiredError: Exception for unapproved execution attempts
    RetryConfig: Dataclass for retry configuration with exponential backoff
    get_general_tools: Function returning general tool definitions
    execute_tool: Function to execute a general tool
    TOOL_EXECUTORS: Dict mapping tool names to executor functions
"""

from operator_core.actions.audit import (
    ActionAuditor,
    AuditEvent,
)
from operator_core.actions.executor import ActionExecutor, ApprovalRequiredError
from operator_core.actions.registry import (
    ActionDefinition,
    ActionRegistry,
    ParamDef,
)
from operator_core.actions.retry import RetryConfig
from operator_core.actions.safety import (
    ObserveOnlyError,
    SafetyController,
    SafetyMode,
)
from operator_core.actions.tools import (
    TOOL_EXECUTORS,
    execute_tool,
    get_general_tools,
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
    "ApprovalRequiredError",
    "ActionProposal",
    "ActionRecord",
    "ActionRegistry",
    "ActionStatus",
    "ActionType",
    "AuditEvent",
    "ObserveOnlyError",
    "ParamDef",
    "RetryConfig",
    "SafetyController",
    "SafetyMode",
    "TOOL_EXECUTORS",
    "ValidationError",
    "execute_tool",
    "get_general_tools",
    "validate_action_params",
]
