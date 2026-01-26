"""
Retry configuration for action execution with exponential backoff.

This module provides RetryConfig for calculating retry delays with
exponential backoff and jitter, preventing thundering herd problems
when multiple failed actions retry simultaneously.

Per RESEARCH.md:
- Use exponential backoff with jitter
- Cap max_retries to prevent infinite loops
- Persist retry state in database for restart recovery
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class RetryConfig:
    """
    Configuration for action retry behavior.

    Uses exponential backoff with jitter to spread out retry attempts
    and prevent overwhelming the target system.

    Attributes:
        max_attempts: Maximum number of retry attempts (default 3)
        min_wait_seconds: Minimum wait before first retry (default 1.0)
        max_wait_seconds: Maximum wait between retries (default 60.0)
        exponential_base: Base for exponential calculation (default 2.0)
        jitter_fraction: Fraction of wait time to add as jitter (default 0.5)

    Example:
        config = RetryConfig(max_attempts=5, min_wait_seconds=2.0)
        next_retry = config.calculate_next_retry(attempt=1)
        # Returns datetime ~2-3 seconds from now (2s base + jitter)
    """

    max_attempts: int = 3
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter_fraction: float = 0.5

    def calculate_next_retry(self, attempt: int) -> datetime:
        """
        Calculate the next retry time with exponential backoff + jitter.

        Formula: min(max_wait, min_wait * base^attempt) + random(0, wait * jitter)

        Args:
            attempt: The attempt number (0 for first retry, 1 for second, etc.)

        Returns:
            datetime when the next retry should occur
        """
        # Calculate base wait with exponential backoff
        wait = min(
            self.max_wait_seconds,
            self.min_wait_seconds * (self.exponential_base**attempt),
        )

        # Add jitter to prevent thundering herd
        jitter = random.uniform(0, wait * self.jitter_fraction)
        delay = wait + jitter

        return datetime.now() + timedelta(seconds=delay)

    def should_retry(self, retry_count: int) -> bool:
        """
        Check if another retry attempt should be made.

        Args:
            retry_count: Current number of attempts made

        Returns:
            True if retry_count < max_attempts, False otherwise
        """
        return retry_count < self.max_attempts
