# Phase 11: Fault Workflow Integration - Research

**Researched:** 2026-01-25
**Domain:** Workload visualization, countdown animation, fault injection integration with TUI
**Confidence:** HIGH

## Summary

This phase integrates fault injection into the TUI demo flow, adding three key components: (1) a workload panel with sparkline visualization that shows ops/sec and turns red on degradation, (2) a visual countdown before fault injection, and (3) orchestration of the full fault/recovery cycle through the existing chapter system.

Research confirms:

1. **Sparklines for workload visualization**: The `sparklines` Python library (pure Python, MIT license) generates Unicode bar sparklines (`▁▂▃▄▅▆▇█`) from numeric data. This integrates cleanly with Rich markup for color coding. No external dependencies needed beyond the sparklines package.

2. **YCSB outputs real-time throughput**: YCSB status lines follow the format `2017-05-20 18:55:44:512 10 sec: 376385 operations; 37634.74 current ops/sec`. Parsing the `current ops/sec` value from subprocess output enables real-time workload visualization.

3. **Countdown using Rich Live update**: The existing `Live.update()` pattern with `asyncio.sleep()` provides smooth countdown animation. No additional libraries needed beyond what's already in use (Rich, asyncio).

4. **Fault injection exists in chaos.py**: The `ChaosDemo._inject_fault()` method already kills TiKV nodes via `docker.kill()`. This can be called directly from chapter callbacks without reimplementation.

**Primary recommendation:** Add `sparklines` library for workload visualization. Create a `WorkloadTracker` class that parses YCSB output for throughput, maintains a sliding window of values, and generates color-coded sparklines. Integrate countdown as a special chapter that pauses progression while displaying "Injecting fault in 3... 2... 1..." then triggers fault injection.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sparklines | >=0.4.2 | Unicode sparkline generation from numeric data | Simple API, MIT license, Edward Tufte's design principles |
| rich | >=14.0.0 | Color markup for sparklines, countdown display, panel updates | Already in use |
| asyncio | stdlib | Countdown timer via sleep(), event coordination | Already in use |
| python-on-whales | >=0.60.0 | Docker container kill/restart | Already in use in chaos.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| collections.deque | stdlib | Sliding window for throughput history | WorkloadTracker value storage |
| re | stdlib | YCSB output parsing | Extract ops/sec from status lines |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sparklines library | Hand-rolled Unicode bars | Library handles edge cases (empty data, scaling) |
| sparklines library | plotext/termgraph | Heavier, designed for full charts not inline sparklines |
| YCSB subprocess | Simulated workload | YCSB is realistic but requires parsing; simulation is simpler but less authentic |
| Rich text for countdown | pyfiglet/big text | Overkill for simple "3... 2... 1..." display |

**Installation:**
```bash
pip install sparklines>=0.4.2
```

## Architecture Patterns

### Recommended Module Structure
```
operator_core/
└── tui/
    ├── controller.py   # Modified - add WorkloadTracker, countdown logic
    ├── chapters.py     # Modified - add chapter callbacks for fault workflow
    ├── workload.py     # NEW - WorkloadTracker class
    └── ... (existing files unchanged)
```

### Pattern 1: WorkloadTracker with Sparkline Generation
**What:** Parse YCSB output for throughput, maintain sliding window, generate sparklines
**When to use:** Real-time workload visualization in TUI
**Example:**
```python
# Source: sparklines library + existing OutputBuffer pattern
import re
from collections import deque
from sparklines import sparklines

class WorkloadTracker:
    """Tracks workload throughput and generates sparkline visualization."""

    # YCSB status line format: "2017-05-20 18:55:44:512 10 sec: 376385 operations; 37634.74 current ops/sec"
    YCSB_PATTERN = re.compile(r'(\d+\.?\d*)\s+current ops/sec')

    def __init__(self, window_size: int = 30, degradation_threshold: float = 0.5) -> None:
        """
        Initialize workload tracker.

        Args:
            window_size: Number of throughput samples to keep
            degradation_threshold: Fraction of baseline below which is "degraded"
        """
        self._values: deque[float] = deque(maxlen=window_size)
        self._baseline: float | None = None
        self._threshold = degradation_threshold

    def parse_line(self, line: str) -> float | None:
        """
        Parse YCSB output line for throughput.

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

        Args:
            ops_per_sec: Current throughput value
        """
        self._values.append(ops_per_sec)
        # Establish baseline from warm-up period
        if self._baseline is None and len(self._values) >= 5:
            self._baseline = sum(list(self._values)[:5]) / 5

    def is_degraded(self) -> bool:
        """Check if current throughput is degraded vs baseline."""
        if not self._values or self._baseline is None:
            return False
        current = self._values[-1]
        return current < (self._baseline * self._threshold)

    def get_sparkline(self) -> str:
        """
        Generate sparkline from throughput history.

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
```

