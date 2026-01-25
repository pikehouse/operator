# Architecture Research: TUI Demo Integration

**Project:** Operator v1.1 TUI Demo
**Researched:** 2026-01-24
**Confidence:** MEDIUM (verified with official Rich docs, asyncio docs)

## Current Architecture

### Existing Components

The operator has three main runtime components:

| Component | Location | Behavior |
|-----------|----------|----------|
| MonitorLoop | `operator_core/monitor/loop.py` | Async daemon, signal handlers, Event-based shutdown |
| AgentRunner | `operator_core/agent/runner.py` | Async daemon, signal handlers, Event-based shutdown |
| ChaosDemo | `operator_core/demo/chaos.py` | One-shot orchestrator, Rich output, inline checks |

### How Daemons Work Today

Both MonitorLoop and AgentRunner follow the same pattern:

```python
async def run(self) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, ...)

    while not self._shutdown.is_set():
        await self._check_cycle(db)  # or _process_cycle
        await asyncio.wait_for(self._shutdown.wait(), timeout=self.interval)
```

Key characteristics:
- **Own event loops** via `asyncio.run()` in CLI commands
- **Signal handlers** registered at startup
- **Event-based shutdown** with `asyncio.Event`
- **Output via print()** - not Rich-aware

### CLI Entry Points

```
operator monitor run  -> asyncio.run() -> MonitorLoop.run()
operator agent start  -> asyncio.run() -> AgentRunner.run()
operator demo chaos   -> asyncio.run() -> ChaosDemo.run()
```

Each command creates its own event loop. The current chaos demo does NOT run the real daemons - it runs inline invariant checks and one-shot Claude calls.

## TUI Integration Design

### Component Overview

```
+------------------------------------------------------------------+
|                          TUI Controller                           |
|                    (Rich Live + Layout Manager)                   |
+------------------------------------------------------------------+
         |                    |                    |
    [asyncio]            [asyncio]            [asyncio]
         |                    |                    |
         v                    v                    v
+----------------+   +----------------+   +------------------+
| Monitor Panel  |   |  Agent Panel   |   |  Cluster Panel   |
| (StreamReader) |   | (StreamReader) |   | (Direct Polling) |
+----------------+   +----------------+   +------------------+
         |                    |                    |
    [subprocess]         [subprocess]          [httpx]
         |                    |                    |
         v                    v                    v
+----------------+   +----------------+   +------------------+
| operator       |   | operator       |   |   PD/Prometheus  |
| monitor run    |   | agent start    |   |      APIs        |
+----------------+   +----------------+   +------------------+
         |                    |                    |
         v                    v                    v
+------------------------------------------------------------------+
|                     TiKV/PD Cluster (Docker)                      |
+------------------------------------------------------------------+
```

### Why Subprocesses (Not Direct Import)

Running monitor/agent as subprocesses rather than importing directly has key advantages:

1. **Signal isolation** - Each subprocess handles its own SIGINT/SIGTERM. The TUI can send targeted signals.
2. **Output capture** - Subprocess stdout is a stream we can read line-by-line.
3. **Clean lifecycle** - Start, stop, restart without complex state management.
4. **Realistic demo** - Shows what "running the operator" actually looks like.
5. **No event loop conflicts** - Each subprocess has its own `asyncio.run()`.

If we imported directly, we'd need to:
- Refactor daemons to share an event loop with TUI
- Change all print() calls to callbacks
- Handle signal handlers conflicting with TUI's own handlers

### Subprocess Management

**Spawning with asyncio:**

```python
async def spawn_monitor() -> asyncio.subprocess.Process:
    """Spawn monitor as subprocess with captured stdout."""
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "operator_core.cli.main",
        "monitor", "run",
        "--interval", "5",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
        env={**os.environ, "PYTHONUNBUFFERED": "1"},  # Force unbuffered
    )
```

**Key flags:**
- `PYTHONUNBUFFERED=1` - Forces line-buffered output for real-time streaming
- `stderr=STDOUT` - Single stream to read from
- `stdout=PIPE` - Capture for display

**Termination:**

```python
async def stop_subprocess(proc: asyncio.subprocess.Process) -> None:
    """Gracefully stop subprocess."""
    if proc.returncode is None:
        proc.terminate()  # SIGTERM first
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()  # SIGKILL if needed
            await proc.wait()
```

### Live Output Capture

**Pattern: Async Line Reader**

```python
async def read_subprocess_output(
    proc: asyncio.subprocess.Process,
    callback: Callable[[str], None],
) -> None:
    """Read stdout line-by-line, call callback for each."""
    while True:
        line = await proc.stdout.readline()
        if not line:  # EOF
            break
        callback(line.decode().rstrip())
```

**Integration with Rich Live:**

```python
class OutputBuffer:
    """Ring buffer for recent output lines."""
    def __init__(self, max_lines: int = 20):
        self.lines: deque[str] = deque(maxlen=max_lines)

    def add(self, line: str) -> None:
        self.lines.append(line)

    def render(self) -> Text:
        return Text("\n".join(self.lines))
```

