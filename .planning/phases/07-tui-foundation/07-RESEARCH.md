# Phase 7: TUI Foundation - Research

**Researched:** 2026-01-24
**Domain:** Multi-panel terminal dashboard with Rich Layout + Live
**Confidence:** HIGH

## Summary

This phase establishes the multi-panel TUI layout with proper terminal management and async coordination. The research confirms that Rich's Layout and Live APIs are well-suited for this task, with clear patterns for nested panel structures, dynamic content updates, and context-managed terminal state.

The primary technical challenges are:
1. Creating a 5-panel layout (cluster, monitor, agent, workload, narration) using nested Layout splits
2. Managing terminal state with proper signal handlers to prevent corruption on Ctrl+C
3. Coordinating multiple async tasks using TaskGroup for automatic cancellation on error
4. Implementing an OutputBuffer class using deque(maxlen=N) for ring buffer semantics

All patterns are well-documented in official sources. The existing codebase already demonstrates the signal handling pattern in `MonitorLoop`, which can be adapted for the TUI context.

**Primary recommendation:** Use Rich Layout with nested splits (split_column then split_row), wrap everything in a Live context manager, and register signal handlers BEFORE entering the Live context to ensure terminal restoration on exit.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rich | >=14.0.0 | Layout, Live, Panel, Text rendering | Already in use, full-featured, well-documented |
| asyncio | stdlib | TaskGroup, signal handlers, event coordination | Python 3.11+ has TaskGroup, stdlib stability |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| collections.deque | stdlib | Ring buffer (OutputBuffer) with maxlen | Fixed-size buffers with O(1) append/pop, thread-safe |
| signal | stdlib | SIGINT/SIGTERM handlers | Terminal state restoration before exit |
| functools | stdlib | functools.partial for signal handlers | Lambda binding alternative, existing pattern |

### Future Phases (Not This Phase)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| readchar | 4.2.1 | Single keypress reading | Phase: Keyboard navigation |
| sparklines | 0.7.0 | Ops/sec visualization | Phase: Workload visualization |

**Installation:**
No new dependencies needed for this phase. Rich and asyncio are already available.

## Architecture Patterns

### Recommended Project Structure
```
operator_core/
└── tui/
    ├── __init__.py
    ├── layout.py       # Layout factory, panel creators
    ├── buffer.py       # OutputBuffer class
    └── controller.py   # TUIController class with TaskGroup
```

### Pattern 1: Nested Layout Splits
**What:** Create 5-panel layout using column-first, then row splits
**When to use:** Multi-region dashboard layouts
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/layout.html
from rich.layout import Layout
from rich.panel import Panel

def create_layout() -> Layout:
    """Create 5-panel layout: left column, right column with 4 rows."""
    layout = Layout(name="root")

    # Split into left (cluster) and right (main content)
    layout.split_row(
        Layout(name="left", size=30),
        Layout(name="right"),
    )

    # Right side splits into 4 rows
    layout["right"].split_column(
        Layout(name="narration", size=5),
        Layout(name="monitor", ratio=1),
        Layout(name="agent", ratio=1),
        Layout(name="workload", size=8),
    )

    return layout
```

### Pattern 2: Layout Content Updates
**What:** Update panel content dynamically without recreating layout
**When to use:** Refreshing panel content in Live context
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/layout.html
from rich.panel import Panel
from rich.text import Text

def update_panel(layout: Layout, name: str, content: str, title: str) -> None:
    """Update a named panel's content."""
    layout[name].update(
        Panel(
            Text(content),
            title=title,
            border_style="blue",
        )
    )
```

