# Phase 10: Demo Flow Control - Research

**Researched:** 2026-01-25
**Domain:** Keyboard input handling in Python terminal applications with asyncio
**Confidence:** HIGH

## Summary

This phase adds key-press chapter progression and narration to the existing Rich Live TUI. The research confirms that keyboard input in terminal applications requires platform-specific handling (Unix uses `termios`/`tty`; Windows uses `msvcrt`), but cross-platform libraries abstract this complexity effectively.

The primary technical challenges are:
1. Reading single keypresses without blocking the asyncio event loop
2. Ensuring terminal mode restoration even on crash/Ctrl+C (the TUI already handles this for Live context)
3. Displaying key hints to the presenter without cluttering the layout
4. Managing chapter state and narration text updates

The recommended approach uses the `readchar` library (already identified in Phase 7 research) with `asyncio.run_in_executor()` to wrap blocking `readkey()` calls. This avoids complex raw terminal mode management while integrating cleanly with the existing asyncio TaskGroup pattern.

**Primary recommendation:** Use `readchar.readkey()` wrapped in `loop.run_in_executor()` for non-blocking keyboard input, integrated as an async task in the existing TaskGroup. Update the narration panel with chapter text on each keypress.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| readchar | >=4.2.0 | Cross-platform single keypress reading | No dependencies, simple API, Unix/Windows/macOS support |
| asyncio | stdlib | run_in_executor for non-blocking integration | Python 3.11+ stdlib, executor pattern well-documented |
| rich | >=14.0.0 | Layout, Panel for narration display | Already in use, Live context handles terminal restoration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| concurrent.futures | stdlib | ThreadPoolExecutor for readkey() | Implicit via run_in_executor(None, ...) |
| dataclasses | stdlib | Chapter/NarrationState data models | Clean state management |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| readchar | getchlib 1.1.3 | GPL license, more features (hotkeys), but extra complexity |
| readchar | readkeys | Similar API, less ecosystem adoption |
| readchar | pynput | Heavier, requires permissions on macOS, overkill for single keys |
| readchar | raw termios/msvcrt | No library dependency but complex platform handling |

**Installation:**
```bash
# Add to pyproject.toml dependencies
pip install readchar>=4.2.0
```

## Architecture Patterns

### Recommended Project Structure
```
operator_core/
└── tui/
    ├── controller.py   # Existing - add keyboard task
    ├── layout.py       # Existing - narration panel already exists
    ├── keyboard.py     # NEW - KeyboardReader class
    └── chapters.py     # NEW - Chapter definitions and state
```

### Pattern 1: Async Keyboard Reader with Executor
**What:** Wrap blocking `readchar.readkey()` in `run_in_executor()` for asyncio compatibility
**When to use:** Any async application needing non-blocking keyboard input
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
import asyncio
import readchar

class KeyboardReader:
    """Non-blocking keyboard reader for asyncio."""

    def __init__(self) -> None:
        self._shutdown = asyncio.Event()

    async def read_key(self) -> str | None:
        """Read single keypress without blocking event loop."""
        loop = asyncio.get_running_loop()
        try:
            # Run blocking readkey() in thread pool
            key = await asyncio.wait_for(
                loop.run_in_executor(None, readchar.readkey),
                timeout=0.5,  # Check shutdown every 0.5s
            )
            return key
        except asyncio.TimeoutError:
            return None  # No key pressed, check shutdown

    async def run(self, on_key: Callable[[str], None]) -> None:
        """Main reader loop calling callback on each keypress."""
        while not self._shutdown.is_set():
            key = await self.read_key()
            if key is not None:
                on_key(key)

    def stop(self) -> None:
        """Signal reader to stop."""
        self._shutdown.set()
```

### Pattern 2: Chapter State Machine
**What:** Define chapters as a list with current index, advance on keypress
**When to use:** Sequential presentation with narration
**Example:**
```python
# Source: Standard Python pattern
from dataclasses import dataclass, field

@dataclass
class Chapter:
    """Single chapter/stage in the demo."""
    title: str
    narration: str
    key_hint: str = "Press SPACE to continue"

