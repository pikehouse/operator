"""
Shared status for demo TUI.

Provides a module-level status object that chaos callbacks can update
and the TUI can display. This avoids print() which doesn't work with
Rich's Live context.
"""


class DemoStatus:
    """Shared status for TUI display."""

    def __init__(self) -> None:
        self._text = ""
        self._lines: list[str] = []

    def set(self, text: str) -> None:
        """Set status text (replaces previous)."""
        self._text = text
        if text:
            self._lines.append(text)
            # Keep last 5 lines
            self._lines = self._lines[-5:]

    def get(self) -> str:
        """Get current status text."""
        return self._text

    def get_log(self) -> str:
        """Get recent status lines as log."""
        return "\n".join(self._lines)

    def clear(self) -> None:
        """Clear status."""
        self._text = ""
        self._lines = []


# Global instance - import this in chapters and TUI
demo_status = DemoStatus()
