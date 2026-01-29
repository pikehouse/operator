"""Unit tests for agent loop audit logging."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from operator_core.agent_lab import loop
from operator_core.agent_lab import tools
from operator_core.agent_lab.prompts import SYSTEM_PROMPT
from operator_core.db.audit_log import AuditLogDB
from operator_core.monitor.types import Ticket, TicketStatus


def test_process_ticket_logs_complete_audit_trail():
    """Verify that process_ticket logs reasoning, tool_call, and tool_result entries."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create mock client
        mock_client = MagicMock()

        # Mock Haiku summarization
        def mock_summarize(client, text: str) -> str:
            return text[:50] + "..." if len(text) > 50 else text

        # Create mock messages that simulate the tool_runner flow
        mock_msg1 = Mock()
        mock_msg1.role = "assistant"
        mock_msg1.stop_reason = "tool_use"

        # Create mock blocks with proper attributes
        text_block = Mock()
        text_block.type = "text"
        text_block.text = "Let me check the system status by running a command."

        tool_use_block = Mock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "shell"
        tool_use_block.input = {"command": "echo hello", "reasoning": "Test"}

        mock_msg1.content = [text_block, tool_use_block]

        mock_msg2 = Mock()
        mock_msg2.role = "assistant"
        mock_msg2.stop_reason = "end_turn"

        final_text_block = Mock()
        final_text_block.type = "text"
        final_text_block.text = "The command completed successfully. Status is healthy."

        mock_msg2.content = [final_text_block]

        # Mock the tool_runner to return our messages
        with patch.object(loop, "summarize_with_haiku", side_effect=mock_summarize):
            with patch.object(mock_client.beta.messages, "tool_runner") as mock_runner:
                # Simulate tool execution by setting global state after first message
                def message_generator():
                    yield mock_msg1
                    tools._last_shell_result = {"output": "hello\n", "exit_code": 0, "command": "echo hello"}
                    yield mock_msg2

                mock_runner.return_value = message_generator()

                # Create audit DB and session
                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(1)

                    # Create minimal ticket
                    ticket = Ticket(
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

                    # Process ticket
                    loop.process_ticket(mock_client, ticket, audit_db, session_id)

                    # Verify audit entries
                    conn = sqlite3.connect(db_path)
                    cursor = conn.execute(
                        "SELECT entry_type, tool_name, exit_code FROM agent_log_entries ORDER BY timestamp"
                    )
                    entries = cursor.fetchall()
                    conn.close()

                    # Should have: reasoning, tool_call, tool_result, reasoning
                    assert len(entries) >= 3, f"Expected at least 3 entries, got {len(entries)}"

                    # Check for reasoning entry
                    reasoning_entries = [e for e in entries if e[0] == "reasoning"]
                    assert len(reasoning_entries) >= 1, "Should have at least one reasoning entry"

                    # Check for tool_call entry
                    tool_call_entries = [e for e in entries if e[0] == "tool_call"]
                    assert len(tool_call_entries) == 1, f"Should have one tool_call entry, got {len(tool_call_entries)}"
                    assert tool_call_entries[0][1] == "shell", "Tool name should be 'shell'"

                    # Check for tool_result entry
                    tool_result_entries = [e for e in entries if e[0] == "tool_result"]
                    assert len(tool_result_entries) == 1, f"Should have one tool_result entry, got {len(tool_result_entries)}"
                    assert tool_result_entries[0][2] == 0, "Exit code should be 0"

    finally:
        # Cleanup
        db_path.unlink(missing_ok=True)


def test_subject_agent_prompts_are_importable():
    """Verify that AGENT_PROMPT constants are importable from subject packages."""
    from tikv_observer import AGENT_PROMPT as tikv_prompt
    from ratelimiter_observer import AGENT_PROMPT as rl_prompt

    # Verify they contain expected content
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

        # Create ticket with subject_context using async TicketDB
        asyncio.run(create_ticket_with_context(db_path, test_context))

        # Read it back with sync TicketOpsDB
        with TicketOpsDB(db_path) as ops_db:
            polled = ops_db.poll_for_open_ticket()

        assert polled is not None, "Should poll a ticket"
        assert polled.subject_context == test_context, (
            f"subject_context should be '{test_context}', got '{polled.subject_context}'"
        )

    finally:
        db_path.unlink(missing_ok=True)


def test_process_ticket_uses_subject_context_in_system_prompt():
    """Verify that subject_context from ticket is appended to system prompt."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        # Create mock client
        mock_client = MagicMock()

        # Mock Haiku summarization
        def mock_summarize(client, text: str) -> str:
            return text[:50] + "..." if len(text) > 50 else text

        # Create mock message
        mock_msg = Mock()
        mock_msg.role = "assistant"
        mock_msg.stop_reason = "end_turn"

        final_text_block = Mock()
        final_text_block.type = "text"
        final_text_block.text = "Analysis complete."

        mock_msg.content = [final_text_block]

        # Capture the system prompt passed to tool_runner
        captured_system_prompt = None

        def capture_tool_runner(*args, **kwargs):
            nonlocal captured_system_prompt
            captured_system_prompt = kwargs.get("system")
            return iter([mock_msg])

        with patch.object(loop, "summarize_with_haiku", side_effect=mock_summarize):
            with patch.object(mock_client.beta.messages, "tool_runner", side_effect=capture_tool_runner):
                # Create audit DB and session
                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(1)

                    # Subject context to test
                    test_subject_context = """
Rate limiter context:
- Sliding window rate limiter using Redis sorted sets
- Containers: ratelimiter-1, ratelimiter-2, ratelimiter-3, redis
"""

                    # Create ticket WITH subject_context
                    ticket = Ticket(
                        id=1,
                        violation_key="test:1",
                        invariant_name="counter_drift",
                        message="Counter drift detected",
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
                        subject_context=test_subject_context,
                        created_at=None,
                        updated_at=None,
                    )

                    # Process ticket
                    loop.process_ticket(mock_client, ticket, audit_db, session_id)

        # Verify subject_context was appended to system prompt
        assert captured_system_prompt is not None, "System prompt should be captured"
        assert SYSTEM_PROMPT in captured_system_prompt, "Base system prompt should be included"
        assert test_subject_context in captured_system_prompt, "Subject context should be appended"
        assert captured_system_prompt == SYSTEM_PROMPT + "\n\n" + test_subject_context

    finally:
        db_path.unlink(missing_ok=True)


def test_process_ticket_without_subject_context_uses_base_prompt():
    """Verify that base system prompt is used when no subject_context."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        mock_client = MagicMock()

        def mock_summarize(client, text: str) -> str:
            return text[:50] + "..." if len(text) > 50 else text

        mock_msg = Mock()
        mock_msg.role = "assistant"
        mock_msg.stop_reason = "end_turn"

        final_text_block = Mock()
        final_text_block.type = "text"
        final_text_block.text = "Analysis complete."

        mock_msg.content = [final_text_block]

        captured_system_prompt = None

        def capture_tool_runner(*args, **kwargs):
            nonlocal captured_system_prompt
            captured_system_prompt = kwargs.get("system")
            return iter([mock_msg])

        with patch.object(loop, "summarize_with_haiku", side_effect=mock_summarize):
            with patch.object(mock_client.beta.messages, "tool_runner", side_effect=capture_tool_runner):
                with AuditLogDB(db_path) as audit_db:
                    session_id = audit_db.create_session(1)

                    # Create ticket WITHOUT subject_context
                    ticket = Ticket(
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
                        subject_context=None,  # No subject context
                        created_at=None,
                        updated_at=None,
                    )

                    loop.process_ticket(mock_client, ticket, audit_db, session_id)

        # Verify only base prompt is used
        assert captured_system_prompt == SYSTEM_PROMPT, "Should use base system prompt only"

    finally:
        db_path.unlink(missing_ok=True)