@dataclass
class DemoState:
    """Manages chapter progression state."""
    chapters: list[Chapter]
    current: int = 0

    def advance(self) -> bool:
        """Advance to next chapter. Returns False if at end."""
        if self.current < len(self.chapters) - 1:
            self.current += 1
            return True
        return False

    def get_current(self) -> Chapter:
        """Get current chapter."""
        return self.chapters[self.current]

    def is_complete(self) -> bool:
        """Check if demo is at final chapter."""
        return self.current >= len(self.chapters) - 1
```

### Pattern 3: Key-to-Action Dispatch
**What:** Map specific keys to actions, ignore unknown keys
**When to use:** When different keys have different meanings
**Example:**
```python
# Source: Standard Python pattern
import readchar

def handle_key(key: str, state: DemoState) -> str | None:
    """
    Handle keypress and return action taken.

    Returns:
        Action name or None if key ignored
    """
    if key in (readchar.key.SPACE, readchar.key.ENTER, readchar.key.RIGHT):
        # Advance to next chapter
        if state.advance():
            return "advance"
        return "complete"
    elif key == readchar.key.LEFT:
        # Go back (optional feature)
        if state.current > 0:
            state.current -= 1
            return "back"
    elif key in ("q", "Q", readchar.key.CTRL_C):
        return "quit"
    return None  # Unknown key, ignore
```

### Pattern 4: Narration Panel Update
**What:** Update narration panel content when chapter changes
**When to use:** Displaying story/context text to presenter
**Example:**
```python
# Source: Rich Panel documentation + existing layout.py patterns
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

def update_narration(layout: Layout, chapter: Chapter) -> None:
    """Update narration panel with current chapter content."""
    # Build content with title and body
    content = Text()
    content.append(f"{chapter.title}\n\n", style="bold cyan")
    content.append(chapter.narration)
    content.append(f"\n\n{chapter.key_hint}", style="dim")

    layout["main"]["narration"].update(
        Panel(
            content,
            title="[bold magenta]Chapter[/bold magenta]",
            border_style="magenta",
            padding=(0, 1),
        )
    )
```

### Anti-Patterns to Avoid
- **Blocking readkey() in async task:** Never call `readchar.readkey()` directly in an async function - it blocks the entire event loop. Always use `run_in_executor()`.
- **Tight polling without timeout:** Don't poll `kbhit()` in a tight loop; use executor with timeout for CPU-friendly waiting.
- **Terminal mode without cleanup:** Don't manually set cbreak/raw mode without ensuring restoration. Let Rich Live and readchar handle it.
- **Global keyboard hooks:** Don't use pynput or keyboard library's global hooks - they require elevated permissions and are overkill.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-platform keypress | Platform if/else with termios/msvcrt | readchar.readkey() | Handles escape sequences, special keys, edge cases |
| Non-blocking async input | Manual threading | loop.run_in_executor() | Proper asyncio integration, automatic thread pool |
| Terminal mode management | Manual termios save/restore | Rich Live + readchar | Both handle cleanup; combining them works safely |
| Key constants | Hardcoded escape sequences | readchar.key.SPACE, etc. | Platform-independent, readable code |

**Key insight:** Keyboard input has subtle platform differences (key codes, escape sequences, terminal modes). Libraries like readchar have years of edge-case fixes that hand-rolled solutions would need to rediscover.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop
**What goes wrong:** Demo freezes, panels stop updating while waiting for keypress
**Why it happens:** Called `readchar.readkey()` directly in async context without executor
**How to avoid:** Always use `await loop.run_in_executor(None, readchar.readkey)`
**Warning signs:** Refresh stops during keypress wait, Ctrl+C unresponsive

### Pitfall 2: Race Condition on Shutdown
**What goes wrong:** Keyboard thread hangs after shutdown, preventing clean exit
**Why it happens:** `readkey()` blocks even after shutdown event is set
**How to avoid:** Use `asyncio.wait_for()` with timeout around the executor call, check shutdown event in loop
**Warning signs:** Program doesn't exit cleanly, requires kill -9

### Pitfall 3: Terminal Mode Conflict
**What goes wrong:** Garbled input, no echo, broken terminal after exit
**Why it happens:** Multiple things trying to manage terminal mode (Rich Live + manual cbreak)
**How to avoid:** Let Rich Live manage terminal via `with Live():` context; readchar handles its own mode internally
**Warning signs:** Terminal needs `reset` command after crash

### Pitfall 4: Missing Key Constants
**What goes wrong:** Special keys (arrows, space) don't register or crash
**Why it happens:** Comparing raw string instead of using readchar.key constants
**How to avoid:** Import `readchar.key` and use constants like `key.SPACE`, `key.ENTER`, `key.RIGHT`
**Warning signs:** Arrow keys produce multi-character strings, space works inconsistently

### Pitfall 5: Narration Panel Size
**What goes wrong:** Narration text gets truncated or overlaps
**Why it happens:** Fixed 5-row narration panel too small for longer text
**How to avoid:** Keep narration text concise (3-4 lines max) or increase panel size. Consider scrollable if needed.
**Warning signs:** Text cut off mid-sentence, visual overflow

## Code Examples

Verified patterns from official sources:

### Complete Keyboard Task Integration
```python
# Source: Adapted from asyncio.run_in_executor docs + existing TUIController pattern
import asyncio
from typing import Callable
import readchar

