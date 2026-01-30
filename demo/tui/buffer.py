"""
OutputBuffer for capturing daemon output.

This module implements a ring buffer for storing the most recent lines
of output from daemon subprocesses. Uses collections.deque with maxlen
for automatic oldest-removal when the buffer is full.

Per RESEARCH.md Pattern 3: OutputBuffer with deque
- Uses deque(maxlen=N) for automatic oldest-removal
- Thread-safe append operations (deque guarantee in CPython)
- Strips trailing newlines on append for consistent storage
"""

from collections import deque
from collections.abc import Iterator


class OutputBuffer:
    """
    Fixed-size ring buffer for capturing daemon output.

    Thread-safe for append operations (deque guarantee in CPython).
    Automatically discards oldest lines when full.

    Example:
        buffer = OutputBuffer(maxlen=50)
        buffer.append("line 1")
        buffer.append("line 2")
        print(buffer.get_text())  # "line 1\\nline 2"
    """

    def __init__(self, maxlen: int = 50) -> None:
        """
        Initialize buffer with maximum line count.

        Args:
            maxlen: Maximum number of lines to store (default 50)
        """
        self._buffer: deque[str] = deque(maxlen=maxlen)

    def append(self, line: str) -> None:
        """
        Add a line to the buffer.

        Strips trailing newline if present. When buffer is full,
        oldest line is automatically removed.

        Args:
            line: Line of text to add
        """
        self._buffer.append(line.rstrip("\n"))

    def get_lines(self, n: int | None = None) -> list[str]:
        """
        Get last n lines (or all if n is None).

        Args:
            n: Number of lines to return, or None for all lines

        Returns:
            List of lines, newest last
        """
        lines = list(self._buffer)
        if n is not None:
            return lines[-n:]
        return lines

    def get_text(self, n: int | None = None) -> str:
        """
        Get lines as newline-joined string.

        Args:
            n: Number of lines to return, or None for all lines

        Returns:
            Lines joined with newlines
        """
        return "\n".join(self.get_lines(n))

    def __len__(self) -> int:
        """Return number of lines in buffer."""
        return len(self._buffer)

    def __iter__(self) -> Iterator[str]:
        """Iterate over lines in buffer."""
        return iter(self._buffer)

    def clear(self) -> None:
        """Clear all lines from buffer."""
        self._buffer.clear()
