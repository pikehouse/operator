# Stack Research: TUI Demo

**Focus:** Multi-panel TUI with live subprocess output and sparkline visualizations
**Researched:** 2026-01-24
**Overall Confidence:** HIGH (verified with PyPI and official documentation)

---

## Current Stack (Existing)

These are already in use and should NOT be changed:

| Package | Version | Purpose |
|---------|---------|---------|
| Python | 3.11+ | Runtime |
| Rich | >=14.0.0 | CLI output, panels, console |
| Typer | >=0.21.0 | CLI framework |
| asyncio | stdlib | Async operations |
| aiosqlite | >=0.20.0 | Ticket database |
| httpx | >=0.27.0 | HTTP client |
| anthropic | >=0.40.0 | AI integration |
| python-on-whales | >=0.70.0 | Docker/compose |

**Current Rich Usage** (from `chaos.py`):
- `Console` for output
- `Live` for countdown display
- `Panel` for diagnosis display
- `Markdown` for formatted text
- `Text` for styled strings

---

## Additions for v1.1

### Core: No New Framework Required

**Recommendation: Stay with Rich, do NOT add Textual**

The existing `rich.live.Live` + `rich.layout.Layout` combination provides everything needed for a multi-panel TUI dashboard. Adding Textual would:
- Require rewriting existing `ChaosDemo` code
- Add significant dependency weight (~2x memory overhead)
- Introduce unnecessary complexity for a demo that doesn't need interactive widgets

Rich 14.x (current: 14.3.1 as of 2026-01-24) already includes:
- `Layout` class for multi-panel screen division
- `Live` for real-time updates at configurable refresh rates
- `Panel` for bordered content areas
- Full asyncio compatibility

**Integration pattern:**
```python
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

layout = Layout()
layout.split_row(
    Layout(name="left", ratio=1),
    Layout(name="right", ratio=2),
)
layout["right"].split_column(
    Layout(name="monitor"),
    Layout(name="agent"),
)

with Live(layout, refresh_per_second=4) as live:
    # Update panels asynchronously
    layout["left"].update(Panel("Cluster Status"))
```

### Keyboard Input: readchar

- **readchar** (4.2.1) - Single-character keyboard capture
  - Why: Minimal dependency for press-any-key progression
  - Integration: Works alongside `Live` context, non-blocking pattern required
  - PyPI: https://pypi.org/project/readchar/

**Why readchar over alternatives:**
- `pynput` is overkill (designed for system-wide keyboard hooks)
- `getch` is outdated and unmaintained
- `readchar` is focused on terminal input, cross-platform, actively maintained

**Non-blocking pattern with Rich Live:**
```python
import asyncio
import sys
import select
from readchar import readkey, key

async def check_keypress():
    """Check for keypress without blocking."""
    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        return readkey()
    return None
```

### Sparklines/Histograms: sparklines

- **sparklines** (0.7.0) - Unicode sparkline visualization
  - Why: Lightweight, no dependencies, outputs strings that render in Rich panels
  - Integration: Returns string that can be wrapped in `Text` or `Panel`
  - PyPI: https://pypi.org/project/sparklines/

**Usage pattern:**
```python
from sparklines import sparklines

# ops/sec data for last 20 seconds
ops_history = [450, 520, 480, 510, 530, 490, 500, 515, ...]
chart = sparklines(ops_history)[0]  # Returns: "▃▇▅▆▇▄▅▆"
panel = Panel(chart, title="ops/sec")
```

**Why sparklines over alternatives:**
- `asciichartpy` (1.5.25) is stale (last update 2020), designed for line charts not histograms
- `plotext` is full-featured but heavy, overkill for simple metrics
- `termgraph` requires more setup, designed for standalone output not embedding
- `sparklines` is focused, lightweight, actively maintained (June 2025)

### Subprocess Output Capture: asyncio.subprocess (stdlib)

No additional dependency needed. Use `asyncio.create_subprocess_exec` with `PIPE`.