### Pattern 2: Countdown Display with Rich Update
**What:** Visual countdown that updates in-place before fault injection
**When to use:** Building dramatic pause before chaos event
**Example:**
```python
# Source: Rich Live + asyncio patterns from existing code
import asyncio
from rich.text import Text

async def countdown_before_fault(
    update_callback: Callable[[str], None],
    seconds: int = 3,
) -> None:
    """
    Display countdown before fault injection.

    Args:
        update_callback: Function to call with countdown text
        seconds: Number of seconds to count down
    """
    for i in range(seconds, 0, -1):
        text = f"[bold yellow]Injecting fault in {i}...[/bold yellow]"
        update_callback(text)
        await asyncio.sleep(1.0)

    # Final message
    update_callback("[bold red]FAULT INJECTED![/bold red]")
    await asyncio.sleep(0.5)
```

### Pattern 3: Chapter with Action Callback
**What:** Extend Chapter to support actions that run when chapter is entered
**When to use:** Chapters that need to trigger side effects (countdown, fault injection)
**Example:**
```python
# Source: Existing chapters.py pattern extended
from dataclasses import dataclass, field
from typing import Callable, Awaitable

@dataclass(frozen=True)
class Chapter:
    """Chapter definition with optional action callback."""
    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"
    # Optional async action to run when entering this chapter
    on_enter: Callable[[], Awaitable[None]] | None = None
    # Whether to auto-advance after on_enter completes
    auto_advance: bool = False
```

### Pattern 4: Fault Injection Integration
**What:** Integrate existing chaos.py fault injection with TUI controller
**When to use:** Triggering node kill during demo
**Example:**
```python
# Source: Existing chaos.py._inject_fault pattern
from python_on_whales import DockerClient

class TUIController:
    # ... existing code ...

    async def _inject_fault(self) -> str:
        """
        Kill a random TiKV node (adapted from chaos.py).

        Returns:
            Name of killed container
        """
        docker = DockerClient(compose_files=[self._compose_file])
        containers = docker.compose.ps()
        tikv_containers = [
            c for c in containers
            if "tikv" in c.name.lower() and c.state.running
        ]

        if not tikv_containers:
            raise RuntimeError("No running TiKV containers")

        import random
        target = random.choice(tikv_containers)
        docker.kill(target.name)
        self._killed_container = target.name

        return target.name

    async def _recover_node(self) -> None:
        """Restart killed container."""
        if self._killed_container:
            docker = DockerClient(compose_files=[self._compose_file])
            docker.compose.start(services=[self._killed_container])
            self._killed_container = None
```

### Pattern 5: YCSB Subprocess Integration
**What:** Parse YCSB output from subprocess for workload visualization
**When to use:** Connecting YCSB daemon output to WorkloadTracker
**Example:**
```python
# Source: Existing SubprocessManager pattern
def _refresh_panels(self) -> None:
    """Refresh panels including workload from YCSB output."""
    # ... existing monitor/agent refresh ...

    # Update workload panel from YCSB output
    ycsb_buf = self._subprocess_mgr.get_buffer("ycsb")
    if ycsb_buf and self._workload_tracker:
        for line in ycsb_buf.get_lines(n=10):
            ops = self._workload_tracker.parse_line(line)
            if ops is not None:
                self._workload_tracker.update(ops)

        self._layout["main"]["workload"].update(
            make_workload_panel(self._workload_tracker)
        )

def make_workload_panel(tracker: WorkloadTracker) -> Panel:
    """Create workload panel with degradation-aware styling."""
    content = tracker.format_panel()
    border_style = "red" if tracker.is_degraded() else "yellow"
    return Panel(
        content,
        title="[bold]Workload[/bold]",
        border_style=border_style,
        padding=(0, 1),
    )
```

