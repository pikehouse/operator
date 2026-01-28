"""Unit tests for agent loop audit logging."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from operator_core.agent_lab import loop
from operator_core.agent_lab import tools
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
