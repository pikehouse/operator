"""Session-based audit logging for agent conversations."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class SessionAuditor:
    """Logs agent conversation history to JSON files.

    The SessionAuditor tracks a complete agent session (one triggered incident)
    including all messages and tool calls. This is the integration point for the
    agent loop (Phase 31) which calls log_tool_call() after each shell() execution.

    Attributes:
        session_id: Unique session identifier with timestamp and UUID component
        audit_dir: Directory where audit log JSON files are saved
        messages: List of all conversation events (messages and tool calls)
    """

    def __init__(self, audit_dir: Path):
        """Initialize a new audit session.

        Args:
            audit_dir: Directory to save audit logs (created if doesn't exist)
        """
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        # Generate session ID: {timestamp}-{uuid4[:8]}
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        uuid_component = str(uuid.uuid4())[:8]
        self.session_id = f"{timestamp}-{uuid_component}"

        self.messages: list[dict[str, Any]] = []

    def log_message(self, role: str, content: Any) -> None:
        """Log a conversation message.

        Args:
            role: Message role (e.g., "user", "assistant")
            content: Message content (any JSON-serializable type)
        """
        self.messages.append({
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
        })

    def log_tool_call(self, tool_name: str, parameters: dict, result: dict) -> None:
        """Log a tool execution.

        This is the integration point for the Phase 31 agent loop, which calls
        this method after each shell() execution to record the full tool call
        context (command, reasoning) and results.

        Args:
            tool_name: Name of the tool that was called (e.g., "shell")
            parameters: Tool parameters (e.g., {"command": "uptime", "reasoning": "..."})
            result: Tool result (the structured dict returned by the tool)
        """
        self.messages.append({
            "timestamp": datetime.now().isoformat(),
            "type": "tool_call",
            "tool": tool_name,
            "parameters": parameters,
            "result": result,
        })

    def save_session(self) -> Path:
        """Save the complete session to a JSON file.

        Returns:
            Path to the saved JSON file
        """
        # Determine start and end times
        started_at = self.messages[0]["timestamp"] if self.messages else datetime.now().isoformat()
        ended_at = datetime.now().isoformat()

        # Build session data
        session_data = {
            "session_id": self.session_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "message_count": len(self.messages),
            "messages": self.messages,
        }

        # Write to file
        filepath = self.audit_dir / f"{self.session_id}.json"
        filepath.write_text(json.dumps(session_data, indent=2))

        return filepath