### Anti-Patterns to Avoid
- **Blocking during countdown:** Never use `time.sleep()` in async context. Always use `asyncio.sleep()`.
- **Polling YCSB too fast:** Don't parse every line immediately. Check recent lines in refresh cycle (every 250ms is fine).
- **Hardcoded threshold:** Make degradation threshold configurable. 50% of baseline is a reasonable default but may need tuning.
- **Losing baseline on restart:** If YCSB restarts, baseline resets. This is actually correct behavior for demo purposes.
- **Countdown blocking key input:** Countdown should not prevent Q from quitting. Use asyncio.wait() with both countdown and shutdown event.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unicode bar sparklines | Character lookup table | sparklines library | Handles scaling, empty data, edge cases |
| Docker container kill | subprocess + docker CLI | python-on-whales | Already in use, proper API |
| Async countdown | Threading + sleep | asyncio.sleep() in async func | Event loop compatible |
| YCSB output parsing | Line-by-line scan in subprocess | Regex in refresh cycle | Simpler, batched processing |
| Container restart | Manual docker commands | docker.compose.start() | Already implemented in chaos.py |

**Key insight:** The sparklines library is small (single file, pure Python) but handles the math of scaling values to 8 Unicode bar heights correctly. Hand-rolling this is error-prone.

## Common Pitfalls

### Pitfall 1: Sparklines with Negative/Zero Values
**What goes wrong:** Sparklines display incorrectly or crash
**Why it happens:** Library expects positive values, throughput can temporarily be 0
**How to avoid:**
- Filter out zero values before sparkline generation
- Use `max(0.1, value)` floor to avoid visual artifacts
- Handle empty deque gracefully
**Warning signs:** Empty sparkline, ValueError from library

### Pitfall 2: YCSB Output Buffering Delays
**What goes wrong:** Workload panel shows stale data
**Why it happens:** YCSB outputs status every 10 seconds by default
**How to avoid:**
- Start YCSB with `-s` flag for status output
- Optionally use `-p status.interval=1` for 1-second updates
- Accept some lag (2-3 seconds is acceptable for demo)
**Warning signs:** Sparkline doesn't update even when YCSB is running

### Pitfall 3: Countdown Blocking Shutdown
**What goes wrong:** Can't Ctrl+C during countdown
**Why it happens:** Countdown loop doesn't check shutdown event
**How to avoid:**
- Use `asyncio.wait()` with both countdown sleep and shutdown event
- Check shutdown flag between countdown ticks
- Interrupt-aware sleep pattern: `await asyncio.wait_for(shutdown.wait(), timeout=1.0)`
**Warning signs:** Q key ignored during countdown, need Ctrl+C multiple times

### Pitfall 4: Container Not Found After Kill
**What goes wrong:** Recovery fails, can't restart killed node
**Why it happens:** Container name changes or compose project prefix varies
**How to avoid:**
- Store killed container name immediately after kill
- Use compose service name for restart (not container name)
- Verify container exists before restart
**Warning signs:** "No such container" errors during recovery

### Pitfall 5: Baseline Never Established
**What goes wrong:** Degradation detection never triggers
**Why it happens:** YCSB slow to start, fewer than 5 samples before fault
**How to avoid:**
- Wait for baseline before allowing fault injection chapter advance
- Show "Establishing baseline..." in workload panel during warm-up
- Use configurable warm-up sample count (default 5)
**Warning signs:** Workload shows "degraded" immediately or never

### Pitfall 6: Sparkline Too Short or Too Long
**What goes wrong:** Visual doesn't show useful trend
**Why it happens:** Window size doesn't match panel width
**How to avoid:**
- Calculate window size from panel width (roughly panel_width - padding)
- Default 30 values works for 35-character panel width
- Allow configuration for different terminal sizes
**Warning signs:** Sparkline wraps or is only a few characters

## Code Examples

