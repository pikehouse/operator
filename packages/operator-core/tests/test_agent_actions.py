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


class TestParameterInference:
    """Tests for parameter inference when Claude returns empty params."""

    @pytest.fixture
    def runner(self, tmp_path, mock_subject):
        """Create AgentRunner for testing inference."""
        return AgentRunner(
            subject=mock_subject,
            db_path=tmp_path / "test.db",
        )

    def test_infer_reset_counter_finds_over_limit(self, runner):
        """Should infer key from counter that's over limit."""
        observation = {
            "counters": [
                {"key": "api-orders", "count": 5, "limit": 10},
                {"key": "counter-drift-demo", "count": 15, "limit": 10},
                {"key": "api-users", "count": 3, "limit": 10},
            ]
        }

        result = runner._infer_action_parameters("reset_counter", observation)

        assert result == {"key": "counter-drift-demo"}

    def test_infer_reset_counter_no_over_limit(self, runner):
        """Should return None when no counter is over limit."""
        observation = {
            "counters": [
                {"key": "api-orders", "count": 5, "limit": 10},
                {"key": "api-users", "count": 3, "limit": 10},
            ]
        }

        result = runner._infer_action_parameters("reset_counter", observation)

        assert result is None

    def test_infer_reset_counter_empty_counters(self, runner):
        """Should return None when counters list is empty."""
        observation = {"counters": []}

        result = runner._infer_action_parameters("reset_counter", observation)

        assert result is None

    def test_infer_reset_counter_no_counters_key(self, runner):
        """Should return None when observation has no counters."""
        observation = {"nodes": [{"id": "node-1", "state": "Up"}]}

        result = runner._infer_action_parameters("reset_counter", observation)

        assert result is None

    def test_infer_unknown_action_returns_none(self, runner):
        """Should return None for actions without inference logic."""
        observation = {
            "counters": [
                {"key": "counter-drift-demo", "count": 15, "limit": 10},
            ]
        }

        result = runner._infer_action_parameters("unknown_action", observation)

        assert result is None

    def test_infer_finds_first_over_limit(self, runner):
        """Should return the first counter that's over limit."""
        observation = {
            "counters": [
                {"key": "first-over", "count": 12, "limit": 10},
                {"key": "second-over", "count": 20, "limit": 10},
            ]
        }

        result = runner._infer_action_parameters("reset_counter", observation)

        assert result == {"key": "first-over"}


class TestTiKVParameterInference:
    """Tests for TiKV action parameter inference."""

    @pytest.fixture
    def runner(self, tmp_path, mock_subject):
        """Create AgentRunner for testing inference."""
        return AgentRunner(
            subject=mock_subject,
            db_path=tmp_path / "test.db",
        )

    def test_infer_drain_store_finds_down_store(self, runner):
        """Should infer store_id from down store."""
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-1:20160", "state": "Up"},
                {"id": "2", "address": "tikv-2:20160", "state": "Down"},
                {"id": "3", "address": "tikv-3:20160", "state": "Up"},
            ]
        }

        result = runner._infer_action_parameters("drain_store", observation)

        assert result == {"store_id": "2"}

    def test_infer_drain_store_no_down_stores(self, runner):
        """Should return None when all stores are up."""
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-1:20160", "state": "Up"},
                {"id": "2", "address": "tikv-2:20160", "state": "Up"},
            ]
        }

        result = runner._infer_action_parameters("drain_store", observation)

        assert result is None

    def test_infer_drain_store_empty_stores(self, runner):
        """Should return None when stores list is empty."""
        observation = {"stores": []}

        result = runner._infer_action_parameters("drain_store", observation)

        assert result is None

    def test_infer_drain_store_no_stores_key(self, runner):
        """Should return None when observation has no stores."""
        observation = {"counters": []}

        result = runner._infer_action_parameters("drain_store", observation)

        assert result is None

    def test_infer_drain_store_finds_first_down(self, runner):
        """Should return the first down store when multiple are down."""
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-1:20160", "state": "Down"},
                {"id": "2", "address": "tikv-2:20160", "state": "Down"},
                {"id": "3", "address": "tikv-3:20160", "state": "Up"},
            ]
        }

        result = runner._infer_action_parameters("drain_store", observation)

        assert result == {"store_id": "1"}

    def test_infer_drain_store_handles_disconnected_state(self, runner):
        """Should treat Disconnected as down."""
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-1:20160", "state": "Up"},
                {"id": "2", "address": "tikv-2:20160", "state": "Disconnected"},
            ]
        }

        result = runner._infer_action_parameters("drain_store", observation)

        assert result == {"store_id": "2"}

    def test_infer_transfer_leader_returns_none(self, runner):
        """transfer_leader needs region_id which requires region query."""
        observation = {
            "stores": [
                {"id": "1", "address": "tikv-1:20160", "state": "Up"},
                {"id": "2", "address": "tikv-2:20160", "state": "Down"},
            ],
            "cluster_metrics": {"leader_count": {"1": 10, "2": 5}},
        }

        # transfer_leader is too complex to infer without region queries
        result = runner._infer_action_parameters("transfer_leader", observation)

        assert result is None