class KeyboardTask:
    """
    Async keyboard reader for integration with TUIController TaskGroup.

    Designed to run alongside other tasks (subprocess readers, health poller)
    without blocking the event loop.
    """

    def __init__(self, on_key: Callable[[str], None]) -> None:
        """
        Initialize keyboard task.

        Args:
            on_key: Callback invoked with each keypress
        """
        self._on_key = on_key
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        """
        Main task loop. Run inside TaskGroup.

        Uses executor for blocking readkey(), with timeout for
        responsive shutdown checking.
        """
        loop = asyncio.get_running_loop()

        while not self._shutdown.is_set():
            try:
                # Timeout allows checking shutdown event
                key = await asyncio.wait_for(
                    loop.run_in_executor(None, readchar.readkey),
                    timeout=0.5,
                )
                self._on_key(key)
            except asyncio.TimeoutError:
                continue  # No key pressed, check shutdown
            except asyncio.CancelledError:
                break  # TaskGroup cancelled us

    def stop(self) -> None:
        """Signal task to stop."""
        self._shutdown.set()
```

### Chapter Definitions for Demo
```python
# Source: Standard Python pattern
from dataclasses import dataclass

@dataclass(frozen=True)
class Chapter:
    """Immutable chapter definition."""
    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"

# Demo chapters matching existing ChaosDemo stages
DEMO_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="Welcome to the Operator Chaos Demo.\n\n"
                  "This demo showcases autonomous fault detection and AI diagnosis.\n"
                  "Watch the panels as the operator responds to infrastructure chaos.",
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="The operator first ensures the TiDB cluster is healthy.\n\n"
                  "Watch the CLUSTER panel on the left for node status.\n"
                  "All nodes should show UP before we proceed.",
    ),
    Chapter(
        title="Stage 2: Load Generation",
        narration="YCSB is starting to generate write-heavy workload.\n\n"
                  "This simulates real production traffic hitting the cluster.\n"
                  "Watch the WORKLOAD panel for operation throughput.",
    ),
    Chapter(
        title="Stage 3: Fault Injection",
        narration="Now we kill a random TiKV node to simulate failure.\n\n"
                  "Watch the CLUSTER panel - one node will turn DOWN.\n"
                  "The monitor will detect this invariant violation.",
    ),
    Chapter(
        title="Stage 4: Detection",
        narration="The MONITOR is checking cluster health invariants.\n\n"
                  "Watch for violation detection in the MONITOR panel.\n"
                  "Detection typically takes 2-5 seconds.",
    ),
    Chapter(
        title="Stage 5: AI Diagnosis",
        narration="Claude is now analyzing the violation.\n\n"
                  "The AGENT panel shows diagnosis progress.\n"
                  "AI correlates metrics, logs, and cluster state.",
    ),
    Chapter(
        title="Demo Complete",
        narration="The demo is complete!\n\n"
                  "The killed node has been restarted.\n"
                  "Press Q to exit or SPACE to restart.",
    ),
]
```

### Integration with TUIController
```python
# Source: Existing TUIController pattern + keyboard task
async def run(self) -> None:
    """Run TUI with keyboard control."""
    loop = asyncio.get_running_loop()

    # Signal handlers BEFORE Live context (existing pattern)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            functools.partial(self._handle_signal, sig),
        )

    # Initialize demo state
    self._demo_state = DemoState(chapters=DEMO_CHAPTERS)
    self._update_narration()  # Show first chapter

    # Keyboard task
    keyboard = KeyboardTask(on_key=self._handle_key)

    with Live(self._layout, console=self.console, refresh_per_second=4, screen=False) as live:
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._subprocess_mgr.read_output(monitor_proc))
                tg.create_task(self._subprocess_mgr.read_output(agent_proc))
                tg.create_task(self._health_poller.run())
                tg.create_task(keyboard.run())  # Add keyboard task
                tg.create_task(self._update_loop(live))
        except* Exception:
            pass

    # Cleanup (existing pattern)
    keyboard.stop()
    await self._subprocess_mgr.terminate_all()