**Pattern for live output capture:**
```python
async def stream_subprocess(cmd: list[str], output_callback):
    """Stream subprocess stdout line-by-line."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async for line in proc.stdout:
        await output_callback(line.decode().rstrip())

    await proc.wait()
```

**Why no additional library:**
- `asyncio.subprocess` is stdlib, already using asyncio
- Avoids adding dependencies for built-in functionality
- Full async support with `async for` pattern
- Handles both stdout and stderr

---

## Summary: Additions

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| readchar | ^4.2.1 | Key-press input | Minimal, focused, cross-platform |
| sparklines | ^0.7.0 | ops/sec visualization | Lightweight, no deps, string output |

**Installation:**
```bash
uv add readchar sparklines
```

**Total new dependencies:** 2 (both are zero-dependency packages)

---

## Rejected Alternatives

| Option | Why Not |
|--------|---------|
| **Textual** | Full TUI framework is overkill for a demo dashboard. Adds memory overhead (~2x), requires code rewrite, introduces event loop complexity. Rich's `Live` + `Layout` is sufficient. |
| **pynput** | System-wide keyboard hooks are unnecessary. `readchar` is simpler for terminal-only input. |
| **curses** | Low-level, not compatible with Rich rendering. Would require abandoning existing Rich usage. |
| **plotext** | Full charting library is overkill for simple sparklines. Heavy dependency. |
| **asciichartpy** | Stale (last update 2020), designed for line charts not compact histograms. |
| **blessed/blessings** | Another terminal library would conflict with Rich. Unnecessary abstraction layer. |
| **termgraph** | Designed for CLI output, not embedding in Rich panels. Requires more setup. |
| **aconsole** | Tkinter-based, wrong paradigm for terminal TUI. |

---

## Key Patterns

### Pattern 1: Multi-Panel Layout with Live Updates

```python
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

def create_layout() -> Layout:
    """Create the multi-panel TUI layout."""
    layout = Layout()

    # Top-level: left status column, right content column
    layout.split_row(
        Layout(name="status", size=30),
        Layout(name="content"),
    )

    # Right column: monitor, agent, metrics stacked
    layout["content"].split_column(
        Layout(name="monitor", ratio=2),
        Layout(name="agent", ratio=2),
        Layout(name="metrics", size=5),
    )

    # Left column: cluster status, narration
    layout["status"].split_column(
        Layout(name="cluster", size=10),
        Layout(name="narration"),
    )

    return layout
```

### Pattern 2: Async Subprocess to Panel

```python
from collections import deque
import asyncio

class OutputBuffer:
    """Ring buffer for subprocess output lines."""
    def __init__(self, max_lines: int = 20):
        self.lines: deque[str] = deque(maxlen=max_lines)

    def append(self, line: str):
        self.lines.append(line)

    def render(self) -> str:
        return "\n".join(self.lines)

async def run_subprocess_with_panel(
    cmd: list[str],
    buffer: OutputBuffer,
    layout: Layout,
    panel_name: str,
):
    """Run subprocess and stream output to a layout panel."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async for line in proc.stdout:
        buffer.append(line.decode().rstrip())
        layout[panel_name].update(
            Panel(buffer.render(), title=panel_name.title())
        )

    await proc.wait()
```

### Pattern 3: Non-Blocking Keypress with asyncio

```python
import asyncio
import sys
import select
from typing import Optional

async def poll_keypress() -> Optional[str]:
    """Non-blocking check for keypress (Unix only)."""
    # Use select to check if stdin has data
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return sys.stdin.read(1)
    return None

async def run_with_key_handling(layout: Layout, live: Live):
    """Main loop with key handling."""
    while True:
        key = await poll_keypress()
        if key == "q":
            break
        elif key == " " or key == "\n":
            # Advance narration
            advance_narration()

        # Let other tasks run
        await asyncio.sleep(0.1)
```

### Pattern 4: Sparkline Metrics Panel