class TestParameterInferenceIntegration:
    """Integration tests for parameter inference in action flow."""

    @pytest.fixture
    def mock_subject_with_over_limit(self):
        """Subject that returns over-limit counter in observation."""
        class SubjectWithOverLimit(MockSubject):
            async def observe(self):
                return {
                    "counters": [
                        {"key": "counter-drift-demo", "count": 15, "limit": 10},
                    ]
                }
        return SubjectWithOverLimit()

    @pytest.fixture
    def executor_with_subject(self, tmp_path, mock_subject_with_over_limit):
        """Create executor with over-limit subject."""
        from operator_core.actions.safety import SafetyController, SafetyMode
        from operator_core.actions.audit import ActionAuditor

        db_path = tmp_path / "test.db"
        auditor = ActionAuditor(db_path)
        registry = ActionRegistry(mock_subject_with_over_limit)
        safety = SafetyController(db_path, auditor, mode=SafetyMode.EXECUTE)

        return ActionExecutor(
            db_path=db_path,
            registry=registry,
            safety=safety,
            auditor=auditor,
            approval_mode=False,
        )

    @pytest.mark.asyncio
    async def test_empty_params_get_inferred_and_executed(
        self, tmp_path, mock_subject_with_over_limit, executor_with_subject
    ):
        """Action with empty params should succeed via inference."""
        # Track calls
        calls = []

        async def track_reset_counter(key: str):
            calls.append(key)

        mock_subject_with_over_limit.reset_counter = track_reset_counter

        # Create runner with executor
        runner = AgentRunner(
            subject=mock_subject_with_over_limit,
            db_path=tmp_path / "test.db",
            executor=executor_with_subject,
        )

        # Create recommendation with EMPTY params (simulating Claude's behavior)
        rec = ActionRecommendation(
            action_name="reset_counter",
            parameters={},  # Empty - should be inferred
            reason="Counter exceeded limit",
            expected_outcome="Counter reset to zero",
        )

        # Get observation for inference
        observation = await mock_subject_with_over_limit.observe()

        # Manually test inference + proposal flow
        inferred = runner._infer_action_parameters(rec.action_name, observation)
        assert inferred == {"key": "counter-drift-demo"}

        # Update rec with inferred params (as runner does)
        rec.parameters = inferred

        # Now proposal should succeed
        proposal = await executor_with_subject.propose_action(rec, ticket_id=1)
        assert proposal.parameters == {"key": "counter-drift-demo"}

        # Execute should work
        await executor_with_subject.validate_proposal(proposal.id)
        record = await executor_with_subject.execute_proposal(
            proposal.id, mock_subject_with_over_limit
        )

        assert record.success
        assert calls == ["counter-drift-demo"]
