"""Script validation and execution for operator.

This module provides multi-layer validation for Python and Bash scripts
before execution in sandboxed Docker containers. Validation includes syntax
checking, secret scanning, and dangerous pattern detection. Execution happens
in isolated containers with network isolation and resource limits.

Public exports:
    ScriptValidator: Main validator class
    ValidationResult: Validation result dataclass
    ScriptExecutor: Sandboxed script executor
    ExecutionResult: Execution result dataclass
    get_script_tools: Get script execution tool definitions
    SECRET_PATTERNS: List of secret detection patterns
    PYTHON_DANGEROUS_PATTERNS: List of Python dangerous patterns
    BASH_DANGEROUS_PATTERNS: List of Bash dangerous patterns
"""

from operator_core.scripts.executor import ExecutionResult, ScriptExecutor
from operator_core.scripts.patterns import (
    BASH_DANGEROUS_PATTERNS,
    PYTHON_DANGEROUS_PATTERNS,
    SECRET_PATTERNS,
)
from operator_core.scripts.tools import get_script_tools
from operator_core.scripts.validation import ScriptValidator, ValidationResult

__all__ = [
    "ScriptValidator",
    "ValidationResult",
    "ScriptExecutor",
    "ExecutionResult",
    "get_script_tools",
    "SECRET_PATTERNS",
    "PYTHON_DANGEROUS_PATTERNS",
    "BASH_DANGEROUS_PATTERNS",
]
