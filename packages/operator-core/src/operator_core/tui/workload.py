"""
WorkloadTracker for parsing YCSB output and generating sparkline visualization.

This module provides workload throughput tracking and visualization:
- Parses YCSB status output for current ops/sec
- Maintains a sliding window of throughput values
- Generates Unicode sparkline visualization
- Detects throughput degradation against baseline

Per RESEARCH.md Pattern 1: WorkloadTracker with Sparkline Generation
- Uses sparklines library for Unicode bar visualization
- Establishes baseline from first 5 samples (warm-up period)
- Detects degradation when current < baseline * threshold
- Provides Rich markup for panel display
"""

from __future__ import annotations

import re
from collections import deque

from sparklines import sparklines


class WorkloadTracker:
    """
    Tracks workload throughput and generates sparkline visualization.

    Parses YCSB status output for throughput values, maintains a sliding
    window of recent values, and generates color-coded sparkline visualization
    with degradation detection.

    Per RESEARCH.md:
    - YCSB status format: "2017-05-20 18:55:44:512 10 sec: 376385 operations; 37634.74 current ops/sec"
    - Baseline established from first 5 samples
    - Degradation: current < baseline * threshold

    Example:
        tracker = WorkloadTracker()
        for line in ycsb_output:
            ops = tracker.parse_line(line)
            if ops is not None:
                tracker.update(ops)
        panel_content = tracker.format_panel()
    """

    # YCSB status line format: "... 37634.74 current ops/sec"
    YCSB_PATTERN = re.compile(r"(\d+\.?\d*)\s+current ops/sec")

    def __init__(
        self,
        window_size: int = 30,
        degradation_threshold: float = 0.5,
    ) -> None:
        """
        Initialize workload tracker.

        Args:
            window_size: Number of throughput samples to keep in sliding window
            degradation_threshold: Fraction of baseline below which is "degraded"
                                   (0.5 means 50% of baseline)
        """
        self._values: deque[float] = deque(maxlen=window_size)
        self._baseline: float | None = None
        self._threshold = degradation_threshold

    def parse_line(self, line: str) -> float | None:
        """
        Parse YCSB output line for throughput.

        Extracts the "current ops/sec" value from YCSB status output.

        Args:
            line: YCSB status line

        Returns:
            ops/sec value if found, None otherwise
        """
        match = self.YCSB_PATTERN.search(line)
        if match:
            return float(match.group(1))
        return None

    def update(self, ops_per_sec: float) -> None:
        """
        Add new throughput value.

        Establishes baseline from first 5 samples (warm-up period).
        Uses max(0.1, value) to avoid zero values per RESEARCH.md Pitfall 1.

        Args:
            ops_per_sec: Current throughput value
        """
        # Floor at 0.1 to avoid sparkline issues with zero values
        value = max(0.1, ops_per_sec)
        self._values.append(value)

        # Establish baseline from warm-up period (first 5 samples)
        if self._baseline is None and len(self._values) >= 5:
            self._baseline = sum(list(self._values)[:5]) / 5

    def is_degraded(self) -> bool:
        """
        Check if current throughput is degraded vs baseline.

        Returns:
            True if current value is below baseline * threshold,
            False if no data, no baseline, or throughput is normal
        """
        if not self._values or self._baseline is None:
            return False
        current = self._values[-1]
        return current < (self._baseline * self._threshold)

    def get_sparkline(self) -> str:
        """
        Generate sparkline from throughput history.

        Uses sparklines library to create Unicode bar visualization.

        Returns:
            Unicode sparkline string, empty if no data
        """
        if not self._values:
            return ""
        # sparklines() returns generator of lines, we want single line
        lines = list(sparklines(list(self._values)))
        return lines[0] if lines else ""

    def format_panel(self) -> str:
        """
        Format workload panel content with sparkline and status.

        Creates Rich markup with:
        - Color-coded sparkline (green normal, red degraded)
        - Current ops/sec value
        - Status indicator

        Returns:
            Rich markup string for workload panel
        """
        if not self._values:
            return "[dim]Waiting for workload data...[/dim]"

        current = self._values[-1]
        sparkline = self.get_sparkline()

        # Color based on degradation
        if self.is_degraded():
            color = "red"
            status = "[bold red]DEGRADED[/bold red]"
        else:
            color = "green"
            status = "[green]Normal[/green]"

        return (
            f"[{color}]{sparkline}[/{color}]\n\n"
            f"Current: [bold]{current:.0f}[/bold] ops/sec\n"
            f"Status: {status}"
        )