### Pattern 3: OutputBuffer with deque
**What:** Fixed-size ring buffer for capturing subprocess output
**When to use:** Storing last N lines of daemon output
**Example:**
```python
# Source: https://docs.python.org/3/library/collections.html#collections.deque
from collections import deque

class OutputBuffer:
    """Thread-safe ring buffer for capturing output lines."""

    def __init__(self, maxlen: int = 50) -> None:
        self._buffer: deque[str] = deque(maxlen=maxlen)

    def append(self, line: str) -> None:
        """Add line to buffer; oldest line auto-removed if full."""
        self._buffer.append(line)

    def get_lines(self) -> list[str]:
        """Return copy of buffer contents."""
        return list(self._buffer)

    def clear(self) -> None:
        """Clear all lines."""
        self._buffer.clear()
```

### Pattern 4: Live Context with Signal Handlers
**What:** Register signal handlers BEFORE entering Live to ensure cleanup
**When to use:** Any Live-based TUI that must handle Ctrl+C gracefully
**Example:**
```python
# Source: Adapted from existing MonitorLoop + Rich docs
import asyncio
import functools
import signal
from rich.console import Console
from rich.live import Live
from rich.layout import Layout

class TUIController:
    """Controls TUI lifecycle with proper signal handling."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._shutdown = asyncio.Event()
        self._layout = create_layout()

    async def run(self) -> None:
        """Run TUI with signal handling."""
        loop = asyncio.get_running_loop()

        # Register signal handlers BEFORE Live context
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig),
            )

        # Live context ensures terminal restoration
        with Live(
            self._layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,  # Don't use alternate screen for demo
        ) as live:
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._update_loop(live))
                    # More tasks added in later phases
                    await self._shutdown.wait()
            except* Exception:
                pass  # TaskGroup handles cancellation

        # Terminal is restored here by Live.__exit__

    def _handle_signal(self, sig: signal.Signals) -> None:
        """Set shutdown event on signal."""
        self._shutdown.set()

    async def _update_loop(self, live: Live) -> None:
        """Main update loop at 4fps."""
        while not self._shutdown.is_set():
            self._refresh_panels()
            live.refresh()
            await asyncio.sleep(0.25)  # 4fps

    def _refresh_panels(self) -> None:
        """Update all panel contents."""
        # Implemented in later phases
        pass
```

### Pattern 5: TaskGroup for Async Coordination
**What:** Use TaskGroup instead of gather() for automatic sibling cancellation
**When to use:** Multiple concurrent tasks that should all stop if one fails
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-task.html#task-groups
import asyncio

async def run_with_taskgroup() -> None:
    """TaskGroup automatically cancels siblings on any exception."""
    shutdown = asyncio.Event()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(task_one(shutdown))
        tg.create_task(task_two(shutdown))
        tg.create_task(task_three(shutdown))
        # If any task raises (except CancelledError), others are cancelled
        # All exceptions collected into ExceptionGroup
