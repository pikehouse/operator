"""Script validation and security scanning for operator.

This module provides multi-layer validation for Python and Bash scripts
before execution in the sandbox. Validation includes syntax checking,
secret scanning, and dangerous pattern detection.

Public exports:
    ScriptValidator: Main validator class
    ValidationResult: Validation result dataclass
    SECRET_PATTERNS: List of secret detection patterns
    PYTHON_DANGEROUS_PATTERNS: List of Python dangerous patterns
    BASH_DANGEROUS_PATTERNS: List of Bash dangerous patterns
"""

from operator_core.scripts.patterns import (
    BASH_DANGEROUS_PATTERNS,
    PYTHON_DANGEROUS_PATTERNS,
    SECRET_PATTERNS,
)
from operator_core.scripts.validation import ScriptValidator, ValidationResult

__all__ = [
    "ScriptValidator",
    "ValidationResult",
    "SECRET_PATTERNS",
    "PYTHON_DANGEROUS_PATTERNS",
    "BASH_DANGEROUS_PATTERNS",
]
