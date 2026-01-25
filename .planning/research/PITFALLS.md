# Pitfalls Research: TUI Demo

**Domain:** Multi-panel TUI with live subprocess output (Rich + asyncio)
**Researched:** 2026-01-24
**Confidence:** HIGH (verified via official docs and GitHub issues)

## Critical Pitfalls

### 1. Subprocess Output Buffering Causes Delayed/Missing Output

**Problem:** When capturing stdout from subprocesses, output appears all at once at the end instead of streaming line-by-line, or lines are missing entirely. This is because when stdout is piped (not a TTY), most programs switch from line buffering to full buffering.

**Warning signs:**
- Output appears only when subprocess exits
- Long pauses followed by burst of output
- Python subprocess output is particularly delayed
- Works in terminal directly but not when captured

**Prevention:**
- For Python subprocesses: use `-u` flag or set `PYTHONUNBUFFERED=1`
- For general subprocesses: wrap with `stdbuf -oL` on Linux/macOS
- Consider using PTY (pseudo-terminal) via `pty.openpty()` to trick subprocess into line buffering
- Test with `print(flush=True)` in any Python code that will run as subprocess

**Phase to address:** Phase 1 (subprocess infrastructure) - Must be designed in from the start

**Sources:**
- [Luca Da Rin Fioretto - Capture Python subprocess output in real-time](https://lucadrf.dev/blog/python-subprocess-buffers/)
- [Processing subprocess output in realtime](https://tbrink.science/blog/2017/04/30/processing-the-output-of-a-subprocess-with-python-in-realtime/)

---

### 2. Rich Live Display + Concurrent Output = Corruption

**Problem:** Rich's Live display and Console printing have separate locks. When logging or printing from threads/tasks while Live is running, output gets lost, misplaced, or display artifacts persist. Log lines vanish entirely or status remnants corrupt output.

**Warning signs:**
- Log messages disappear intermittently
- Status bar text appears inline with log output
- Output appears in wrong order
- Visual artifacts after Live stops

**Prevention:**
- ALWAYS use `progress.console.print()` or `live.console.print()` for output during live display - never raw `print()`
- Enable `redirect_stdout=True, redirect_stderr=True` on Live (default)
- For logging during Live: configure logging handler to use the Live's console
- Avoid concurrent threads writing to console - funnel all output through asyncio tasks that coordinate with Live

**Phase to address:** Phase 1 (TUI scaffolding) - Architecture decision affects all panels

**Sources:**
- [GitHub Issue #1530 - live displays and console printing are not thread safe](https://github.com/willmcgugan/rich/issues/1530)
- [GitHub Issue #3523 - Progress with stream text output](https://github.com/Textualize/rich/issues/3523)

---

### 3. readline() Blocks Forever on Long-Running Subprocess

**Problem:** `await proc.stdout.readline()` blocks indefinitely if the subprocess never closes stdout. For daemon-like processes (monitor, agent), there's no EOF to signal "done reading." The coroutine hangs forever.

**Warning signs:**
- TUI freezes waiting for subprocess output
- Only first few lines appear, then nothing
- Works with short-lived commands, fails with daemons
- `asyncio.wait_for()` timeout constantly triggers

**Prevention:**
- Use `asyncio.wait_for(proc.stdout.readline(), timeout=0.1)` with short timeout
- Catch `asyncio.TimeoutError` and continue loop (no output available is not an error)
- Track subprocess lifecycle separately from output reading
- Pattern:
```python
while proc.returncode is None:
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.1)
        if line:
            handle_line(line)
    except asyncio.TimeoutError:
        continue  # No output, check if still running
```

**Phase to address:** Phase 2 (subprocess output capture) - Core reading loop design

**Sources:**
- [Python asyncio-subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html)
- [Making subprocess async friendly](https://blog.est.im/2024/stdout-11)

---

### 4. SIGINT Leaves Terminal in Broken State

**Problem:** If user presses Ctrl+C while in alternate screen mode or raw input mode, the terminal may be left unusable. No echo, no line editing, alternate screen persists. User has to type `reset` blindly.

**Warning signs:**
- After Ctrl+C, typing produces no visible output
- Terminal looks "stuck" on TUI display
- Previous command history inaccessible
- Works fine during normal exit, breaks on interrupt

**Prevention:**
- ALWAYS use context managers: `with console.screen():` or `with Live():`
- Register signal handlers BEFORE entering alternate screen
- In signal handler: explicitly stop Live, restore terminal, THEN exit
- Use `atexit.register()` as backup, but remember it doesn't run on SIGKILL
- Pattern:
```python
def cleanup():
    live.stop()
    console.set_alt_screen(False)

signal.signal(signal.SIGINT, lambda s, f: (cleanup(), sys.exit(130)))
atexit.register(cleanup)
```

**Phase to address:** Phase 1 (TUI scaffolding) - Must be in place before any Live usage

**Sources:**
- [Rich Live Display documentation](https://rich.readthedocs.io/en/latest/live.html)
- [Python atexit documentation](https://docs.python.org/3/library/atexit.html)
- [roguelynn - Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/)

---

### 5. Zombie/Orphan Subprocesses After Parent Crash

**Problem:** If the parent Python process crashes or is killed, spawned subprocesses (monitor, agent) keep running. Next demo run fails because ports are in use or multiple instances cause conflicts.

**Warning signs:**
- "Address already in use" errors on restart
- Multiple instances of monitor/agent running
- `ps aux` shows orphaned Python processes
- Works first time, fails on retry

**Prevention:**
- Create subprocess in new process group: `start_new_session=True`
- Track all subprocess PIDs explicitly
- On exit, send SIGTERM to process group, wait with timeout, then SIGKILL
- Use `proc.wait()` after `proc.terminate()` to reap zombies
- Pattern:
```python
proc = await asyncio.create_subprocess_exec(
    *cmd,
    start_new_session=True,  # Own process group
    stdout=asyncio.subprocess.PIPE
)
# On cleanup:
proc.terminate()
try:
    await asyncio.wait_for(proc.wait(), timeout=5.0)
except asyncio.TimeoutError:
    proc.kill()
    await proc.wait()
```

**Phase to address:** Phase 2 (subprocess lifecycle) - Must be part of subprocess abstraction

**Sources:**
- [How to Safely Kill Python Subprocesses Without Zombies](https://dev.to/generatecodedev/how-to-safely-kill-python-subprocesses-without-zombies-3h9g)
- [Handling sub-process hierarchies](https://stefan.sofa-rockers.org/2013/08/15/handling-sub-process-hierarchies-python-linux-os-x/)

---

### 6. asyncio.gather() Exception Doesn't Cancel Siblings

**Problem:** By default, if one task in `asyncio.gather()` raises an exception, the other tasks keep running. The exception propagates but the remaining coroutines aren't cancelled, leading to resource leaks and inconsistent state.

**Warning signs:**
- One panel crashes but others keep updating (partial UI)
- Resources not released after error
- Error handling seems to work but subprocess keeps running
- Cleanup code never executes

**Prevention:**
- Use `TaskGroup` (Python 3.11+) instead of `gather()` - automatically cancels siblings on exception
- If using `gather()`, wrap in try/except and explicitly cancel tasks
- For subprocess management, always cancel related tasks when subprocess dies
- Pattern:
```python
# Python 3.11+ preferred approach
async with asyncio.TaskGroup() as tg:
    tg.create_task(run_monitor())
    tg.create_task(run_agent())
    tg.create_task(update_ui())
# Any exception cancels all tasks
```

**Phase to address:** Phase 1 (async architecture) - Task management pattern choice

**Sources:**
- [Python asyncio-task documentation](https://docs.python.org/3/library/asyncio-task.html)
- [Asyncio Coroutine Patterns: Errors and cancellation](https://yeraydiazdiaz.medium.com/asyncio-coroutine-patterns-errors-and-cancellation-3bb422e961ff)

---

## Moderate Pitfalls

### 7. Keyboard Input Blocks Event Loop

**Problem:** Standard `input()` is blocking and will freeze the entire asyncio event loop. Even with threading, mixing terminal input with Rich Live display causes conflicts.

**Warning signs:**
- TUI freezes when waiting for keypress
- Rich animations stop during input
- Keypresses buffer and execute all at once
- Works in tests, breaks in real terminal

**Prevention:**
- Rich's basic `Prompt` classes are blocking - avoid during Live display
- Use non-blocking stdin reading with `select()` or `fcntl` + raw mode
- Consider Textual if complex keyboard handling needed
- For simple demo chapters: use a dedicated input reader task with small poll interval
- Pattern using select:
```python
import sys, select, tty, termios

def get_key_nonblocking():
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None
```

**Phase to address:** Phase 3 (chapter navigation) - Input handling design

**Sources:**
- [GitHub asyncio Issue #213 - Implement async input()](https://github.com/python/asyncio/issues/213)
- [Non-blocking stdin in Python 3](https://ballingt.com/nonblocking-stdin-in-python-3/)

---

### 8. Terminal Raw Mode Not Restored on Exception

**Problem:** When using raw mode for keyboard input, if an exception occurs before `termios.tcsetattr()` restores settings, the terminal is left in raw mode. No echo, no Ctrl+C, must close terminal.

**Warning signs:**
- After crash, can't see what you type
- Ctrl+C doesn't work
- Backspace doesn't work as expected
- Terminal needs `reset` or `stty sane` to recover

**Prevention:**
- ALWAYS use try/finally when modifying terminal settings
- Store original settings BEFORE any modification
- Restore in finally block AND in signal handlers
- Pattern:
```python
old_settings = termios.tcgetattr(sys.stdin)
try:
    tty.setcbreak(sys.stdin)
    # ... do input handling ...
finally:
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
```

**Phase to address:** Phase 3 (chapter navigation) - Must wrap any raw mode usage

**Sources:**
- [The Perils of Python's Raw Terminal Mode](https://runebook.dev/en/docs/python/library/tty/tty.setraw)

---

### 9. Pipe Buffer Deadlock

**Problem:** If a subprocess produces enough output that the OS pipe buffer fills up (typically 64KB), the subprocess blocks waiting for the pipe to drain. If the parent is waiting for the subprocess to exit before reading, both processes deadlock.

**Warning signs:**
- Subprocess hangs after producing some output
- Works with small output, hangs with verbose logging
- Process never exits, can't read more output
- Timeout on `proc.wait()` after some output was read

**Prevention:**
- ALWAYS read stdout/stderr continuously, don't wait for subprocess to exit first
- Use `communicate()` for simple cases (reads everything then waits)
- For live streaming: read in separate task, coordinate with process lifecycle
- Consider separate stderr task or `stderr=asyncio.subprocess.STDOUT` to merge

**Phase to address:** Phase 2 (output streaming) - Part of output reader design

**Sources:**
- [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html)
- [Python asyncio-subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html)

---

### 10. Progress/Live Refresh Rate Conflicts

**Problem:** Rich Live's refresh rate (default 4/sec) can conflict with update frequency of subprocess output or cause visual tearing. Too slow = laggy feel. Too fast = CPU waste and potential flicker.

**Warning signs:**
- Output appears in "chunks" instead of streaming
- Visual tearing or flicker
- High CPU usage during idle periods
- Updates visible only every 250ms even with fast output

**Prevention:**
- Set `refresh_per_second` based on expected update frequency
- For subprocess output: 10-20 fps is usually good balance
- Use `live.update()` to trigger immediate refresh on important changes
- Don't refresh faster than your eye can perceive (~60fps max)

**Phase to address:** Phase 1 (TUI scaffolding) - Configuration decision

**Sources:**
- [Rich Live Display documentation](https://rich.readthedocs.io/en/latest/live.html)

---

## Minor Pitfalls

### 11. Unicode/Emoji Width Causes Alignment Issues

**Problem:** Different terminals calculate character widths differently, especially for emoji and CJK characters. Tables and panels may misalign across different terminal emulators.

**Warning signs:**
- Alignment looks fine in iTerm, broken in Terminal.app
- Box drawing characters don't line up
- Text overflows panel boundaries
- Works on macOS, breaks on Linux

**Prevention:**
- Test on multiple terminal emulators early
- Avoid emoji in fixed-width layouts (or document limitation)
- Use ASCII box drawing when alignment is critical
- Rich handles most cases, but verify with target terminals

**Phase to address:** Phase 4 (polish) - Cosmetic, test across environments

**Sources:**
- [7 Things learned building a modern TUI Framework](https://www.textualize.io/blog/7-things-ive-learned-building-a-modern-tui-framework/)

---

### 12. Subprocess Environment Inheritance

**Problem:** Subprocesses inherit parent's environment, which may not include necessary PATH entries, virtual environment, or may include unwanted variables like `TERM` that affect output formatting.

**Warning signs:**
- Subprocess can't find commands that work in shell
- Color output works in terminal but not captured
- Virtual environment packages not found
- Subprocess behaves differently than when run manually

**Prevention:**
- Explicitly pass environment with `env=` parameter
- Include `PYTHONUNBUFFERED=1` explicitly
- Consider `TERM=dumb` to disable colors in captured output, or preserve for color support
- Ensure PATH includes necessary directories

**Phase to address:** Phase 2 (subprocess launch) - Part of subprocess configuration

---

## Terminal/TTY Considerations

### PTY vs Pipe Tradeoffs

| Approach | Pros | Cons |
|----------|------|------|
| Pipes (default) | Simple, portable | Full buffering, no TTY features |
| PTY | Line buffering, TTY features | Platform-specific, more complex, echo issues |
| stdbuf wrapper | Simple fix for buffering | Linux-only, not all programs respect it |

**Recommendation:** Start with pipes + `PYTHONUNBUFFERED=1` for Python subprocesses. Only add PTY complexity if buffering is still an issue with non-Python processes.

### Alternate Screen Best Practices

1. Always use context manager (`with console.screen():`)
2. Handle SIGINT before entering alternate screen
3. If crash leaves terminal stuck: type `reset` (works blind)
4. Test Ctrl+C handling early in development
5. Consider NOT using alternate screen for simpler cleanup

### Terminal Compatibility Matrix

| Feature | macOS Terminal | iTerm2 | Linux VT | Windows Terminal |
|---------|---------------|--------|----------|------------------|
| Rich Live | Yes | Yes | Yes | Yes (some limitations) |
| Alternate Screen | Yes | Yes | Yes | Yes |
| 256 Colors | Yes | Yes | Usually | Yes |
| True Color | No | Yes | Depends | Yes |
| Unicode | Yes | Yes | Varies | Yes |

---

## asyncio + Rich Gotchas

### Event Loop Integration

1. **Rich is sync, asyncio is async:** Rich's Live is thread-based internally, not native async. Use from main thread.

2. **Don't block the event loop:** Any blocking call (file I/O, CPU work) freezes Live refresh. Use `run_in_executor()` for blocking operations.

3. **Task exceptions silently swallowed:** If a task raises and you don't await it, exception may be lost. Always await tasks or use TaskGroup.

### Correct Pattern for Rich + asyncio

```python
async def main():
    console = Console()

    with Live(layout, console=console, refresh_per_second=10) as live:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(read_subprocess_output(proc, panel, live))
            tg.create_task(handle_keyboard(live))
            tg.create_task(update_metrics(live))
```

### Common Mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| `print()` during Live | Output lost or corrupted | Use `live.console.print()` |
| `input()` during Live | Event loop blocks | Use non-blocking stdin |
| Create Live from task | Thread issues | Create in main coroutine |
| Forget to stop Live | Terminal state leaked | Use context manager |

---

## Subprocess Management Issues

### Output Capture Patterns

**Pattern 1: Simple (blocks until done)**
```python
stdout, stderr = await proc.communicate()
# Only use for short-lived processes
```

**Pattern 2: Streaming (for long-running)**
```python
async def stream_output(proc, callback):
    while True:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), 0.1)
            if line:
                callback(line.decode())
            elif proc.returncode is not None:
                break
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
```

**Pattern 3: With PTY (for stubborn buffering)**
```python
import pty
master, slave = pty.openpty()
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=slave,
    stderr=slave
)
os.close(slave)
# Read from master fd
```

### Graceful Shutdown Sequence

1. Signal subprocesses to stop (SIGTERM)
2. Wait with timeout (5-10 seconds)
3. Force kill if needed (SIGKILL)
4. Reap zombie processes (`wait()`)
5. Stop Live display
6. Restore terminal settings
7. Exit

### Process Lifecycle States

```
STARTING -> RUNNING -> STOPPING -> STOPPED
              |           |
              v           v
           CRASHED    FORCE_KILLED
```

Track state explicitly to avoid operations on wrong state (e.g., reading from stopped process).

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|----------------|------------|
| 1 | TUI scaffolding | Terminal state corruption | Context managers + signal handlers |
| 1 | Async architecture | Task exception handling | Use TaskGroup not gather |
| 2 | Subprocess launch | Buffering delays output | PYTHONUNBUFFERED + test early |
| 2 | Output streaming | readline blocks forever | Timeout + returncode check |
| 3 | Keyboard input | Blocks event loop | Non-blocking stdin polling |
| 3 | Chapter transitions | State inconsistency | Explicit state machine |
| 4 | Polish | Terminal compatibility | Test multiple terminals |

---

## Summary of Prevention Strategies

### Day 1 Decisions (Phase 1)

- [ ] Choose TaskGroup over gather for task management
- [ ] Set up signal handlers before Live display
- [ ] Use context managers for all terminal state changes
- [ ] Design output routing through Live's console

### Subprocess Infrastructure (Phase 2)

- [ ] Add `PYTHONUNBUFFERED=1` to subprocess environment
- [ ] Implement output reading with timeout, not blocking readline
- [ ] Track subprocess lifecycle state explicitly
- [ ] Use `start_new_session=True` for clean process groups
- [ ] Implement graceful shutdown with SIGTERM -> wait -> SIGKILL

### Input Handling (Phase 3)

- [ ] Use non-blocking stdin with select/poll
- [ ] Restore terminal settings in finally block
- [ ] Test Ctrl+C handling at every chapter transition

### Testing Strategy

- [ ] Test Ctrl+C at every possible moment
- [ ] Test with verbose subprocess output (fill pipe buffer)
- [ ] Test rapid keypress sequences
- [ ] Test on at least 2 different terminal emulators
- [ ] Test subprocess crash scenarios

---

## Sources

### Official Documentation
- [Rich Live Display](https://rich.readthedocs.io/en/latest/live.html)
- [Python asyncio-subprocess](https://docs.python.org/3/library/asyncio-subprocess.html)
- [Python subprocess](https://docs.python.org/3/library/subprocess.html)
- [Python asyncio-task](https://docs.python.org/3/library/asyncio-task.html)
- [Python atexit](https://docs.python.org/3/library/atexit.html)

### GitHub Issues
- [Rich #1530 - Live displays thread safety](https://github.com/willmcgugan/rich/issues/1530)
- [Rich #3523 - Progress with stream output](https://github.com/Textualize/rich/issues/3523)
- [asyncio #213 - Implement async input()](https://github.com/python/asyncio/issues/213)

### Community Resources
- [roguelynn - Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/)
- [Luca Da Rin Fioretto - Capture subprocess output in real-time](https://lucadrf.dev/blog/python-subprocess-buffers/)
- [Non-blocking stdin in Python 3](https://ballingt.com/nonblocking-stdin-in-python-3/)
- [Asyncio Coroutine Patterns](https://yeraydiazdiaz.medium.com/asyncio-coroutine-patterns-errors-and-cancellation-3bb422e961ff)
- [Textualize Blog - 7 Things learned building a TUI](https://www.textualize.io/blog/7-things-ive-learned-building-a-modern-tui-framework/)
