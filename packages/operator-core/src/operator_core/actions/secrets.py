"""
Secret redaction for audit logs (SAFE-06).

This module provides secret detection and redaction to prevent credential
leakage in audit trails. Uses detect-secrets library for pattern-based
detection combined with key-based heuristics.

Per project patterns:
- Industry-standard detect-secrets library (not hand-rolled regex)
- Recursive handling of nested dictionaries
- Case-insensitive key matching for sensitive field names
"""

import re
from typing import Any

from detect_secrets.core import baseline
from detect_secrets.settings import default_settings


class SecretRedactor:
    """
    Redacts secrets from dictionaries before audit logging.

    Uses two detection strategies:
    1. Key-based: Field names like 'password', 'token', 'api_key'
    2. Pattern-based: Env var assignments (API_KEY=xxx), Bearer tokens

    Example:
        redactor = SecretRedactor()
        safe_data = redactor.redact_dict({
            'password': 'secret123',
            'config': 'API_KEY=sk_live_xxx',
            'auth': {'token': 'bearer_token'},
            'name': 'john'
        })
        # Results in:
        # {
        #     'password': '[REDACTED]',
        #     'config': 'API_KEY=[REDACTED]',
        #     'auth': {'token': '[REDACTED]'},
        #     'name': 'john'
        # }
    """

    # Sensitive key names (case-insensitive)
    SENSITIVE_KEYS = {
        "password",
        "passwords",
        "passwd",
        "pwd",
        "secret",
        "secrets",
        "token",
        "tokens",
        "api_key",
        "api_keys",
        "apikey",
        "apikeys",
        "api_token",
        "api_tokens",
        "access_token",
        "access_tokens",
        "refresh_token",
        "refresh_tokens",
        "bearer",
        "authorization",
        "auth",
        "credentials",
        "credential",
        "private_key",
        "private_keys",
        "privatekey",
        "privatekeys",
        "key",
        "keys",
        "session",
        "sessions",
        "cookie",
        "cookies",
        "jwt",
        "oauth",
    }

    # Patterns for env var style secrets (KEY=value)
    ENV_VAR_PATTERNS = [
        re.compile(r"(API_KEY|APIKEY|TOKEN|PASSWORD|SECRET|KEY)=([^\s]+)", re.IGNORECASE),
    ]

    # Pattern for Bearer tokens
    BEARER_PATTERN = re.compile(r"Bearer\s+([^\s]+)", re.IGNORECASE)

    def __init__(self) -> None:
        """Initialize the secret redactor with detect-secrets."""
        self._settings = default_settings
        self._baseline = baseline.create()

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Redact secrets from a dictionary.

        Recursively processes nested dictionaries and lists, redacting
        any detected secrets.

        Args:
            data: Dictionary potentially containing secrets

        Returns:
            Dictionary with secrets replaced by '[REDACTED]'
        """
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            # Recursively handle nested dicts (structure takes priority)
            if isinstance(value, dict):
                result[key] = self.redact_dict(value)
            # Handle lists
            elif isinstance(value, list):
                # If key is sensitive, redact entire list
                if key.lower() in self.SENSITIVE_KEYS:
                    result[key] = "[REDACTED]"
                else:
                    # Otherwise, process list items
                    result[key] = [
                        self.redact_dict(item) if isinstance(item, dict) else item
                        for item in value
                    ]
            # Check if key is sensitive (case-insensitive) for leaf values
            elif key.lower() in self.SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            # Handle string values with pattern matching
            elif isinstance(value, str):
                result[key] = self._redact_string(value)
            # Other types pass through
            else:
                result[key] = value

        return result

    def _redact_string(self, value: str) -> str:
        """
        Redact secrets from string values using pattern matching.

        Detects:
        - Environment variable style assignments (API_KEY=xxx)
        - Bearer tokens

        Args:
            value: String potentially containing secrets

        Returns:
            String with secrets redacted
        """
        if not value:
            return value

        result = value

        # Redact env var patterns
        for pattern in self.ENV_VAR_PATTERNS:
            result = pattern.sub(r"\1=[REDACTED]", result)

        # Redact Bearer tokens
        result = self.BEARER_PATTERN.sub(r"Bearer [REDACTED]", result)

        return result