```python
from collections import deque
from sparklines import sparklines
from rich.panel import Panel
from rich.text import Text

class MetricsTracker:
    """Track and visualize ops/sec metrics."""
    def __init__(self, window: int = 30):
        self.history: deque[float] = deque(maxlen=window)

    def record(self, ops_per_sec: float):
        self.history.append(ops_per_sec)

    def render_panel(self) -> Panel:
        if not self.history:
            return Panel("No data", title="Metrics")

        chart = sparklines(list(self.history))[0]
        current = self.history[-1]
        avg = sum(self.history) / len(self.history)

        content = Text()
        content.append(f"ops/sec: {current:.0f} (avg: {avg:.0f})\n")
        content.append(chart)

        return Panel(content, title="Workload")
```

### Pattern 5: Coordinating Multiple Async Tasks with Live

```python
async def run_demo_dashboard():
    """Main entry point for TUI demo."""
    console = Console()
    layout = create_layout()

    # Buffers for subprocess output
    monitor_buffer = OutputBuffer()
    agent_buffer = OutputBuffer()
    metrics = MetricsTracker()

    async def update_loop():
        """Refresh layout panels at regular intervals."""
        while True:
            layout["monitor"].update(
                Panel(monitor_buffer.render(), title="Monitor")
            )
            layout["agent"].update(
                Panel(agent_buffer.render(), title="Agent")
            )
            layout["metrics"].update(metrics.render_panel())
            await asyncio.sleep(0.25)

    with Live(layout, console=console, refresh_per_second=4) as live:
        # Run all tasks concurrently
        await asyncio.gather(
            run_subprocess_with_panel(
                ["operator", "monitor", "run"],
                monitor_buffer, layout, "monitor"
            ),
            run_subprocess_with_panel(
                ["operator", "agent", "run"],
                agent_buffer, layout, "agent"
            ),
            update_loop(),
            run_with_key_handling(layout, live),
        )
```

---

## Integration Notes

### With Existing Code

1. **Console reuse**: The existing `ChaosDemo` uses `Console()`. The new TUI should share or replace this console.

2. **Live context nesting**: Rich supports nested `Live` contexts but this adds complexity. Better to have one `Live` context for the entire dashboard.

3. **Typer compatibility**: The demo command should remain a Typer command. The TUI runs within the command, not replacing Typer.

### Platform Considerations

- **readchar**: Works on macOS, Linux, Windows
- **sparklines**: Pure Python, works everywhere
- **select.select for stdin**: Unix only. For Windows, use `msvcrt.kbhit()`:

```python
import sys

if sys.platform == "win32":
    import msvcrt
    def has_keypress() -> bool:
        return msvcrt.kbhit()
    def get_keypress() -> str:
        return msvcrt.getch().decode()
else:
    import select
    def has_keypress() -> bool:
        return bool(select.select([sys.stdin], [], [], 0.0)[0])
    def get_keypress() -> str:
        return sys.stdin.read(1)
```

---

## Sources

- [Rich PyPI](https://pypi.org/project/rich/) - Version 14.3.1, verified 2026-01-24
- [Rich Live Display Docs](https://rich.readthedocs.io/en/latest/live.html) - Official documentation
- [Rich Layout Docs](https://rich.readthedocs.io/en/latest/layout.html) - Official documentation
- [readchar PyPI](https://pypi.org/project/readchar/) - Version 4.2.1
- [sparklines PyPI](https://pypi.org/project/sparklines/) - Version 0.7.0
- [Textual PyPI](https://pypi.org/project/textual/) - Version 7.3.0 (rejected alternative)
- [Python asyncio-subprocess Docs](https://docs.python.org/3/library/asyncio-subprocess.html) - Official documentation
- [Rich Terminal Dashboards Blog](https://www.willmcgugan.com/blog/tech/post/building-rich-terminal-dashboards/) - Will McGugan
- [Rich + asyncio Discussion](https://github.com/Textualize/rich/discussions/1401) - GitHub
