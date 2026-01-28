"""Multi-layer script validation for security enforcement.

This module provides the ScriptValidator class which implements a 4-layer
validation pipeline:
  1. Size check - reject oversized scripts
  2. Syntax validation - ensure script is parseable
  3. Secret scanning - detect hardcoded credentials
  4. Dangerous pattern detection - block unsafe code patterns

All validation must pass before a script can be executed in the sandbox.
"""

import ast
import re
from dataclasses import dataclass

from operator_core.scripts.patterns import (
    BASH_DANGEROUS_PATTERNS,
    PYTHON_DANGEROUS_PATTERNS,
    SECRET_PATTERNS,
)


@dataclass
class ValidationResult:
    """Result of script validation.

    Attributes:
        valid: Whether the script passed validation
        error: Error message if validation failed, None if valid
        layer: Which validation layer failed (size, syntax, secrets, dangerous)
    """

    valid: bool
    error: str | None = None
    layer: str | None = None


class ScriptValidator:
    """Multi-layer validator for Python and Bash scripts.

    Validates scripts through 4 security layers before execution:
      1. Size check (VALD-05) - prevent resource exhaustion
      2. Syntax check (VALD-01, VALD-02) - ensure parseable code
      3. Secret scan (VALD-03) - detect hardcoded credentials
      4. Dangerous pattern scan (VALD-04) - block unsafe constructs

    Validation stops at the first failure (fail-fast).
    """

    MAX_SIZE = 10000  # VALD-05: Maximum script size in characters

    def validate(self, content: str, script_type: str) -> ValidationResult:
        """Validate script through all layers. First failure stops.

        Args:
            content: Script content to validate
            script_type: Either "python" or "bash"

        Returns:
            ValidationResult indicating success or first failure
        """
        # Layer 1: Size check (VALD-05)
        if len(content) > self.MAX_SIZE:
            return ValidationResult(
                valid=False,
                error=f"Script exceeds maximum size of {self.MAX_SIZE} characters (got {len(content)})",
                layer="size",
            )

        # Layer 2: Syntax check (VALD-01, VALD-02)
        # Python: ast.parse() - synchronous
        # Bash: requires async (bash -n), handle in executor
        if script_type == "python":
            result = self._validate_python_syntax(content)
            if not result.valid:
                return result
        # Bash syntax validated at execution time (requires subprocess)

        # Layer 3: Secrets scan (VALD-03)
        result = self._scan_for_secrets(content)
        if not result.valid:
            return result

        # Layer 4: Dangerous patterns (VALD-04)
        result = self._scan_for_dangerous(content, script_type)
        if not result.valid:
            return result

        return ValidationResult(valid=True)

    def _validate_python_syntax(self, content: str) -> ValidationResult:
        """Validate Python syntax using ast.parse().

        Args:
            content: Python script content

        Returns:
            ValidationResult with syntax error details if invalid
        """
        try:
            ast.parse(content)
            return ValidationResult(valid=True)
        except SyntaxError as e:
            return ValidationResult(
                valid=False,
                error=f"Python syntax error at line {e.lineno}: {e.msg}",
                layer="syntax",
            )

    def _scan_for_secrets(self, content: str) -> ValidationResult:
        """Scan script for hardcoded secrets.

        Args:
            content: Script content to scan

        Returns:
            ValidationResult indicating if secrets were found
        """
        for pattern, desc in SECRET_PATTERNS:
            if re.search(pattern, content):
                return ValidationResult(
                    valid=False, error=f"Potential secret: {desc}", layer="secrets"
                )
        return ValidationResult(valid=True)

    def _scan_for_dangerous(self, content: str, script_type: str) -> ValidationResult:
        """Scan script for dangerous code patterns.

        Args:
            content: Script content to scan
            script_type: Either "python" or "bash"

        Returns:
            ValidationResult indicating if dangerous patterns were found
        """
        patterns = (
            PYTHON_DANGEROUS_PATTERNS
            if script_type == "python"
            else BASH_DANGEROUS_PATTERNS
        )
        for pattern, desc in patterns:
            if re.search(pattern, content):
                return ValidationResult(
                    valid=False, error=f"Dangerous pattern: {desc}", layer="dangerous"
                )
        return ValidationResult(valid=True)
