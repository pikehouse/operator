"""Agent Lab: v3.0 autonomous agent with shell access."""

from .loop import run_agent_loop
from .prompts import SYSTEM_PROMPT
from .summarize import summarize_with_haiku
from .ticket_ops import poll_for_open_ticket, update_ticket_escalated, update_ticket_resolved
from .tools import get_last_result, shell

__all__ = [
    "run_agent_loop",
    "shell",
    "get_last_result",
    "summarize_with_haiku",
    "poll_for_open_ticket",
    "update_ticket_resolved",
    "update_ticket_escalated",
    "SYSTEM_PROMPT",
]
