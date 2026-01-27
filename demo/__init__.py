"""
Shared demo infrastructure for multi-subject chaos demonstrations.

This package provides the Chapter state machine, ChaosConfig types,
and a generic DemoRunner that works with any subject (TiKV, rate limiter, etc.).

The demo framework enables the same TUI structure to be used across different
distributed systems by accepting subject-specific chapters and health pollers.
"""
