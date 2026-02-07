"""Agent Lab: v3.0 autonomous agent with shell access."""

from .loop import run_agent_loop
from .prompts import SYSTEM_PROMPT
from .summarize import summarize_with_haiku
from .ticket_ops import TicketOpsDB
from .tools import get_last_result, shell

__all__ = [
    "run_agent_loop",
    "shell",
    "get_last_result",
    "summarize_with_haiku",
    "TicketOpsDB",
    "SYSTEM_PROMPT",
]
