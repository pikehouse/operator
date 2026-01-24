"""
TiKV log parser for extracting leadership change events.

This module parses TiDB unified log format per RESEARCH.md Pattern 3.
Format: [timestamp] [LEVEL] [source] [message] [field=value]...

Per CONTEXT.md decisions:
- Purpose: context for AI diagnosis only (not independent alerting)
- Event types: leadership changes only (simplest viable)
- Match keywords: "transfer leader", "leader changed", "became leader",
                  "step down", "leader election"

Per RESEARCH.md Pitfall 5:
- Parse timezone from log format for accurate timestamps
- For Phase 2, use naive datetime (timezone handling can be added later)
"""

import re
from dataclasses import dataclass
from datetime import datetime


# TiDB unified log format pattern
# Format: [timestamp] [LEVEL] [source] [message] [field=value]...
# Example: [2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]
LOG_PATTERN = re.compile(
    r"\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{2}:\d{2})\] "  # timestamp
    r"\[(\w+)\] "  # level
    r"\[([^\]]+)\] "  # source
    r"\[([^\]]*)\]"  # message
    r"(.*)?$"  # optional fields
)

# Pattern for extracting field=value pairs
FIELD_PATTERN = re.compile(r"\[(\w+)=([^\]]+)\]")

# Leadership-related keywords per CONTEXT.md
LEADERSHIP_KEYWORDS = [
    "transfer leader",
    "leader changed",
    "became leader",
    "step down",
    "leader election",
]


@dataclass
class LogEntry:
    """
    Parsed log line from TiKV/TiDB unified log format.

    Attributes:
        timestamp: Datetime when the log was recorded (naive, local to log source)
        level: Log level (DEBUG, INFO, WARN, ERROR)
        source: Component that emitted the log (e.g., "raftstore", "server")
        message: The log message content
        fields: Dict of field=value pairs from the log line
    """

    timestamp: datetime
    level: str
    source: str
    message: str
    fields: dict[str, str]


@dataclass
class LeadershipChange:
    """
    Leadership change event extracted from TiKV logs.

    Attributes:
        timestamp: When the leadership change occurred
        region_id: The region that had a leadership change
        message: The original log message describing the change
    """

    timestamp: datetime
    region_id: int
    message: str


def parse_log_line(line: str) -> LogEntry | None:
    """
    Parse a single TiKV log line into structured data.

    Handles TiDB unified log format:
    [timestamp] [LEVEL] [source] [message] [field=value]...

    Args:
        line: Raw log line string

    Returns:
        LogEntry if line matches expected format, None otherwise.
        Returns None for empty lines, malformed lines, or unexpected formats.
        This ensures graceful handling without crashing.
    """
    if not line or not line.strip():
        return None

    match = LOG_PATTERN.match(line)
    if not match:
        return None

    timestamp_str, level, source, message, fields_str = match.groups()

    # Parse timestamp: 2024/01/15 14:20:11.015 +08:00
    # We extract just the datetime part without timezone for Phase 2
    # (timezone handling can be added later per RESEARCH.md Pitfall 5)
    try:
        timestamp = datetime.strptime(timestamp_str[:23], "%Y/%m/%d %H:%M:%S.%f")
    except ValueError:
        return None

    # Parse fields
    fields: dict[str, str] = {}
    if fields_str:
        for field_match in FIELD_PATTERN.finditer(fields_str):
            fields[field_match.group(1)] = field_match.group(2)

    return LogEntry(
        timestamp=timestamp,
        level=level,
        source=source,
        message=message,
        fields=fields,
    )


def extract_leadership_changes(lines: list[str]) -> list[LeadershipChange]:
    """
    Extract leadership change events from TiKV logs.

    Filters log lines for leadership-related keywords and extracts
    structured LeadershipChange events for AI diagnosis context.

    Per CONTEXT.md decisions:
    - Match keywords: "transfer leader", "leader changed", "became leader",
                      "step down", "leader election"
    - Requires region_id field (skips lines without it)

    Args:
        lines: List of raw log line strings

    Returns:
        List of LeadershipChange events with timestamp, region_id, and message.
        Lines without region_id are skipped (not useful for diagnosis).
    """
    changes: list[LeadershipChange] = []

    for line in lines:
        # Check if line mentions leadership (case-insensitive)
        line_lower = line.lower()
        if not any(kw in line_lower for kw in LEADERSHIP_KEYWORDS):
            continue

        # Parse the log line
        entry = parse_log_line(line)
        if entry is None:
            continue

        # Extract region_id - skip if not present
        region_id_str = entry.fields.get("region_id")
        if region_id_str is None:
            continue

        # Parse region_id as int
        try:
            region_id = int(region_id_str)
        except ValueError:
            continue

        changes.append(
            LeadershipChange(
                timestamp=entry.timestamp,
                region_id=region_id,
                message=entry.message,
            )
        )

    return changes