The TUI maintains one OutputBuffer per subprocess. Each callback adds to the buffer. Rich Live's refresh renders all buffers into their respective panels.

**Concurrency Model:**

```python
async def run_tui():
    # Spawn subprocesses
    monitor_proc = await spawn_monitor()
    agent_proc = await spawn_agent()

    # Create output buffers
    monitor_buffer = OutputBuffer()
    agent_buffer = OutputBuffer()

    # Start readers as tasks (run concurrently)
    monitor_reader = asyncio.create_task(
        read_subprocess_output(monitor_proc, monitor_buffer.add)
    )
    agent_reader = asyncio.create_task(
        read_subprocess_output(agent_proc, agent_buffer.add)
    )

    # Run Rich Live display
    with Live(layout, refresh_per_second=4) as live:
        while not shutdown:
            # Update layout panels from buffers
            layout["monitor"].update(Panel(monitor_buffer.render()))
            layout["agent"].update(Panel(agent_buffer.render()))
            await asyncio.sleep(0.1)
```

### Key-Press Handling

**Challenge:** Rich's Live display runs in a context manager. We need to detect keypresses concurrently with subprocess reading and display updates.

**Recommended approach:** Use `getchlib` or platform-specific non-blocking input.

```python
import sys
import select

def check_keypress() -> str | None:
    """Non-blocking keypress check (Unix)."""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None
```

**Integration with async loop:**

```python
async def key_listener(callback: Callable[[str], None]) -> None:
    """Poll for keypresses without blocking."""
    import tty
    import termios

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            key = check_keypress()
            if key:
                callback(key)
            await asyncio.sleep(0.05)  # 20Hz polling
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
```

**Alternative: Use Textual**

