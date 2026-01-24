"""
Tests for TiKV log parser.

Tests the TiDB unified log format parsing per RESEARCH.md Pattern 3.
Format: [timestamp] [LEVEL] [source] [message] [field=value]...
"""

import pytest
from datetime import datetime


class TestParseLogLine:
    """Tests for parse_log_line() function."""

    def test_parse_valid_info_line(self):
        """Parse valid INFO log line returns LogEntry with all fields."""
        from operator_tikv.log_parser import parse_log_line

        line = "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]"

        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == "INFO"
        assert entry.source == "raftstore"
        assert entry.message == "leader changed"
        assert isinstance(entry.timestamp, datetime)

    def test_parse_line_with_multiple_fields(self):
        """Parse log line extracts multiple field=value pairs into dict."""
        from operator_tikv.log_parser import parse_log_line

        line = "[2024/01/15 14:20:11.015 +08:00] [WARN] [scheduler] [transfer leader] [region_id=456] [store_id=1] [peer_id=789]"

        entry = parse_log_line(line)

        assert entry is not None
        assert entry.fields == {
            "region_id": "456",
            "store_id": "1",
            "peer_id": "789",
        }

    def test_parse_line_with_no_fields(self):
        """Parse log line with no fields returns empty fields dict."""
        from operator_tikv.log_parser import parse_log_line

        line = "[2024/01/15 14:20:11.015 +08:00] [DEBUG] [server] [starting up]"

        entry = parse_log_line(line)

        assert entry is not None
        assert entry.fields == {}
        assert entry.message == "starting up"

    def test_parse_empty_line_returns_none(self):
        """Parse empty line returns None."""
        from operator_tikv.log_parser import parse_log_line

        assert parse_log_line("") is None

    def test_parse_malformed_line_returns_none(self):
        """Parse malformed line returns None (doesn't crash)."""
        from operator_tikv.log_parser import parse_log_line

        # Missing brackets
        assert parse_log_line("2024/01/15 INFO something") is None
        # Wrong format
        assert parse_log_line("Just some random text") is None
        # Partial format
        assert parse_log_line("[2024/01/15 14:20:11.015 +08:00]") is None

    def test_parse_different_log_levels(self):
        """Parse handles different log levels (DEBUG, INFO, WARN, ERROR)."""
        from operator_tikv.log_parser import parse_log_line

        levels = ["DEBUG", "INFO", "WARN", "ERROR"]
        for level in levels:
            line = f"[2024/01/15 14:20:11.015 +08:00] [{level}] [test] [message]"
            entry = parse_log_line(line)
            assert entry is not None
            assert entry.level == level

    def test_parse_timestamp_correctly(self):
        """Parse extracts timestamp as datetime object."""
        from operator_tikv.log_parser import parse_log_line

        line = "[2024/01/15 14:20:11.015 +08:00] [INFO] [test] [message]"

        entry = parse_log_line(line)

        assert entry is not None
        assert entry.timestamp.year == 2024
        assert entry.timestamp.month == 1
        assert entry.timestamp.day == 15
        assert entry.timestamp.hour == 14
        assert entry.timestamp.minute == 20
        assert entry.timestamp.second == 11