```

## Platform-Specific Considerations

| Platform | Keyboard Mechanism | Notes |
|----------|-------------------|-------|
| Linux | termios + tty | readchar handles cbreak mode internally |
| macOS | termios + tty | Same as Linux; readchar actively supports |
| Windows | msvcrt.getch() | readchar abstracts this; no special handling needed |

**Windows-specific caveats:**
- Some terminals (Windows Terminal) may have different escape sequences
- readchar normalizes these differences in the `readchar.key` module
- Test on Windows if demo will be presented there

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual termios/msvcrt | readchar library | 2020+ | Cross-platform without platform checks |
| Blocking input() | run_in_executor() | asyncio adoption | Non-blocking async integration |
| curses for key input | readchar | N/A | No curses dependency, simpler API |

**Deprecated/outdated:**
- `getch` module (Python 2 era): Use readchar instead
- Manual `select.select()` polling: Use executor pattern for cleaner code

## Open Questions

Things that couldn't be fully resolved:

1. **Key repeat rate handling**
   - What we know: Holding a key generates repeated keypresses
   - What's unclear: Optimal debounce strategy for chapter advance
   - Recommendation: Ignore for MVP; chapter text change provides natural debounce

2. **Multiple presenters scenario**
   - What we know: Only one keyboard reader is active
   - What's unclear: Remote control use case (e.g., someone else advancing slides)
   - Recommendation: Defer to future phase; current scope is single presenter

3. **Escape sequence timing on slow terminals**
   - What we know: readchar handles most escape sequences
   - What's unclear: Behavior on very slow SSH connections
   - Recommendation: Test on target environment; likely fine for local/LAN demo

## Sources

### Primary (HIGH confidence)
- [Python asyncio Event Loop - run_in_executor](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.run_in_executor) - Executor pattern for blocking calls
- [Python tty module](https://docs.python.org/3/library/tty.html) - Terminal control functions (setcbreak)
- [Python msvcrt module](https://docs.python.org/3/library/msvcrt.html) - Windows keyboard input (kbhit, getch)
- [Rich Live Documentation](https://rich.readthedocs.io/en/stable/live.html) - Terminal mode management
- Phase 7 Research - Rich Live + asyncio patterns already validated

### Secondary (MEDIUM confidence)
- [readchar PyPI](https://pypi.org/project/readchar/) - Library documentation and platform support
- [getchlib PyPI](https://pypi.org/project/getchlib/) - Alternative library comparison
- [Cross-platform keyboard input discussion](https://discuss.python.org/t/cross-platform-keyboard-input/51979) - Community patterns

### Tertiary (LOW confidence)
- [Async keyboard GitHub gist](https://gist.github.com/Artiomio/a12fe54afe34873cbf0d46748172aa8e) - Example implementation pattern
- [Rich discussions #1791](https://github.com/Textualize/rich/discussions/1791) - Community workarounds for input during Live

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - readchar is well-established, executor pattern is stdlib
- Architecture: HIGH - Pattern follows existing TUIController TaskGroup design
- Pitfalls: HIGH - Verified via official docs and community reports

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - readchar and asyncio are stable)
