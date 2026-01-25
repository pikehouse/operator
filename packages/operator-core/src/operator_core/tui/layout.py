"""
Layout factory for 5-panel TUI dashboard.

This module provides the layout structure for the demo TUI:
- create_layout(): Creates the 5-panel layout structure
- make_panel(): Helper for creating styled panels

Per RESEARCH.md Pattern 1: Nested Layout Splits
- Uses split_row() and split_column() for nested structure
- Fixed sizes for cluster (35 cols), narration (5 rows), workload (8 rows)
- Flexible ratio=1 for monitor and agent panels

Layout structure:
+------------------+----------------------------------------+
|                  |  Narration (5 rows fixed)              |
|  Cluster Status  +----------------------------------------+
|  (35 cols fixed) |  Monitor Output (ratio=1, flex)        |
|                  +----------------------------------------+
|                  |  Agent Output (ratio=1, flex)          |
|                  +----------------------------------------+
|                  |  Workload (8 rows fixed)               |
+------------------+----------------------------------------+
"""

from rich.layout import Layout
from rich.panel import Panel


def create_layout() -> Layout:
    """
    Create the 5-panel TUI layout structure.

    Returns a Layout with the following named regions:
    - cluster: Left column, 35 characters wide (fixed)
    - narration: Top-right, 5 rows (fixed)
    - monitor: Middle-right, flexible height (ratio=1)
    - agent: Middle-right, flexible height (ratio=1)
    - workload: Bottom-right, 8 rows (fixed)

    Access panels via:
    - layout["cluster"]
    - layout["main"]["narration"]
    - layout["main"]["monitor"]
    - layout["main"]["agent"]
    - layout["main"]["workload"]

    Returns:
        Layout with 5 named panel regions
    """
    layout = Layout(name="root")

    # Main split: left column (cluster) + right column (main)
    layout.split_row(
        Layout(name="cluster", size=35),
        Layout(name="main"),
    )

    # Right column splits into 4 rows
    layout["main"].split_column(
        Layout(name="narration", size=5),
        Layout(name="monitor", ratio=1),
        Layout(name="agent", ratio=1),
        Layout(name="workload", size=8),
    )

    return layout


def make_panel(content: str, title: str, style: str = "blue") -> Panel:
    """
    Create a styled panel with content.

    Args:
        content: Text content for the panel
        title: Panel title (will be bolded)
        style: Border style color (default "blue")

    Returns:
        Panel with formatted title and border style
    """
    return Panel(
        content,
        title=f"[bold]{title}[/bold]",
        border_style=style,
        padding=(0, 1),
    )


def make_cluster_panel(
    content: str,
    has_issues: bool = False,
    detection_active: bool = False,
) -> Panel:
    """
    Create a styled cluster panel with detection highlighting.

    Per RESEARCH.md Pattern 4: Detection Highlighting via Border Color.

    Args:
        content: Rich markup content for the panel
        has_issues: True if any node is not UP
        detection_active: True if monitor recently detected a violation

    Returns:
        Panel with appropriate border style:
        - detection_active: bold red border, "!" in title
        - has_issues: yellow border
        - all healthy: cyan border (default)
    """
    if detection_active:
        # Monitor detected an issue - emphasize with red border
        border_style = "bold red"
        title = "[bold red]! Cluster Status ![/bold red]"
    elif has_issues:
        # Cluster has issues but no active detection
        border_style = "yellow"
        title = "[bold yellow]Cluster Status[/bold yellow]"
    else:
        # All healthy
        border_style = "cyan"
        title = "[bold cyan]Cluster Status[/bold cyan]"

    return Panel(
        content,
        title=title,
        border_style=border_style,
        padding=(0, 1),
    )