Verified patterns from official sources:

### Sparklines Library Usage (Verified)
```python
# Source: https://pypi.org/project/sparklines/
from sparklines import sparklines

# Basic usage - returns generator of lines
values = [1, 2, 3, 4, 5, 4, 3, 2, 1]
for line in sparklines(values):
    print(line)  # ▁▃▅▆█▆▅▃▁

# Single line extraction
line = list(sparklines(values))[0]

# Handle None values (appear as spaces)
values_with_gap = [1, 2, None, 4, 5]
for line in sparklines(values_with_gap):
    print(line)  # ▁▃ ▆█
```

### Rich Color Markup with Sparklines
```python
# Source: Rich markup docs + sparklines integration
from rich.console import Console
from sparklines import sparklines

console = Console()

values = [100, 120, 80, 90, 50, 30, 20]  # Degrading throughput
spark = list(sparklines(values))[0]

# Color based on last value
if values[-1] < 50:
    console.print(f"[red]{spark}[/red]")  # Red when degraded
else:
    console.print(f"[green]{spark}[/green]")  # Green when healthy
```

### YCSB Output Parsing (Verified)
```python
# Source: YCSB status output format from GitHub issues
import re

# Status line format: "2017-05-20 18:55:44:512 10 sec: 376385 operations; 37634.74 current ops/sec"
YCSB_PATTERN = re.compile(r'(\d+\.?\d*)\s+current ops/sec')

line = "2026-01-25 10:30:15:123 5 sec: 50000 operations; 10000.00 current ops/sec"
match = YCSB_PATTERN.search(line)
if match:
    ops_per_sec = float(match.group(1))  # 10000.0
```

### Interruptible Countdown (Verified)
```python
# Source: asyncio docs + existing TUI patterns
import asyncio

async def interruptible_countdown(
    seconds: int,
    shutdown: asyncio.Event,
    on_tick: Callable[[int], None],
) -> bool:
    """
    Countdown that can be interrupted by shutdown event.

    Returns:
        True if countdown completed, False if interrupted
    """
    for i in range(seconds, 0, -1):
        on_tick(i)
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=1.0)
            return False  # Interrupted
        except asyncio.TimeoutError:
            continue  # Normal tick
    return True  # Completed
```

