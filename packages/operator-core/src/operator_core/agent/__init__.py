"""
Agent module for AI-powered diagnosis and action.

This module contains:
- diagnosis.py: Pydantic models for structured diagnosis output
- context.py: Context gathering for diagnosis (DiagnosisContext, ContextGatherer)
- prompt.py: System prompts and template construction
- runner.py: Agent runner daemon that processes tickets

Per PROJECT.md: "AI demonstrates real diagnostic reasoning about
distributed systems - not just 'something is wrong' but 'here's what's
happening, here are the options, here's why I'd choose this one.'"
"""

from operator_core.agent.context import ContextGatherer, DiagnosisContext
from operator_core.agent.diagnosis import (
    Alternative,
    DiagnosisOutput,
    format_diagnosis_markdown,
)
from operator_core.agent.prompt import SYSTEM_PROMPT, build_diagnosis_prompt
from operator_core.agent.runner import AgentRunner

__all__ = [
    # Context gathering
    "ContextGatherer",
    "DiagnosisContext",
    # Diagnosis models
    "Alternative",
    "DiagnosisOutput",
    "format_diagnosis_markdown",
    # Prompt building
    "SYSTEM_PROMPT",
    "build_diagnosis_prompt",
    # Agent runner
    "AgentRunner",
]
