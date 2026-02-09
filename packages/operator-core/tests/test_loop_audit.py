"""Unit tests for agent loop audit logging."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from operator_core.agent_lab import loop
from operator_core.agent_lab.prompts import SYSTEM_PROMPT
from operator_core.db.audit_log import AuditLogDB
from operator_core.monitor.types import Ticket, TicketStatus


def _make_ticket(**overrides):
    """Helper to create a minimal Ticket for testing."""
    defaults = dict(
        id=1,
        violation_key="test:1",
        invariant_name="test_invariant",
        message="Test violation",
        severity="high",
        first_seen_at=None,
        last_seen_at=None,
        status=TicketStatus.OPEN,
        store_id=None,
        held=False,
        batch_key=None,
        occurrence_count=1,
        resolved_at=None,
        diagnosis=None,
        metric_snapshot=None,
        created_at=None,
        updated_at=None,
    )
    defaults.update(overrides)
    return Ticket(**defaults)


async def _fake_query_stream(messages):
    """Helper: async generator that yields a sequence of mock SDK messages."""
    for msg in messages:
        yield msg


@pytest.mark.asyncio
async def test_process_ticket_logs_complete_audit_trail():
    """Verify that process_ticket logs reasoning, tool_call, and tool_result entries."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
        )

        msg1 = AssistantMessage(content=[
            TextBlock(text="Let me check the system status by running a command."),
            ToolUseBlock(id="tu_1", name="Bash", input={"command": "echo hello"}),
        ], model="claude-sonnet-4-5-20250929")
        msg2 = AssistantMessage(content=[
            ToolResultBlock(tool_use_id="tu_1", content="hello\n", is_error=False),
        ], model="claude-sonnet-4-5-20250929")
        msg3 = AssistantMessage(content=[
            TextBlock(text="The command completed successfully. Status is healthy."),
        ], model="claude-sonnet-4-5-20250929")
        result_msg = ResultMessage(
            subtype="result",
            duration_ms=1000,
            duration_api_ms=800,
            is_error=False,
            num_turns=2,
            session_id="test-session",
            total_cost_usd=0.01,
            usage={},
            result="The command completed successfully. Status is healthy.",
        )

        # query() returns an async iterator directly, not a coroutine
        def mock_query(prompt, options=None):
            return _fake_query_stream([msg1, msg2, msg3, result_msg])

        with patch.object(loop, "query", side_effect=mock_query):
            with AuditLogDB(db_path) as audit_db:
                session_id = audit_db.create_session(1)
                ticket = _make_ticket()

                status, summary = await loop.process_ticket(ticket, audit_db, session_id)

                assert status == "resolved"

                conn = sqlite3.connect(db_path)
                cursor = conn.execute(
                    "SELECT entry_type, tool_name, exit_code FROM agent_log_entries ORDER BY timestamp"
                )
                entries = cursor.fetchall()
                conn.close()

                # Should have: reasoning, tool_call, tool_result, reasoning
                assert len(entries) >= 3, f"Expected at least 3 entries, got {len(entries)}"

                reasoning_entries = [e for e in entries if e[0] == "reasoning"]
                assert len(reasoning_entries) >= 1, "Should have at least one reasoning entry"

                tool_call_entries = [e for e in entries if e[0] == "tool_call"]
                assert len(tool_call_entries) == 1, f"Should have one tool_call entry, got {len(tool_call_entries)}"
                assert tool_call_entries[0][1] == "Bash", "Tool name should be 'Bash'"

                tool_result_entries = [e for e in entries if e[0] == "tool_result"]
                assert len(tool_result_entries) == 1, f"Should have one tool_result entry, got {len(tool_result_entries)}"
                assert tool_result_entries[0][2] == 0, "Exit code should be 0 (not an error)"

    finally:
        db_path.unlink(missing_ok=True)