```

### Anti-Patterns to Avoid
- **Using asyncio.gather() for daemon tasks:** gather() doesn't cancel siblings on exception. Use TaskGroup.
- **Registering signals inside Live context:** If Ctrl+C hits before handler is registered, terminal state may corrupt.
- **Using print() inside Live context:** Use `live.console.print()` to avoid output interleaving.
- **Using asyncio.sleep() for shutdown waits:** Use Event.wait() with timeout so signals can interrupt.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Ring buffer | Custom linked list | `deque(maxlen=N)` | O(1) operations, thread-safe, stdlib |
| Terminal restore | Manual termios | `with Live():` context | Rich handles all edge cases |
| Task cancellation | Manual cancel loops | `asyncio.TaskGroup` | Automatic sibling cancellation, ExceptionGroup |
| Signal handlers | atexit module | `loop.add_signal_handler()` | atexit doesn't catch SIGTERM, signals do |
| Panel layout | Custom grid math | `Layout.split_row/column()` | Rich handles resize, ratios |

**Key insight:** Terminal management and async coordination have many edge cases (raw mode, alternate screen, zombie tasks). Using context managers and TaskGroup eliminates entire categories of bugs.

## Common Pitfalls

### Pitfall 1: Terminal State Corruption on Ctrl+C
**What goes wrong:** User presses Ctrl+C, terminal has no echo, stuck cursor, mangled prompt
**Why it happens:** Live enters raw mode or alternate screen; exit handler doesn't run
**How to avoid:**
1. Register signal handlers BEFORE entering Live context
2. Signal handler sets shutdown Event (doesn't exit directly)
3. Let Live context manager exit cleanly
**Warning signs:** Manual testing with Ctrl+C leaves terminal unusable

### Pitfall 2: Signal Handler Registered Too Late
**What goes wrong:** First Ctrl+C during startup crashes with KeyboardInterrupt, terminal corrupt
**Why it happens:** Signal handler added after Live context entered
**How to avoid:** Signal handler registration is the FIRST thing in run(), before any context managers
**Warning signs:** Quick Ctrl+C during startup shows different behavior than later

### Pitfall 3: asyncio.gather() Leaves Zombie Tasks
**What goes wrong:** One task crashes, others keep running, resources leaked
**Why it happens:** gather() with return_exceptions=True catches but doesn't cancel
**How to avoid:** Use TaskGroup (Python 3.11+) which cancels siblings automatically
**Warning signs:** Exception in one task, other tasks continue logging

### Pitfall 4: Blocking Event.wait() Without Timeout
**What goes wrong:** Shutdown event never fires, program hangs
**Why it happens:** No timeout, no way to break out
**How to avoid:** Use wait_for with timeout, continue loop on timeout
**Warning signs:** Ctrl+C doesn't exit, have to kill -9

### Pitfall 5: Print Inside Live Context
**What goes wrong:** Output interleaved with Live display, visual artifacts
**Why it happens:** print() and Live use different output streams
**How to avoid:** Always use `live.console.print()` for any output during Live
**Warning signs:** Flicker, duplicate lines, garbled output

### Pitfall 6: Layout Ratio Confusion
**What goes wrong:** Panels have unexpected sizes
**Why it happens:** Mixing size (fixed) with ratio (proportional) without understanding
**How to avoid:** Use `size` for fixed-height panels, `ratio` for flexible. Ratio 2 gets 2x space of ratio 1.
**Warning signs:** Panels too small or too large after terminal resize

## Code Examples

Verified patterns from official sources:

### Complete 5-Panel Layout
```python
# Source: https://rich.readthedocs.io/en/stable/layout.html
from rich.layout import Layout
from rich.panel import Panel

def create_demo_layout() -> Layout:
    """
    Create the 5-panel TUI layout:

    +------------------+----------------------------------------+
    |                  |  Narration (5 rows)                    |
    |  Cluster Status  +----------------------------------------+
    |  (30 cols fixed) |  Monitor Output (flex)                 |
    |                  +----------------------------------------+
    |                  |  Agent Output (flex)                   |
    |                  +----------------------------------------+
    |                  |  Workload (8 rows)                     |
    +------------------+----------------------------------------+
    """
    layout = Layout(name="root")

    # Main split: left column (cluster) + right column (everything else)
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
    """Create a styled panel with content."""
    return Panel(
        content,
        title=f"[bold]{title}[/bold]",
        border_style=style,
        padding=(0, 1),
    )
```

### Signal-Safe TUI Runner
```python
# Source: Adapted from existing MonitorLoop + asyncio docs
import asyncio
import functools
import signal
from rich.console import Console
from rich.live import Live

async def run_tui(console: Console) -> None:
    """Run TUI with proper signal handling."""
    shutdown = asyncio.Event()
    layout = create_demo_layout()

    def handle_signal(sig: signal.Signals) -> None:
        console.print(f"\n[yellow]Received {sig.name}, shutting down...[/yellow]")
        shutdown.set()

    # Register BEFORE Live context
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, functools.partial(handle_signal, sig))

    # Initialize panels with placeholder content
    layout["cluster"].update(make_panel("Loading...", "Cluster Status", "cyan"))
    layout["narration"].update(make_panel("Welcome to the demo", "Chapter", "magenta"))
    layout["monitor"].update(make_panel("Waiting for monitor...", "Monitor", "blue"))
    layout["agent"].update(make_panel("Waiting for agent...", "Agent", "green"))
    layout["workload"].update(make_panel("Waiting for workload...", "Workload", "yellow"))

    with Live(layout, console=console, refresh_per_second=4) as live:
        while not shutdown.is_set():
            # Update panel contents here
            live.refresh()
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass  # Normal refresh interval

    console.print("[green]TUI shutdown complete[/green]")