### Docker Container Kill/Restart (Verified)
```python
# Source: Existing chaos.py + python-on-whales docs
from python_on_whales import DockerClient

docker = DockerClient(compose_files=["docker-compose.yaml"])

# Kill specific container (SIGKILL)
docker.kill("tikv-tikv0-1")

# Restart via compose (preferred for service name)
docker.compose.start(services=["tikv0"])
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ASCII graphs (--.--) | Unicode sparklines (▁▂▃▄▅▆▇█) | Unicode adoption | Better visual density |
| Curses-based animation | Rich Live update | Rich maturity | Simpler API, Rich ecosystem |
| Manual docker subprocess | python-on-whales | Library maturity | Type safety, cleaner API |
| Synchronous fault inject | Async with event coordination | asyncio adoption | Non-blocking TUI |

**Deprecated/outdated:**
- Using `termgraph` for inline sparklines: It's designed for full charts, not inline text
- Using `plotext` for sparklines: Overkill, designed for matplotlib-like API
- Shell-based spark command: External dependency, Python native is simpler

## Open Questions

Things that couldn't be fully resolved:

1. **YCSB status interval configuration**
   - What we know: YCSB outputs status every 10 seconds by default
   - What's unclear: Best interval for demo (1s updates vs 10s)
   - Recommendation: Start with default, reduce to 1s if panel looks stale. Use `-p status.interval=1` if needed.

2. **Degradation threshold tuning**
   - What we know: 50% of baseline is reasonable starting point
   - What's unclear: Actual throughput drop when TiKV node dies
   - Recommendation: Start with 50%, tune based on real demo runs. May need 30% or 70%.

3. **Recovery timing**
   - What we know: Node can be restarted with docker compose start
   - What's unclear: How long until cluster rebalances and throughput recovers
   - Recommendation: Add "Recovering..." chapter after restart, auto-advance when throughput normalizes.

4. **Workload panel size**
   - What we know: Current layout has 8 rows for workload panel
   - What's unclear: Is 8 rows enough for sparkline + stats + status?
   - Recommendation: Sparkline (1 row) + blank (1 row) + current ops (1 row) + status (1 row) = 4 rows minimum. 8 rows is sufficient.

## Sources

### Primary (HIGH confidence)
- [sparklines PyPI](https://pypi.org/project/sparklines/) - Library API, installation, usage examples
- [sparklines GitHub](https://github.com/deeplook/sparklines) - Source code, feature list
- [Rich Live Documentation](https://rich.readthedocs.io/en/stable/live.html) - update() method, refresh patterns
- [YCSB GitHub Issue #974](https://github.com/brianfrankcooper/YCSB/issues/974) - Status line format clarification
- [Python asyncio Documentation](https://docs.python.org/3/library/asyncio-task.html) - wait_for pattern
- [Existing chaos.py](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/demo/chaos.py) - Fault injection implementation
- [Existing controller.py](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/controller.py) - TUI integration patterns
- [Existing chapters.py](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/chapters.py) - Chapter dataclass

### Secondary (MEDIUM confidence)
- [YCSB GitHub Issue #318](https://github.com/brianfrankcooper/YCSB/issues/318) - Output format details
- [Phase 9 Research](/Users/jrtipton/x/operator/.planning/phases/09-cluster-health-display/09-RESEARCH.md) - Health panel patterns
- [Phase 10 Research](/Users/jrtipton/x/operator/.planning/phases/10-demo-flow-control/10-RESEARCH.md) - Chapter progression patterns

### Tertiary (LOW confidence)
- [Rich discussions #1002](https://github.com/Textualize/rich/discussions/1002) - Terminal plotting discussion (confirms sparklines as separate concern)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - sparklines library is stable, other components already in use
- Architecture: HIGH - Patterns follow existing codebase conventions
- Workload visualization: HIGH - sparklines API well-documented, Rich integration straightforward
- Countdown: HIGH - Rich Live update pattern already validated in project
- Fault integration: HIGH - chaos.py already implements, just needs TUI orchestration
- Pitfalls: MEDIUM - Some based on YCSB behavior (will need tuning)

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - sparklines and asyncio are stable)

---

## Key Answers to Phase Questions

**Q1: How to display workload throughput as sparkline in TUI panel?**
- Use `sparklines` library: `pip install sparklines>=0.4.2`
- Parse YCSB status output with regex for `(\d+\.?\d*)\s+current ops/sec`
- Maintain sliding window in `collections.deque(maxlen=30)`
- Generate sparkline: `list(sparklines(values))[0]`
- Wrap in Rich color markup: `[green]{sparkline}[/green]` or `[red]{sparkline}[/red]`

**Q2: How to detect workload degradation and change panel color?**
- Establish baseline from first 5 samples during warm-up
- Compare current value to baseline * threshold (default 50%)
- If `current < baseline * 0.5`: degraded (red)
- Else: normal (green/yellow)
- Apply color to both sparkline text and panel border_style

**Q3: How to display countdown before fault injection?**
- Create async function that calls panel update callback
- Loop from N to 0, updating text: `"Injecting fault in {i}..."`
- Use `asyncio.sleep(1.0)` between updates
- Check shutdown event to allow interrupt
- After countdown: update to "FAULT INJECTED!", trigger kill

**Q4: How to integrate fault injection with existing TUI?**
- Extend Chapter dataclass with `on_enter` callback and `auto_advance` flag
- Create countdown chapter that runs countdown then triggers `_inject_fault()`
- Store killed container name on controller: `self._killed_container`
- Create recovery chapter that calls `docker.compose.start()`
- Parse fault injection chapter: disable key advance during countdown

**Q5: How to start/parse YCSB subprocess output?**
- Add YCSB to SubprocessManager: `spawn("ycsb", ["-m", "ycsb.client", ...])`
- In `_refresh_panels()`, get YCSB buffer and parse recent lines
- Create WorkloadTracker instance on controller
- Call `tracker.parse_line()` for each line, `tracker.update()` when ops found
- Render with `tracker.format_panel()` for panel content
