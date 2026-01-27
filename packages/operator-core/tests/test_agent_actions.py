"""
Tests for agent action proposal and execution.

Tests the flow from diagnosis recommendations to action execution,
without needing to call Claude.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from operator_core.agent.diagnosis import ActionRecommendation, DiagnosisOutput
from operator_core.agent.runner import AgentRunner
from operator_core.actions.executor import ActionExecutor
from operator_core.actions.registry import ActionRegistry, ActionDefinition, ParamDef
from operator_core.actions.types import ActionType


class MockSubject:
    """Mock subject for testing."""

    def get_action_definitions(self):
        return [
            ActionDefinition(
                name="reset_counter",
                description="Reset a rate limit counter",
                action_type=ActionType.SUBJECT,
                parameters={
                    "key": ParamDef(
                        type="str",
                        description="Counter key to reset",
                        required=True,
                    )
                },
                risk_level="medium",
            )
        ]

    async def observe(self):
        return {"counters": []}

    async def reset_counter(self, key: str):
        pass


@pytest.fixture
def mock_subject():
    return MockSubject()


@pytest.fixture
def mock_executor(tmp_path, mock_subject):
    """Create a real executor with mocked internals."""
    from operator_core.actions.safety import SafetyController, SafetyMode
    from operator_core.actions.audit import ActionAuditor

    db_path = tmp_path / "test.db"
    auditor = ActionAuditor(db_path)
    registry = ActionRegistry(mock_subject)
    safety = SafetyController(db_path, auditor, mode=SafetyMode.EXECUTE)

    executor = ActionExecutor(
        db_path=db_path,
        registry=registry,
        safety=safety,
        auditor=auditor,
        approval_mode=False,
    )
    return executor


class TestActionProposal:
    """Tests for action proposal from diagnosis."""

    @pytest.mark.asyncio
    async def test_propose_action_with_valid_params(self, mock_executor, mock_subject):
        """Action with valid parameters should be proposed successfully."""
        rec = ActionRecommendation(
            action_name="reset_counter",
            parameters={"key": "counter-drift-demo"},
            reason="Counter exceeded limit",
            expected_outcome="Counter reset to zero",
        )

        proposal = await mock_executor.propose_action(rec, ticket_id=1)

        assert proposal.action_name == "reset_counter"
        assert proposal.parameters == {"key": "counter-drift-demo"}
        assert proposal.id is not None

    @pytest.mark.asyncio
    async def test_propose_action_missing_required_param(self, mock_executor):
        """Action missing required parameter should raise ValidationError."""
        from operator_core.actions.validation import ValidationError

        rec = ActionRecommendation(
            action_name="reset_counter",
            parameters={},  # Missing 'key'
            reason="Counter exceeded limit",
            expected_outcome="Counter reset to zero",
        )

        with pytest.raises(ValidationError) as exc_info:
            await mock_executor.propose_action(rec, ticket_id=1)

        assert "key" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_propose_unknown_action(self, mock_executor):
        """Unknown action should raise ValueError."""
        rec = ActionRecommendation(
            action_name="nonexistent_action",
            parameters={},
            reason="Test",
            expected_outcome="Test",
        )

        with pytest.raises(ValueError) as exc_info:
            await mock_executor.propose_action(rec, ticket_id=1)

        assert "nonexistent_action" in str(exc_info.value)


class TestActionExecution:
    """Tests for action execution flow."""

    @pytest.mark.asyncio
    async def test_execute_action_calls_subject_method(self, mock_executor, mock_subject):
        """Executing action should call the subject's method."""
        # Track calls manually since AsyncMock return value isn't JSON serializable
        calls = []

        async def track_reset_counter(key: str):
            calls.append(key)

        mock_subject.reset_counter = track_reset_counter

        rec = ActionRecommendation(
            action_name="reset_counter",
            parameters={"key": "test-key"},
            reason="Test",
            expected_outcome="Test",
        )

        proposal = await mock_executor.propose_action(rec, ticket_id=1)
        await mock_executor.validate_proposal(proposal.id)
        record = await mock_executor.execute_proposal(proposal.id, mock_subject)

        assert record.success
        assert calls == ["test-key"]


class TestDiagnosisOutputSchema:
    """Tests for DiagnosisOutput schema validation."""

    def test_action_recommendation_requires_parameters(self):
        """ActionRecommendation should require parameters field."""
        # This should work - parameters provided
        rec = ActionRecommendation(
            action_name="reset_counter",
            parameters={"key": "test"},
            reason="Test",
            expected_outcome="Test",
        )
        assert rec.parameters == {"key": "test"}

    def test_action_recommendation_empty_params_allowed(self):
        """Empty dict is valid for actions with no required params."""
        rec = ActionRecommendation(
            action_name="some_action",
            parameters={},
            reason="Test",
            expected_outcome="Test",
        )
        assert rec.parameters == {}