For more robust key handling, the Textual framework (from Rich's author) provides:
- Built-in `key_*` method handlers
- Proper terminal mode management
- Cross-platform support

However, Textual is a heavier dependency and requires restructuring to its App/Widget model. For this demo, low-level keypress detection is sufficient.

### Layout Structure

**Recommended 5-panel layout:**

```
+------------------+------------------+
|   Cluster Status |    Narration     |
|   (health, nodes)|  (chapter text)  |
+------------------+------------------+
|   Monitor Output | Agent Output     |
|   (live logs)    | (live logs)      |
+------------------+------------------+
|            Workload Panel           |
|        (ops/sec, latency bar)       |
+---------+---------------------------+
| [space] next  [q] quit  [r] restart |
+---------+---------------------------+
```

**Rich Layout code:**

```python
from rich.layout import Layout
from rich.panel import Panel

def make_layout() -> Layout:
    """Create the TUI layout structure."""
    layout = Layout()

    layout.split_column(
        Layout(name="upper", ratio=1),
        Layout(name="middle", ratio=2),
        Layout(name="lower", ratio=1),
        Layout(name="footer", size=3),
    )

    layout["upper"].split_row(
        Layout(name="cluster", ratio=1),
        Layout(name="narration", ratio=1),
    )

    layout["middle"].split_row(
        Layout(name="monitor", ratio=1),
        Layout(name="agent", ratio=1),
    )

    return layout
```

### asyncio + Rich Live Compatibility

**Verified pattern from Rich docs:** Rich Live works within asyncio. The Live context manager handles terminal state; your async code handles the content updates.

```python
async def run_dashboard():
    layout = make_layout()

    with Live(layout, refresh_per_second=4, screen=True) as live:
        # screen=True gives full terminal control
        while not shutdown_event.is_set():
            # Update panels from buffers/state
            update_panels(layout)

            # Yield to other tasks
            await asyncio.sleep(0.1)
```

**Key considerations:**

1. **refresh_per_second=4** - Default is fine for logs. Use higher (10-15) for smoother animations.
2. **screen=True** - Takes over terminal, restores on exit. Good for dashboards.
3. **transient=False** - Keep final state visible after exit (default).
4. **Auto-refresh** - Enabled by default. Content updates automatically on each refresh cycle.

### Data Flow Summary

```
1. TUI Controller starts
   |
2. Spawns monitor subprocess (asyncio.create_subprocess_exec)
   |
3. Spawns agent subprocess (asyncio.create_subprocess_exec)
   |
4. Creates output reader tasks (asyncio.create_task for each)
   |
5. Enters Rich Live context
   |
6. Main loop:
   |-- Reader tasks populate OutputBuffers (async readline)
   |-- Key listener task checks for keypresses
   |-- Layout panels updated from buffers
   |-- Live.refresh() renders to terminal (automatic at refresh_per_second)
   |
7. On keypress 'q' or chapter complete:
   |-- Send SIGTERM to subprocesses
   |-- Cancel reader tasks
   |-- Exit Live context
   |-- Terminal restored
```

## Build Order

Based on dependencies and testability:

### 1. Output Buffer and Panel Rendering

**Why first:** Can test independently with mock data. Foundation for all panels.

**Deliverables:**
- `OutputBuffer` class with ring buffer and render method
- Panel factory functions for each panel type
- Unit tests with sample output

### 2. Layout Manager

**Why second:** Depends on panel rendering. Can test with static content.

**Deliverables:**
- `make_layout()` function
- `update_panels()` function
- Visual test script

### 3. Subprocess Spawning and Management

**Why third:** Core infrastructure. Can test with simple echo commands.

**Deliverables:**
- `spawn_monitor()`, `spawn_agent()` functions
- `stop_subprocess()` with graceful shutdown
- `read_subprocess_output()` async reader
- Integration test with real monitor/agent (manual)

### 4. Cluster Status Polling

**Why fourth:** Independent of subprocess work. Reuses existing PDClient/PrometheusClient.

**Deliverables:**
- `poll_cluster_status()` async function
- Cluster status panel rendering
- Integration with existing subject code

### 5. Key-Press Handler

**Why fifth:** Simple in isolation, complex in integration.

**Deliverables:**
- `check_keypress()` non-blocking reader
- `key_listener()` async task
- Chapter state machine (healthy -> fault -> diagnosis -> recovery -> exit)

### 6. TUI Controller Integration

**Why sixth:** Brings everything together.

**Deliverables:**
- `TUIDemo` class (replaces ChaosDemo for TUI mode)
- Full async orchestration
- CLI command `operator demo tui`

### 7. Docker Integration for Fault Injection

**Why seventh:** Reuse existing ChaosDemo Docker code.

**Deliverables:**
- Kill container on chapter transition
- Restart container on recovery chapter
- Container status in cluster panel

## Integration Points

| Existing Component | New Component | Connection |
|-------------------|---------------|------------|
| `monitor/loop.py` MonitorLoop | SubprocessManager | Spawned as subprocess via CLI |
| `agent/runner.py` AgentRunner | SubprocessManager | Spawned as subprocess via CLI |
| `demo/chaos.py` ChaosDemo | TUIDemo | Reuse Docker client, container kill logic |
| `cli/monitor.py` run_monitor | TUI | Entry point for subprocess |
| `cli/agent.py` start_agent | TUI | Entry point for subprocess |
| `tikv/pd_client.py` PDClient | ClusterStatusPanel | Direct import for polling |
| `tikv/prom_client.py` PrometheusClient | WorkloadPanel | Direct import for metrics |

### What NOT to Change

The existing daemons (MonitorLoop, AgentRunner) should NOT be modified. They work correctly as standalone processes. The TUI layer wraps them as subprocesses.

The CLI commands (monitor run, agent start) should NOT be modified. They're the stable interface the TUI invokes.

### What to Add

New module: `operator_core/demo/tui.py`

```
demo/
  __init__.py  (existing)
  chaos.py     (existing - one-shot demo)
  tui.py       (new - TUI dashboard demo)
```

New CLI command: `operator demo tui`

```python
# In cli/demo.py
@demo_app.command("tui")
def run_tui_demo(...):
    """Run TUI-based live demo with multi-panel dashboard."""
    asyncio.run(TUIDemo(...).run())
```

## Pitfalls and Mitigations

### Pitfall 1: Signal Handler Conflicts

**Risk:** TUI and subprocesses both want to handle SIGINT.

**Mitigation:** Don't register signal handlers in TUI. Let Ctrl+C propagate to subprocesses naturally. Use keypress 'q' for clean exit.

### Pitfall 2: Buffered Subprocess Output

**Risk:** Python subprocess output is buffered by default, causing delayed display.

**Mitigation:** Always set `PYTHONUNBUFFERED=1` in subprocess environment.

### Pitfall 3: Terminal State Corruption

**Risk:** If TUI crashes, terminal may be in raw mode.

**Mitigation:** Use try/finally in key listener. Rich Live handles its own cleanup. Consider `atexit` handler for catastrophic failures.

### Pitfall 4: Blocking Reads Starving Event Loop

**Risk:** `proc.stdout.readline()` could block if no output.

**Mitigation:** Using async readline (`await proc.stdout.readline()`) yields to event loop between lines. EOF returns empty bytes, signaling subprocess exit.

### Pitfall 5: Memory Growth from Unbounded Buffers

**Risk:** Long-running demo accumulates unbounded output.

**Mitigation:** Use `deque(maxlen=N)` for fixed-size ring buffers. 50-100 lines per panel is sufficient.

## Sources

- [Rich Live Display Documentation](https://rich.readthedocs.io/en/stable/live.html) - Official Rich docs on Live display
- [Rich Layout Documentation](https://rich.readthedocs.io/en/stable/layout.html) - Official Rich docs on Layout
- [Python asyncio Subprocess Documentation](https://docs.python.org/3/library/asyncio-subprocess.html) - Official Python docs on asyncio subprocess
- [Real-time subprocess capture patterns](https://lucadrf.dev/blog/python-subprocess-buffers/) - Community patterns for unbuffered output
- [GitHub Discussion: Rich Live with input](https://github.com/Textualize/rich/discussions/1791) - Workarounds for input during Live display
- [sshkeyboard library](https://sshkeyboard.readthedocs.io/) - Async-compatible keyboard input library
