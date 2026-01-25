# Phase 8: Subprocess Management - Research

**Researched:** 2026-01-24
**Domain:** Python asyncio subprocess spawning, output capture, and lifecycle management
**Confidence:** HIGH

## Summary

This phase implements the subprocess infrastructure for running monitor and agent daemons as real processes with live output capture. The research confirms that Python's asyncio subprocess module provides all needed functionality, with well-documented patterns for the critical challenges: output buffering, graceful shutdown, and zombie prevention.

The primary challenges are:
1. **Output buffering** - Subprocesses buffer stdout when piped. Solved with `PYTHONUNBUFFERED=1` environment variable
2. **Readline blocking forever** - Daemons don't close stdout. Solved with `asyncio.wait_for(readline(), timeout=0.1)` pattern
3. **Zombie/orphan processes** - Must use `start_new_session=True` and proper shutdown sequence (SIGTERM -> wait -> SIGKILL)
4. **TaskGroup integration** - Reader tasks must handle CancelledError gracefully during shutdown

The codebase already has the exact CLI commands needed: `operator monitor run` and `operator agent start`. Both daemons print output continuously, making them ideal for the TUI output capture use case.

**Primary recommendation:** Create a SubprocessManager class that spawns processes with `asyncio.create_subprocess_exec`, uses environment-based unbuffering, and implements the SIGTERM-wait-SIGKILL shutdown pattern. Integrate reader tasks into TUIController's run() method using TaskGroup.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio.subprocess | stdlib (3.11+) | create_subprocess_exec, Process lifecycle | Stdlib, async-native, well-documented |
| asyncio.TaskGroup | stdlib (3.11+) | Coordinate reader tasks with TUI lifecycle | Automatic sibling cancellation on exception |
| os | stdlib | Environment variable manipulation | Stdlib, cross-platform |
| signal | stdlib | SIGTERM/SIGKILL for subprocess termination | Stdlib, POSIX-standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sys | stdlib | Get Python executable path | Spawning Python subprocesses |
| shutil | stdlib | Find executable paths (shutil.which) | Validating command availability |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncio.subprocess | subprocess.Popen | Popen is sync, requires threading for async integration |
| PYTHONUNBUFFERED | PTY (pty module) | PTY is more complex, platform-specific, only needed for non-Python processes |

**Installation:**
No new dependencies needed. All required functionality is in Python's standard library (3.11+).

## Architecture Patterns

### Recommended Module Structure
```
operator_core/
└── tui/
    ├── __init__.py
    ├── layout.py         # Existing - Layout factory
    ├── buffer.py         # Existing - OutputBuffer class
    ├── controller.py     # Modified - Add subprocess integration
    └── subprocess.py     # NEW - SubprocessManager class
```

### Pattern 1: Subprocess Spawning with Unbuffered Output
**What:** Spawn Python subprocess with PYTHONUNBUFFERED=1 to force line buffering
**When to use:** Always, for Python subprocess output capture
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-subprocess.html
import asyncio
import os
import sys