class TestExtractLeadershipChanges:
    """Tests for extract_leadership_changes() function."""

    def test_extract_filters_leadership_keywords(self):
        """Extract filters for leadership-related log events."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]",
            "[2024/01/15 14:20:12.015 +08:00] [INFO] [server] [request processed]",
            "[2024/01/15 14:20:13.015 +08:00] [INFO] [raftstore] [transfer leader] [region_id=456]",
            "[2024/01/15 14:20:14.015 +08:00] [DEBUG] [gc] [cleanup done]",
        ]

        changes = extract_leadership_changes(lines)

        # Only leadership-related lines should be extracted
        assert len(changes) == 2

    def test_extract_includes_region_id(self):
        """Leadership changes include region_id when present."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]",
        ]

        changes = extract_leadership_changes(lines)

        assert len(changes) == 1
        assert changes[0].region_id == 123

    def test_extract_skips_lines_without_region_id(self):
        """Leadership changes skips lines without region_id field."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            # Has leadership keyword but no region_id
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader election started]",
            # Has both keyword and region_id
            "[2024/01/15 14:20:12.015 +08:00] [INFO] [raftstore] [became leader] [region_id=789]",
        ]

        changes = extract_leadership_changes(lines)

        # Only the line with region_id should be included
        assert len(changes) == 1
        assert changes[0].region_id == 789

    def test_extract_handles_all_leadership_keywords(self):
        """Extract recognizes all leadership-related keywords."""
        from operator_tikv.log_parser import extract_leadership_changes

        # Per CONTEXT.md: "transfer leader", "leader changed", "became leader", "step down", "leader election"
        lines = [
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [transfer leader] [region_id=1]",
            "[2024/01/15 14:20:12.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=2]",
            "[2024/01/15 14:20:13.015 +08:00] [INFO] [raftstore] [became leader] [region_id=3]",
            "[2024/01/15 14:20:14.015 +08:00] [INFO] [raftstore] [step down] [region_id=4]",
            "[2024/01/15 14:20:15.015 +08:00] [INFO] [raftstore] [leader election] [region_id=5]",
        ]

        changes = extract_leadership_changes(lines)

        assert len(changes) == 5
        region_ids = [c.region_id for c in changes]
        assert region_ids == [1, 2, 3, 4, 5]

    def test_extract_preserves_message(self):
        """Leadership change includes the original message."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]",
        ]

        changes = extract_leadership_changes(lines)

        assert changes[0].message == "leader changed"

    def test_extract_preserves_timestamp(self):
        """Leadership change includes parsed timestamp."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [became leader] [region_id=100]",
        ]

        changes = extract_leadership_changes(lines)

        assert changes[0].timestamp.year == 2024
        assert changes[0].timestamp.month == 1
        assert changes[0].timestamp.day == 15

    def test_extract_handles_empty_list(self):
        """Extract handles empty input list."""
        from operator_tikv.log_parser import extract_leadership_changes

        changes = extract_leadership_changes([])

        assert changes == []

    def test_extract_handles_malformed_lines_gracefully(self):
        """Extract skips malformed lines without crashing."""
        from operator_tikv.log_parser import extract_leadership_changes

        lines = [
            "not a valid log line",
            "[2024/01/15 14:20:11.015 +08:00] [INFO] [raftstore] [leader changed] [region_id=123]",
            "another invalid line",
            "",
        ]

        # Should not raise, should extract the valid leadership change
        changes = extract_leadership_changes(lines)

        assert len(changes) == 1
        assert changes[0].region_id == 123


class TestLogEntryType:
    """Tests for LogEntry dataclass."""

    def test_log_entry_has_required_fields(self):
        """LogEntry has timestamp, level, source, message, fields."""
        from operator_tikv.log_parser import LogEntry

        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 14, 20, 11),
            level="INFO",
            source="raftstore",
            message="test message",
            fields={"key": "value"},
        )

        assert entry.timestamp == datetime(2024, 1, 15, 14, 20, 11)
        assert entry.level == "INFO"
        assert entry.source == "raftstore"
        assert entry.message == "test message"
        assert entry.fields == {"key": "value"}


class TestLeadershipChangeType:
    """Tests for LeadershipChange dataclass."""

    def test_leadership_change_has_required_fields(self):
        """LeadershipChange has timestamp, region_id, message."""
        from operator_tikv.log_parser import LeadershipChange

        change = LeadershipChange(
            timestamp=datetime(2024, 1, 15, 14, 20, 11),
            region_id=123,
            message="leader changed",
        )

        assert change.timestamp == datetime(2024, 1, 15, 14, 20, 11)
        assert change.region_id == 123
        assert change.message == "leader changed"