```

### OutputBuffer Implementation
```python
# Source: https://docs.python.org/3/library/collections.html#collections.deque
from collections import deque
from typing import Iterator

class OutputBuffer:
    """
    Fixed-size ring buffer for capturing daemon output.

    Thread-safe for append operations (deque guarantee in CPython).
    Automatically discards oldest lines when full.
    """

    def __init__(self, maxlen: int = 50) -> None:
        """Initialize buffer with maximum line count."""
        self._buffer: deque[str] = deque(maxlen=maxlen)

    def append(self, line: str) -> None:
        """Add a line to the buffer."""
        # Strip trailing newline if present
        self._buffer.append(line.rstrip('\n'))

    def get_lines(self, n: int | None = None) -> list[str]:
        """Get last n lines (or all if n is None)."""
        lines = list(self._buffer)
        if n is not None:
            return lines[-n:]
        return lines

    def get_text(self, n: int | None = None) -> str:
        """Get lines as newline-joined string."""
        return '\n'.join(self.get_lines(n))

    def __len__(self) -> int:
        """Return number of lines in buffer."""
        return len(self._buffer)

    def __iter__(self) -> Iterator[str]:
        """Iterate over lines."""
        return iter(self._buffer)

    def clear(self) -> None:
        """Clear all lines."""
        self._buffer.clear()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| asyncio.gather() | asyncio.TaskGroup | Python 3.11 | Automatic sibling cancellation on exception |
| Manual deque management | deque(maxlen=N) | Long-standing | Automatic oldest-removal |
| signal.signal() | loop.add_signal_handler() | asyncio adoption | Safe async signal handling |

**Deprecated/outdated:**
- `asyncio.get_event_loop()`: Use `asyncio.get_running_loop()` inside async functions
- `loop.run_until_complete()`: Use `asyncio.run()` at top level

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal refresh rate for subprocess output**
   - What we know: Rich docs suggest 4fps default, research says 4-10fps
   - What's unclear: Ideal rate depends on subprocess output frequency
   - Recommendation: Start with 4fps, make configurable, tune during testing

2. **Panel size ratios for readability**
   - What we know: Fixed sizes for header (5) and footer (8), flex for middle
   - What's unclear: Exact column width (30-35 chars) for cluster panel
   - Recommendation: Start with 35 chars, adjust based on content width

## Sources

### Primary (HIGH confidence)
- [Rich Layout Documentation](https://rich.readthedocs.io/en/stable/layout.html) - split_row, split_column, size, ratio
- [Rich Live Documentation](https://rich.readthedocs.io/en/stable/live.html) - Live context, refresh_per_second, console property
- [Python asyncio TaskGroup](https://docs.python.org/3/library/asyncio-task.html#task-groups) - Automatic sibling cancellation
- [Python collections.deque](https://docs.python.org/3/library/collections.html#collections.deque) - maxlen for ring buffer
- [Existing MonitorLoop](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/monitor/loop.py) - Signal handler pattern already in codebase

### Secondary (MEDIUM confidence)
- [Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/) - Signal handler setup, task cancellation sequence
- [Milestone Research SUMMARY.md](/Users/jrtipton/x/operator/.planning/research/SUMMARY.md) - Architecture decisions, pitfall catalog

### Tertiary (LOW confidence)
- None - all findings verified with primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Rich and asyncio are already in use, patterns documented
- Architecture: HIGH - Layout API is simple and well-documented, TaskGroup is stdlib
- Pitfalls: HIGH - All pitfalls verified via official docs and existing codebase patterns

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - Rich is stable)