def test_subject_agent_prompts_are_importable():
    """Verify that AGENT_PROMPT constants are importable from subject packages."""
    from tikv_observer import AGENT_PROMPT as tikv_prompt
    from ratelimiter_observer import AGENT_PROMPT as rl_prompt

    assert "TiKV" in tikv_prompt, "TiKV prompt should mention TiKV"
    assert "pd-ctl" in tikv_prompt or "tikv-ctl" in tikv_prompt, "TiKV prompt should mention tools"

    assert "Redis" in rl_prompt or "rate limiter" in rl_prompt.lower(), "Rate limiter prompt should mention Redis or rate limiter"
    assert "counter" in rl_prompt.lower() or "ratelimiter" in rl_prompt.lower(), "Rate limiter prompt should mention counters or ratelimiter"


def test_ticket_ops_db_reads_subject_context():
    """Verify that TicketOpsDB.poll_for_open_ticket reads subject_context from database."""
    import asyncio
    from datetime import datetime
    from operator_core.db.tickets import TicketDB
    from operator_core.agent_lab.ticket_ops import TicketOpsDB
    from operator_protocols import InvariantViolation

    async def create_ticket_with_context(db_path, context):
        async with TicketDB(db_path) as db:
            now = datetime.now()
            violation = InvariantViolation(
                invariant_name="test_invariant",
                message="Test message",
                severity="warning",
                first_seen=now,
                last_seen=now,
                store_id="store1",
            )
            return await db.create_or_update_ticket(
                violation,
                subject_context=context,
            )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        test_context = "Rate limiter context for agent"
        asyncio.run(create_ticket_with_context(db_path, test_context))

        with TicketOpsDB(db_path) as ops_db:
            polled = ops_db.poll_for_open_ticket()

        assert polled is not None, "Should poll a ticket"
        assert polled.subject_context == test_context, (
            f"subject_context should be '{test_context}', got '{polled.subject_context}'"
        )

    finally:
        db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_process_ticket_uses_subject_context_in_system_prompt():
    """Verify that subject_context from ticket is appended to system prompt."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        captured_options = None

        def mock_query(prompt, options=None):
            nonlocal captured_options
            captured_options = options
            msg = AssistantMessage(content=[
                TextBlock(text="Analysis complete."),
            ], model="claude-sonnet-4-5-20250929")
            result = ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="test",
                total_cost_usd=0.001,
                usage={},
                result="Analysis complete.",
            )
            return _fake_query_stream([msg, result])

        test_subject_context = """
Rate limiter context:
- Sliding window rate limiter using Redis sorted sets
- Containers: ratelimiter-1, ratelimiter-2, ratelimiter-3, redis
"""

        ticket = _make_ticket(
            invariant_name="counter_drift",
            message="Counter drift detected",
            subject_context=test_subject_context,
        )

        with patch.object(loop, "query", side_effect=mock_query):
            with AuditLogDB(db_path) as audit_db:
                session_id = audit_db.create_session(1)
                await loop.process_ticket(ticket, audit_db, session_id)

        assert captured_options is not None, "Options should be captured"
        assert SYSTEM_PROMPT in captured_options.system_prompt, "Base system prompt should be included"
        assert test_subject_context in captured_options.system_prompt, "Subject context should be appended"
        assert captured_options.system_prompt == SYSTEM_PROMPT + "\n\n" + test_subject_context

    finally:
        db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_process_ticket_without_subject_context_uses_base_prompt():
    """Verify that base system prompt is used when no subject_context."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        captured_options = None

        def mock_query(prompt, options=None):
            nonlocal captured_options
            captured_options = options
            msg = AssistantMessage(content=[
                TextBlock(text="Analysis complete."),
            ], model="claude-sonnet-4-5-20250929")
            result = ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="test",
                total_cost_usd=0.001,
                usage={},
                result="Analysis complete.",
            )
            return _fake_query_stream([msg, result])

        ticket = _make_ticket(subject_context=None)

        with patch.object(loop, "query", side_effect=mock_query):
            with AuditLogDB(db_path) as audit_db:
                session_id = audit_db.create_session(1)
                await loop.process_ticket(ticket, audit_db, session_id)

        assert captured_options.system_prompt == SYSTEM_PROMPT, "Should use base system prompt only"

    finally:
        db_path.unlink(missing_ok=True)
