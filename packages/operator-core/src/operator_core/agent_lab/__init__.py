"""Agent Lab: v3.0 autonomous agent with shell access."""
from .tools import shell as async_shell  # Phase 30 async version
from .audit import SessionAuditor
from .loop import run_agent_loop, shell  # Phase 31 sync version for tool_runner
from .prompts import SYSTEM_PROMPT

__all__ = ["async_shell", "shell", "SessionAuditor", "run_agent_loop", "SYSTEM_PROMPT"]
