"""
Action registry for runtime action discovery.

This module provides:
- ParamDef: Parameter definition for action arguments
- ActionDefinition: Complete action specification
- ActionRegistry: Discovers actions from subjects at runtime

The registry enables the agent to discover available actions without
hard-coding subject-specific logic in the core.

Example:
    ```python
    registry = ActionRegistry(subject)
    actions = registry.get_definitions()
    for action in actions:
        print(f"{action.name}: {action.description}")
    ```
"""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from operator_core.actions.types import ActionType

if TYPE_CHECKING:
    from operator_core.subject import Subject


class ParamDef(BaseModel):
    """
    Parameter definition for an action argument.

    Attributes:
        type: Python type name ("int", "str", "float", "bool")
        description: What this parameter represents
        required: Whether parameter must be provided
        default: Default value if not required
    """

    type: str = Field(..., description="Python type name (int, str, float, bool)")
    description: str = Field(..., description="What this parameter represents")
    required: bool = Field(default=True, description="Whether parameter must be provided")
    default: Any = Field(default=None, description="Default value if not required")


class ActionDefinition(BaseModel):
    """
    Complete definition of an action available from a subject or as a general tool.

    ActionDefinitions are provided by subjects and describe what actions
    can be performed, their parameters, and risk level. General tools also
    use ActionDefinition with ActionType.TOOL.

    Attributes:
        name: Action name matching Subject method (e.g., "transfer_leader")
        description: Human-readable description for prompts
        parameters: Parameter definitions keyed by parameter name
        action_type: Source type (SUBJECT for subject methods, TOOL for general tools)
        risk_level: "low", "medium", "high" for future approval tiers
        requires_approval: Whether action needs human approval (default False per APR-01)

    Example:
        ```python
        ActionDefinition(
            name="transfer_leader",
            description="Transfer region leadership to another store",
            parameters={
                "region_id": ParamDef(type="int", description="Region to transfer"),
                "to_store_id": ParamDef(type="str", description="Target store ID"),
            },
            action_type=ActionType.SUBJECT,
            risk_level="medium",
            requires_approval=False,
        )
        ```
    """

    name: str = Field(..., description="Action name matching Subject method")
    description: str = Field(..., description="Human-readable description")
    parameters: dict[str, ParamDef] = Field(
        default_factory=dict, description="Parameter definitions keyed by name"
    )
    action_type: ActionType = Field(
        default=ActionType.SUBJECT,
        description="Source type: subject method or general tool",
    )
    risk_level: str = Field(
        default="low", description="Risk level: low, medium, high"
    )
    requires_approval: bool = Field(
        default=False, description="Whether action needs human approval"
    )


class ActionRegistry:
    """
    Registry for discovering actions from subjects at runtime.

    The registry queries the subject for its action definitions and
    provides methods to look up actions by name or list all available
    action names (useful for prompt construction).

    Actions are cached after first retrieval to avoid repeated calls
    to the subject.

    Attributes:
        subject: The subject to query for action definitions

    Example:
        ```python
        registry = ActionRegistry(subject)

        # Get all definitions
        definitions = registry.get_definitions()

        # Find specific action
        transfer = registry.get_definition("transfer_leader")

        # List action names for prompts
        names = registry.list_action_names()  # ["transfer_leader", "split_region", ...]
        ```
    """

    def __init__(self, subject: "Subject") -> None:
        """
        Initialize registry with a subject.

        Args:
            subject: The subject to query for action definitions
        """
        self._subject = subject
        self._cache: dict[str, ActionDefinition] | None = None

    def _ensure_cache(self) -> dict[str, ActionDefinition]:
        """
        Lazily build the action cache.

        Returns:
            Dictionary mapping action names to definitions
        """
        if self._cache is None:
            definitions = self._subject.get_action_definitions()
            self._cache = {defn.name: defn for defn in definitions}
        return self._cache

    def get_definitions(self) -> list[ActionDefinition]:
        """
        Get all action definitions from the subject.

        Returns:
            List of ActionDefinition objects for all available actions
        """
        return list(self._ensure_cache().values())

    def get_definition(self, action_name: str) -> ActionDefinition | None:
        """
        Find an action definition by name.

        Args:
            action_name: The name of the action to find

        Returns:
            ActionDefinition if found, None otherwise
        """
        return self._ensure_cache().get(action_name)

    def list_action_names(self) -> list[str]:
        """
        Get just the action names.

        Useful for constructing prompts that list available actions.

        Returns:
            List of action name strings
        """
        return list(self._ensure_cache().keys())

    def clear_cache(self) -> None:
        """
        Clear the cached action definitions.

        Useful if the subject's available actions may have changed.
        """
        self._cache = None
