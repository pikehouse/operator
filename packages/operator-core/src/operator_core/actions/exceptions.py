"""
TOCTOU-related exception classes for action execution safety.

This module defines exceptions for Time-Of-Check Time-Of-Use (TOCTOU)
defense mechanisms:
- ApprovalExpiredError: Approval token expired (60s window)
- StateChangedError: Concurrent modification detected
- InvalidTokenError: Token mismatch on execution

These exceptions are raised during execute_proposal to prevent TOCTOU attacks
where system state changes between approval and execution.

Per project patterns:
- Inherit from Exception for base exception type
- Store context data in attributes for error handling
- Include descriptive message with relevant details
"""


class ApprovalExpiredError(Exception):
    """
    Raised when approval token has expired (SAFE-02).

    Approval tokens expire after 60 seconds to prevent stale approvals
    from being used when system state may have changed.

    Attributes:
        proposal_id: The proposal that was attempted
        age_seconds: How old the approval was in seconds
    """

    def __init__(self, proposal_id: int, age_seconds: float) -> None:
        self.proposal_id = proposal_id
        self.age_seconds = age_seconds
        super().__init__(
            f"Approval for proposal {proposal_id} expired "
            f"(age: {age_seconds:.1f}s, max: 60s). "
            f"Re-approve to execute."
        )


class StateChangedError(Exception):
    """
    Raised when proposal state changed between approval and execution (SAFE-01).

    This indicates a TOCTOU race condition where the proposal was modified
    by a concurrent operation after approval but before execution.

    Attributes:
        proposal_id: The proposal that was attempted
        reason: Why the state change was detected
    """

    def __init__(self, proposal_id: int, reason: str) -> None:
        self.proposal_id = proposal_id
        self.reason = reason
        super().__init__(
            f"State changed for proposal {proposal_id}: {reason}. "
            f"Cannot execute - re-validate and re-approve required."
        )


class InvalidTokenError(Exception):
    """
    Raised when approval token doesn't match (SAFE-02).

    This prevents execution with a different approval token than the one
    generated during approval, indicating tampering or replay attempt.

    Attributes:
        proposal_id: The proposal that was attempted
    """

    def __init__(self, proposal_id: int) -> None:
        self.proposal_id = proposal_id
        super().__init__(
            f"Invalid approval token for proposal {proposal_id}. "
            f"Token must match the one generated during approval."
        )