async def spawn_daemon(command: list[str]) -> asyncio.subprocess.Process:
    """Spawn subprocess with unbuffered stdout."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Force line buffering

    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m", "operator_core.cli.main",
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
        env=env,
        start_new_session=True,  # Create new process group
    )
```

### Pattern 2: Non-Blocking Readline with Timeout
**What:** Read stdout line-by-line with timeout to avoid blocking on long-running daemons
**When to use:** When subprocess stdout won't close (daemons)
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-subprocess.html + WebSearch verification
async def read_output(
    proc: asyncio.subprocess.Process,
    buffer: OutputBuffer,
    shutdown: asyncio.Event,
) -> None:
    """Read subprocess output line-by-line with timeout."""
    while not shutdown.is_set() and proc.returncode is None:
        try:
            line = await asyncio.wait_for(
                proc.stdout.readline(),
                timeout=0.1,  # Short timeout for responsiveness
            )
            if line:
                buffer.append(line.decode("utf-8"))
            elif proc.returncode is not None:
                break  # Process exited
        except asyncio.TimeoutError:
            continue  # Normal timeout, check shutdown flag
        except asyncio.CancelledError:
            break  # Task cancelled, exit cleanly
```

### Pattern 3: Graceful Shutdown Sequence (SIGTERM -> Wait -> SIGKILL)
**What:** Terminate subprocess gracefully with escalation to SIGKILL
**When to use:** Always, for subprocess cleanup
**Example:**
```python
# Source: https://roguelynn.com/words/asyncio-graceful-shutdowns/ + official docs
async def terminate_subprocess(
    proc: asyncio.subprocess.Process,
    timeout: float = 5.0,
) -> None:
    """Gracefully terminate subprocess with SIGKILL fallback."""
    if proc.returncode is not None:
        return  # Already exited

    # Try graceful termination first
    proc.terminate()  # Sends SIGTERM on POSIX

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        # Process didn't exit, force kill
        proc.kill()  # Sends SIGKILL on POSIX
        await proc.wait()  # Reap zombie
```

### Pattern 4: TaskGroup Integration with TUIController
**What:** Run subprocess reader tasks within TUIController's TaskGroup
**When to use:** To coordinate subprocess lifecycle with TUI lifecycle
**Example:**
```python
# Source: https://docs.python.org/3/library/asyncio-task.html#task-groups
async def run(self) -> None:
    """Run TUI with subprocess management."""
    # ... signal handler setup ...

    # Spawn subprocesses BEFORE entering Live context
    monitor_proc = await spawn_daemon(["monitor", "run", "-i", "5"])
    agent_proc = await spawn_daemon(["agent", "start", "-i", "5"])

    with Live(self._layout, console=self.console, refresh_per_second=4) as live:
        try:
            async with asyncio.TaskGroup() as tg:
                # Reader tasks
                tg.create_task(read_output(monitor_proc, self._monitor_buffer, self._shutdown))
                tg.create_task(read_output(agent_proc, self._agent_buffer, self._shutdown))
                # Update loop
                tg.create_task(self._update_loop(live))
                # Wait for shutdown
                await self._shutdown.wait()
        except* Exception:
            pass  # TaskGroup handles cancellation

    # Cleanup: terminate subprocesses
    await terminate_subprocess(monitor_proc)
    await terminate_subprocess(agent_proc)
```

### Pattern 5: Process Group Termination for Orphan Prevention
**What:** Use start_new_session=True to create process group, enabling group-wide signals
**When to use:** When subprocess might spawn child processes
**Example:**
```python
# Source: https://docs.python.org/3/library/subprocess.html + WebSearch verification
import os
import signal

async def terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    """Terminate entire process group (including children)."""
    if proc.returncode is not None:
        return

    try:
        # Send SIGTERM to entire process group
        os.killpg(proc.pid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        # Force kill entire group
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
    except ProcessLookupError:
        pass  # Process already exited
```

### Anti-Patterns to Avoid
- **Using proc.communicate():** Waits for process to exit before returning output. Not suitable for daemons
- **Using proc.stdout.read():** Blocks until EOF. Daemons don't EOF
- **Forgetting await proc.wait():** Leaves zombie processes
- **Using shell=True:** Security risk, harder to terminate, unnecessary for this use case
- **Not setting PYTHONUNBUFFERED:** Output will be delayed until buffer fills

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Output buffering fix | Custom flush logic in daemons | PYTHONUNBUFFERED=1 env var | Zero code changes to daemons |
| Async readline | Threading + queues | asyncio.wait_for(readline(), timeout) | Async-native, simpler |
| Process cleanup | Manual kill logic | SIGTERM -> wait -> SIGKILL pattern | Handles edge cases |
| Task coordination | Manual task tracking | asyncio.TaskGroup | Automatic cancellation |
| Ring buffer | Custom list slicing | OutputBuffer (already exists) | Phase 7 already built this |

**Key insight:** The subprocess module and asyncio together provide all primitives needed. The complexity is in combining them correctly, not in building new abstractions.

## Common Pitfalls

### Pitfall 1: Subprocess Output Buffering
**What goes wrong:** Output appears all at once when subprocess exits, or not at all
**Why it happens:** Python switches to full buffering when stdout is piped
**How to avoid:** Set `PYTHONUNBUFFERED=1` in subprocess environment
**Warning signs:** Output only appears after process terminates or in large chunks

### Pitfall 2: readline() Blocks Forever
**What goes wrong:** Reader task never returns, blocks shutdown
**Why it happens:** Daemons don't close stdout, so EOF never arrives
**How to avoid:** Use `asyncio.wait_for(readline(), timeout=0.1)` with short timeout
**Warning signs:** Ctrl+C doesn't terminate cleanly, hangs waiting for reader

### Pitfall 3: Zombie Processes After Exit
**What goes wrong:** `ps aux` shows zombie processes, ports remain bound
**Why it happens:** Parent didn't call `proc.wait()` to reap exit status
**How to avoid:** Always `await proc.wait()` after termination, even after kill()
**Warning signs:** "Address already in use" on restart, `<defunct>` in ps output

### Pitfall 4: Orphan Subprocess Children
**What goes wrong:** Grandchild processes survive parent termination
**Why it happens:** SIGTERM only goes to direct child, not its children
**How to avoid:** Use `start_new_session=True` + `os.killpg()` for group termination
**Warning signs:** Processes with PPID=1 after TUI exit

### Pitfall 5: TaskGroup Exception Swallowing
**What goes wrong:** Subprocess reader exceptions are silently ignored
**Why it happens:** TaskGroup wraps exceptions in ExceptionGroup, often caught with `except*`
**How to avoid:** Log exceptions in reader tasks, use try/finally for cleanup
**Warning signs:** Reader stops working but no error message

### Pitfall 6: Signal Handler After Live Context
**What goes wrong:** Ctrl+C during subprocess spawn leaves terminal corrupt
**Why it happens:** TUIController.run() already handles this, but subprocess spawn must not break it
**How to avoid:** Spawn subprocesses AFTER signal handler registration but BEFORE Live context
**Warning signs:** Terminal corruption if Ctrl+C pressed during startup

### Pitfall 7: stderr Mixed Into Wrong Buffer
**What goes wrong:** Error messages from subprocess appear in wrong panel
**Why it happens:** stderr goes to different stream, not captured
**How to avoid:** Use `stderr=asyncio.subprocess.STDOUT` to merge streams
**Warning signs:** Error messages from daemon missing from TUI

## Code Examples

Verified patterns from official sources:

### Complete SubprocessManager Class
```python
# Source: Synthesized from asyncio docs + roguelynn.com patterns
import asyncio
import os
import sys
from dataclasses import dataclass

from operator_core.tui.buffer import OutputBuffer


@dataclass
class ManagedProcess:
    """Wrapper for subprocess with its output buffer."""
    process: asyncio.subprocess.Process
    buffer: OutputBuffer
    name: str


class SubprocessManager:
    """
    Manages subprocess lifecycle for TUI daemons.

    Handles spawning, output capture, and graceful shutdown.
    """

    def __init__(self) -> None:
        self._processes: dict[str, ManagedProcess] = {}
        self._shutdown = asyncio.Event()

    async def spawn(
        self,
        name: str,
        command: list[str],
        buffer_size: int = 50,
    ) -> ManagedProcess:
        """
        Spawn a subprocess with output capture.

        Args:
            name: Identifier for this process (e.g., "monitor", "agent")
            command: CLI arguments after "operator" (e.g., ["monitor", "run"])
            buffer_size: Max lines in output buffer

        Returns:
            ManagedProcess with process handle and output buffer
        """
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m", "operator_core.cli.main",
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        buffer = OutputBuffer(maxlen=buffer_size)
        managed = ManagedProcess(process=proc, buffer=buffer, name=name)
        self._processes[name] = managed
        return managed

    async def read_output(self, managed: ManagedProcess) -> None:
        """
        Read output from subprocess into buffer.

        Runs until shutdown event is set or process exits.
        Handles CancelledError gracefully for TaskGroup compatibility.
        """
        proc = managed.process
        buffer = managed.buffer

        try:
            while not self._shutdown.is_set() and proc.returncode is None:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=0.1,
                    )
                    if line:
                        buffer.append(line.decode("utf-8", errors="replace"))
                    elif proc.returncode is not None:
                        break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass  # Normal shutdown via TaskGroup

    async def terminate(
        self,
        name: str,
        timeout: float = 5.0,
    ) -> None:
        """
        Gracefully terminate a subprocess.

        Sends SIGTERM, waits for exit, escalates to SIGKILL if needed.
        """
        if name not in self._processes:
            return

        managed = self._processes[name]
        proc = managed.process

        if proc.returncode is not None:
            return

        # Graceful termination
        proc.terminate()

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill
            proc.kill()
            await proc.wait()

        del self._processes[name]

    async def terminate_all(self, timeout: float = 5.0) -> None:
        """Terminate all managed subprocesses."""
        self._shutdown.set()
        for name in list(self._processes.keys()):
            await self.terminate(name, timeout=timeout)

    def get_buffer(self, name: str) -> OutputBuffer | None:
        """Get output buffer for a subprocess."""
        if name in self._processes:
            return self._processes[name].buffer
        return None
```

### CLI Commands for Daemons
```python
# Commands verified from existing CLI code
# Monitor daemon:
["monitor", "run", "-i", "5", "--pd", "http://localhost:2379", "--prometheus", "http://localhost:9090"]

# Agent daemon:
["agent", "start", "-i", "5", "--pd", "http://localhost:2379", "--prometheus", "http://localhost:9090"]
```

### TUIController Integration Example
```python
# Source: Adaptation of existing TUIController + subprocess patterns
async def run(self) -> None:
    """Run TUI with subprocess management."""
    loop = asyncio.get_running_loop()

    # 1. Register signal handlers FIRST
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            functools.partial(self._handle_signal, sig),
        )

    # 2. Spawn subprocesses (after signal handlers, before Live)
    self._subprocess_mgr = SubprocessManager()
    monitor = await self._subprocess_mgr.spawn(
        "monitor",
        ["monitor", "run", "-i", "5"],
    )
    agent = await self._subprocess_mgr.spawn(
        "agent",
        ["agent", "start", "-i", "5"],
    )

    # 3. Initialize panels
    self._init_panels()

    # 4. Enter Live context with reader tasks
    with Live(
        self._layout,
        console=self.console,
        refresh_per_second=4,
        screen=False,
    ) as live:
        try:
            async with asyncio.TaskGroup() as tg:
                # Reader tasks
                tg.create_task(self._subprocess_mgr.read_output(monitor))
                tg.create_task(self._subprocess_mgr.read_output(agent))
                # Update loop that reads from buffers
                tg.create_task(self._update_loop(live))
                # Wait for shutdown signal
                await self._shutdown.wait()
        except* Exception:
            pass  # TaskGroup handles cancellation

    # 5. Clean shutdown
    await self._subprocess_mgr.terminate_all()
    self.console.print("[green]TUI shutdown complete[/green]")

def _refresh_panels(self) -> None:
    """Update panels from subprocess output buffers."""
    # Get latest output from buffers
    monitor_buffer = self._subprocess_mgr.get_buffer("monitor")
    agent_buffer = self._subprocess_mgr.get_buffer("agent")

    if monitor_buffer:
        self._layout["main"]["monitor"].update(
            make_panel(monitor_buffer.get_text(n=20), "Monitor", "blue")
        )

    if agent_buffer:
        self._layout["main"]["agent"].update(
            make_panel(agent_buffer.get_text(n=20), "Agent", "green")
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| subprocess.Popen + threads | asyncio.create_subprocess_exec | Python 3.4+ | Async-native, no threading needed |
| asyncio.gather() | asyncio.TaskGroup | Python 3.11 | Automatic sibling cancellation |
| Manual task tracking | TaskGroup context manager | Python 3.11 | Structured concurrency |
| signal.signal() | loop.add_signal_handler() | asyncio adoption | Safe async signal handling |

**Deprecated/outdated:**
- `asyncio.get_event_loop()`: Use `asyncio.get_running_loop()` inside async functions
- `return_exceptions=True` with gather(): Use TaskGroup instead for automatic cancellation

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal readline timeout value**
   - What we know: Too short (0.01s) wastes CPU, too long (1s) delays shutdown
   - What's unclear: Exact sweet spot depends on output frequency
   - Recommendation: Start with 0.1s, tune based on testing. Make configurable if needed.

2. **stderr handling strategy**
   - What we know: Can merge with stdout (simpler) or capture separately (more info)
   - What's unclear: Will users need to distinguish errors from output?
   - Recommendation: Merge for now (`stderr=STDOUT`). Errors are infrequent, simpler code.

3. **Buffer size per panel**
   - What we know: 50 lines is reasonable for typical terminal height
   - What's unclear: Optimal depends on panel height and font size
   - Recommendation: Start with 50, make configurable. Panel only shows ~20 lines anyway.

4. **Daemon CLI argument values**
   - What we know: `-i 5` sets 5-second check interval
   - What's unclear: Best interval for demo (fast enough to show activity, slow enough for readability)
   - Recommendation: Use 5 seconds for monitor, 5 seconds for agent. Can tune.

## Sources

### Primary (HIGH confidence)
- [Python asyncio-subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html) - create_subprocess_exec API, readline, wait, terminate, kill
- [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html) - start_new_session, env, bufsize parameters
- [Python asyncio-task documentation](https://docs.python.org/3/library/asyncio-task.html) - TaskGroup, task cancellation, wait_for

### Secondary (MEDIUM confidence)
- [Graceful Shutdowns with asyncio (roguelynn.com)](https://roguelynn.com/words/asyncio-graceful-shutdowns/) - Signal handler patterns, task cancellation order
- [Capture Python subprocess output in real-time (lucadrf.dev)](https://lucadrf.dev/blog/python-subprocess-buffers/) - PYTHONUNBUFFERED pattern, buffering explanation
- [Python 3.11 Preview: Task and Exception Groups (Real Python)](https://realpython.com/python311-exception-groups/) - TaskGroup semantics, ExceptionGroup handling

### Tertiary (LOW confidence)
- None - all critical findings verified with primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, well-documented, no version uncertainty
- Architecture: HIGH - Patterns verified in official docs and existing codebase
- Pitfalls: HIGH - All 7 pitfalls verified via official docs + multiple community sources

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - asyncio subprocess is stable)

---

## Key Answers to Phase Questions

**Q1: How exactly should subprocess spawning integrate with TUIController's run() method?**
- Spawn after signal handler registration but before Live context entry
- Store SubprocessManager instance on TUIController
- Create reader tasks inside TaskGroup alongside update loop

**Q2: What's the proper TaskGroup structure for reader tasks and subprocess lifecycle?**
- One reader task per subprocess
- Update loop task that reads from buffers
- All tasks in same TaskGroup for automatic cancellation
- Wait for shutdown event, then exit TaskGroup

**Q3: How to ensure subprocesses terminate even if parent crashes?**
- Use `start_new_session=True` when spawning
- Can use `os.killpg()` to terminate entire process group
- In worst case, processes become orphans but won't block restart

**Q4: How to handle subprocess stderr (mix with stdout or separate)?**
- Merge: `stderr=asyncio.subprocess.STDOUT`
- Simplifies code, single buffer per subprocess
- Error messages appear inline with output

**Q5: What are the exact CLI commands to invoke monitor and agent?**
- Monitor: `operator monitor run -i 5 --pd http://localhost:2379 --prometheus http://localhost:9090`
- Agent: `operator agent start -i 5 --pd http://localhost:2379 --prometheus http://localhost:9090`
- Via subprocess: `[sys.executable, "-m", "operator_core.cli.main", "monitor", "run", "-i", "5"]`
