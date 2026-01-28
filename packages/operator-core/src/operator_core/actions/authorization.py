"""
Dual authorization checking for action execution (SAFE-04).

This module implements the dual authorization pattern where actions
are verified against BOTH:
1. Requester permission: Does the requester have permission to request this action?
2. Agent capability: Is the agent authorized to execute this action?

This follows OAuth delegation patterns where requester_id is the resource owner
and agent_id is the client acting on their behalf.

Per project patterns:
- Raise specific exceptions for authorization failures
- Support pluggable checker implementations
- Default checkers allow all (permissive by default, restrict via config)
"""

from typing import Protocol

from operator_core.actions.types import ActionProposal


class AuthorizationError(Exception):
    """
    Raised when an action fails authorization checks.

    This exception indicates either:
    - Requester lacks permission to request the action
    - Agent lacks capability to execute the action
    """

    pass


class PermissionChecker(Protocol):
    """
    Protocol for checking requester permissions.

    Implementations verify whether a given requester has permission
    to request a specific action.
    """

    def has_permission(self, requester_id: str, action_name: str) -> bool:
        """
        Check if requester has permission to request this action.

        Args:
            requester_id: Identity of requester (user email, system name, etc.)
            action_name: Name of action being requested

        Returns:
            True if requester has permission, False otherwise
        """
        ...


class CapabilityChecker(Protocol):
    """
    Protocol for checking agent capabilities.

    Implementations verify whether a given agent has the capability
    to execute a specific action.
    """

    def has_capability(self, agent_id: str, action_name: str) -> bool:
        """
        Check if agent has capability to execute this action.

        Args:
            agent_id: Identity of agent (e.g., "agent-diagnostics", "agent-remediation")
            action_name: Name of action to execute

        Returns:
            True if agent has capability, False otherwise
        """
        ...


class DefaultPermissionChecker:
    """
    Default permission checker that allows all requests.

    This is permissive by default to avoid blocking during development.
    In production, replace with a real implementation that checks against
    a permissions database or policy engine.
    """

    def has_permission(self, requester_id: str, action_name: str) -> bool:
        """Allow all requests by default."""
        return True


class DefaultCapabilityChecker:
    """
    Default capability checker that allows all agents.

    This is permissive by default to avoid blocking during development.
    In production, replace with a real implementation that checks against
    an agent capability registry or policy.
    """

    def has_capability(self, agent_id: str, action_name: str) -> bool:
        """Allow all agents by default."""
        return True


def _check_dual_authorization(
    requester_id: str,
    agent_id: str | None,
    action_name: str,
    permission_checker: PermissionChecker | None = None,
    capability_checker: CapabilityChecker | None = None,
) -> bool:
    """
    Internal helper for dual authorization checking.

    This is the core authorization logic extracted as a pure function
    for easy testing and composition.

    Args:
        requester_id: Identity of requester
        agent_id: Identity of executing agent (None if direct execution)
        action_name: Name of action being authorized
        permission_checker: Optional custom permission checker
        capability_checker: Optional custom capability checker

    Returns:
        True if authorization passes, False otherwise
    """
    # Use default checkers if not provided
    if permission_checker is None:
        permission_checker = DefaultPermissionChecker()
    if capability_checker is None:
        capability_checker = DefaultCapabilityChecker()

    # Check requester permission
    if not permission_checker.has_permission(requester_id, action_name):
        return False

    # Check agent capability (if delegated to an agent)
    if agent_id is not None:
        if not capability_checker.has_capability(agent_id, action_name):
            return False

    return True


def check_dual_authorization(
    proposal: ActionProposal,
    permission_checker: PermissionChecker | None = None,
    capability_checker: CapabilityChecker | None = None,
) -> None:
    """
    Verify dual authorization for an action proposal.

    Checks both:
    1. Requester has permission to request the action
    2. Agent has capability to execute the action (if delegated)

    Args:
        proposal: The action proposal to authorize
        permission_checker: Optional custom permission checker
        capability_checker: Optional custom capability checker

    Raises:
        AuthorizationError: If either check fails

    Example:
        proposal = ActionProposal(
            action_name="restart_service",
            requester_id="user@example.com",
            agent_id="agent-remediation"
        )
        check_dual_authorization(proposal)  # Raises if not authorized
    """
    # Use default checkers if not provided
    if permission_checker is None:
        permission_checker = DefaultPermissionChecker()
    if capability_checker is None:
        capability_checker = DefaultCapabilityChecker()

    # Check requester permission
    if not permission_checker.has_permission(proposal.requester_id, proposal.action_name):
        raise AuthorizationError(
            f"Requester '{proposal.requester_id}' lacks permission for action '{proposal.action_name}'"
        )

    # Check agent capability (if delegated to an agent)
    if proposal.agent_id is not None:
        if not capability_checker.has_capability(proposal.agent_id, proposal.action_name):
            raise AuthorizationError(
                f"Agent '{proposal.agent_id}' lacks capability for action '{proposal.action_name}'"
            )
