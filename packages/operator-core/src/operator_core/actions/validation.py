"""
Parameter validation framework for action execution.

This module provides pre-flight parameter validation (ACT-05) to ensure
action parameters match expected types before execution, preventing
runtime errors.

The validation collects ALL errors before raising, giving users complete
feedback rather than failing on the first issue.

Example:
    ```python
    try:
        validate_action_params(transfer_leader_def, {"region_id": "not-an-int"})
    except ValidationError as e:
        print(e)  # "Validation failed for transfer_leader: region_id must be int, got str"
    ```
"""

import logging
from typing import Any

from operator_core.actions.registry import ActionDefinition

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """
    Exception raised when action parameter validation fails.

    Contains the action name and a list of all validation errors,
    providing complete feedback to users.

    Attributes:
        action_name: Name of the action that failed validation
        errors: List of human-readable error messages
    """

    def __init__(self, action_name: str, errors: list[str]) -> None:
        """
        Initialize validation error.

        Args:
            action_name: Name of the action that failed validation
            errors: List of validation error messages
        """
        self.action_name = action_name
        self.errors = errors
        super().__init__(str(self))

    def __str__(self) -> str:
        """Format as readable error message."""
        error_list = "; ".join(self.errors)
        return f"Validation failed for {self.action_name}: {error_list}"


# Type checking functions
# Note: Python's bool is subclass of int, so we exclude bool from int/float checks


def _check_type(value: Any, expected_type: str) -> bool:
    """
    Check if value matches expected type.

    Args:
        value: The value to check
        expected_type: Python type name ("int", "str", "float", "bool")

    Returns:
        True if type matches, False otherwise
    """
    if expected_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    elif expected_type == "str":
        return isinstance(value, str)
    elif expected_type == "float":
        # Accept int as float (common pattern)
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected_type == "bool":
        return isinstance(value, bool)
    else:
        # Unknown type - log warning and skip validation
        logger.warning(f"Unknown type '{expected_type}' - skipping validation")
        return True


def _get_type_name(value: Any) -> str:
    """
    Get human-readable type name for a value.

    Args:
        value: The value to get type name for

    Returns:
        Type name as string
    """
    return type(value).__name__


def validate_action_params(
    definition: ActionDefinition,
    parameters: dict[str, Any],
) -> None:
    """
    Validate parameters against action definition.

    Checks:
    1. All required parameters are present
    2. No unknown parameters provided
    3. Parameter types match expected types

    Collects ALL errors before raising to give complete feedback.

    Args:
        definition: The ActionDefinition to validate against
        parameters: The parameters to validate

    Raises:
        ValidationError: If validation fails (contains all errors)

    Example:
        ```python
        defn = ActionDefinition(
            name="transfer_leader",
            description="Transfer leadership",
            parameters={
                "region_id": ParamDef(type="int", description="Region"),
                "to_store_id": ParamDef(type="str", description="Target store"),
            },
            risk_level="medium"
        )

        # Valid
        validate_action_params(defn, {"region_id": 42, "to_store_id": "store-1"})

        # Invalid - raises ValidationError
        validate_action_params(defn, {"region_id": "bad"})
        ```
    """
    errors: list[str] = []

    # Get the defined parameter names
    defined_params = set(definition.parameters.keys())
    provided_params = set(parameters.keys())

    # Check for unknown parameters
    unknown = provided_params - defined_params
    for param_name in sorted(unknown):
        errors.append(f"unknown parameter '{param_name}'")

    # Check required parameters and types
    for param_name, param_def in definition.parameters.items():
        if param_name in parameters:
            # Parameter provided - check type
            value = parameters[param_name]
            if not _check_type(value, param_def.type):
                actual_type = _get_type_name(value)
                errors.append(
                    f"{param_name} must be {param_def.type}, got {actual_type}"
                )
        elif param_def.required:
            # Required parameter missing
            errors.append(f"missing required parameter '{param_name}'")
        # Optional parameter not provided - OK, will use default

    if errors:
        raise ValidationError(definition.name, errors)
