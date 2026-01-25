# Research Summary: TUI Demo (v1.1)

**Project:** Operator TUI Demo Enhancement
**Domain:** Multi-panel terminal dashboard with live subprocess monitoring
**Researched:** 2026-01-24
**Confidence:** HIGH

## Executive Summary

This project enhances the existing `operator demo chaos` command with a multi-panel TUI dashboard that displays real daemon output, cluster health, and AI diagnosis in real-time. The research shows this is achievable using the existing Rich library (already in use) without adding heavy dependencies like Textual. The recommended approach is to run monitor and agent as subprocesses (not direct imports) to capture their output streams, avoiding complex refactoring of event loop management and signal handling.

The core technical challenge is coordinating three async tasks (subprocess output capture, keyboard input, and display updates) within Rich's Live display context. Research confirms this pattern is well-supported by Rich + asyncio, with multiple successful examples in the ecosystem (btop-style dashboards, k9s-inspired CLIs). The key is using `asyncio.TaskGroup` (Python 3.11+) for task lifecycle management and subprocess pipes with `PYTHONUNBUFFERED=1` to avoid buffering delays.

Critical risks center on subprocess output buffering (prevented with environment variables), terminal state corruption on crashes (mitigated with context managers and signal handlers), and zombie processes (solved with graceful shutdown sequences). The research identified 12 pitfalls, 6 critical, with concrete prevention strategies for each. The architecture is straightforward: spawn daemons as subprocesses, stream their stdout to ring buffers, render buffers into Rich panels, and refresh at 4-10 fps.

## Key Findings

### Recommended Stack

The existing stack is already sufficient. No new frameworks are needed. The research explicitly recommends **NOT** adding Textual, which would require rewriting existing code and add 2x memory overhead for features (interactive widgets) that a demo dashboard doesn't need.

**Core technologies (already in use):**
- **Rich 14.x** - Multi-panel layout via `Layout`, live updates via `Live`, panel rendering - already used extensively in existing code
- **asyncio** - Subprocess management, concurrent task coordination - stdlib, already in use
- **Typer** - CLI framework - already in use, demo remains a Typer command

**Minimal additions (2 packages, both zero-dependency):**
- **readchar 4.2.1** - Non-blocking keyboard input for chapter progression - minimal, cross-platform, 15KB
- **sparklines 0.7.0** - Ops/sec visualization as unicode bar charts - pure Python, outputs strings that render in Rich panels

**Subprocess output capture:** Use `asyncio.subprocess` (stdlib), no additional library needed. The pattern is `create_subprocess_exec` with `stdout=PIPE` and async line reading.

### Expected Features

The research clearly separates table stakes (expected from any monitoring dashboard) from differentiators (what makes this demo impressive).

**Must have (table stakes):**
- Multi-panel layout with clear boundaries - separate visual regions for different data streams
- Real-time updates without flicker - 1-2 second refresh with diff-based rendering (Rich Live handles this)
- Color-coded status indicators - green/yellow/red for healthy/warning/critical states
- Clear panel titles/headers - orient users instantly to what they're seeing
- Running daemon status indicators - show that monitor and agent are actually running
- Activity indicators (heartbeat/spinner) - visual proof of liveness
- Key-press instructions visible - show available keyboard shortcuts in footer
- Chapter/stage progression via keypress - presenter controls demo pacing, not automatic timers

**Should have (high-impact differentiators):**
- Real daemon output in dedicated panels - shows actual monitor/agent logs as they happen, proves "this is really running"
- Ops/sec histogram or sparkline - visual representation of traffic degradation when fault occurs
- Degradation color shift - workload panel color changes when performance degrades
- Chapter/stage panel with context - "Chapter 2: Injecting Fault" with brief explanation
- Countdown timers for key moments - "Detecting fault... 3s" builds tension
- Sub-second detection highlighting - flash or emphasize the moment detection occurs

**Defer to v2+ (complexity not justified for demo):**
- Timeline/event log - chronological list of what happened
- Streaming diagnosis display - panel populates as AI responds (vs. appearing all at once)
- Advanced sparkline/histogram - simple bar chart may suffice

**Explicitly avoid (anti-features):**
- Scrolling log panels - dashboards should synthesize, not dump raw logs
- Mouse-driven navigation - conference demos need keyboard-only for presenter flow
- Configuration UI in demo - demo should "just work" without configuration
- Multiple themes or customization - one polished theme is better
- Persistent state between runs - each demo run should be fresh

### Architecture Approach

The architecture is based on subprocess isolation rather than direct import. The existing MonitorLoop and AgentRunner daemons should NOT be modified - they work correctly as standalone processes. The TUI wraps them as subprocesses and captures their output.

**Major components:**
1. **TUI Controller** - Owns Rich Live + Layout, coordinates all async tasks via TaskGroup
2. **Subprocess Manager** - Spawns monitor/agent via `asyncio.create_subprocess_exec`, handles graceful shutdown (SIGTERM with timeout, then SIGKILL)
3. **Output Readers** - Async tasks that stream subprocess stdout line-by-line into ring buffers (deque with maxlen)
4. **Panel Renderers** - Convert buffer contents into Rich Panel objects, apply color coding based on state
5. **Keyboard Listener** - Non-blocking stdin polling (select.select on Unix, msvcrt.kbhit on Windows), advances chapter state machine
6. **Cluster Poller** - Direct import of existing PDClient/PrometheusClient to get health metrics

**Why subprocesses over direct import:**
- Signal isolation - each subprocess handles its own SIGINT/SIGTERM, TUI can send targeted signals
- Output capture - subprocess stdout is a stream we can read line-by-line
- Clean lifecycle - start, stop, restart without complex state management
- Realistic demo - shows what "running the operator" actually looks like
- No event loop conflicts - each subprocess has its own `asyncio.run()`

**Data flow:**
1. TUI spawns monitor/agent subprocesses with `stdout=PIPE`
2. Each subprocess gets an async reader task that calls `await proc.stdout.readline()`
3. Reader callbacks append lines to OutputBuffer (ring buffer)
4. Rich Live refreshes at 4-10 fps, rendering buffers into panels
5. Keyboard listener task polls stdin every 50ms, advances chapter on keypress
6. Chapter transitions trigger Docker operations (kill container) and update narration panel

### Critical Pitfalls

The research identified 6 critical pitfalls that will block the demo if not addressed in architecture phase:

1. **Subprocess output buffering causes delayed/missing output** - When stdout is piped, Python switches from line buffering to full buffering. Output appears all at once at the end or not at all. **Prevention:** Set `PYTHONUNBUFFERED=1` in subprocess environment. Test with verbose output early. Consider PTY for non-Python subprocesses.

2. **Rich Live display + concurrent output = corruption** - Rich's Live and Console printing have separate locks. Logging from tasks while Live is running causes lost output or visual artifacts. **Prevention:** ALWAYS use `live.console.print()`, never raw `print()`. Enable `redirect_stdout=True` on Live. Funnel all output through the Live's console.

3. **readline() blocks forever on long-running subprocess** - `await proc.stdout.readline()` blocks indefinitely if subprocess never closes stdout (daemons don't EOF). **Prevention:** Use `asyncio.wait_for(proc.stdout.readline(), timeout=0.1)` with short timeout. Track subprocess lifecycle separately from output reading. Continue loop on timeout.

4. **SIGINT leaves terminal in broken state** - If user presses Ctrl+C while in alternate screen or raw mode, terminal may be unusable (no echo, stuck display). **Prevention:** ALWAYS use context managers (`with Live():`). Register signal handlers BEFORE entering alternate screen. In signal handler: stop Live, restore terminal, THEN exit.

5. **Zombie/orphan subprocesses after parent crash** - If TUI crashes, spawned monitor/agent keep running. Next demo run fails with "address already in use." **Prevention:** Create subprocesses with `start_new_session=True`. On exit, send SIGTERM, wait with timeout, then SIGKILL. Use `proc.wait()` to reap zombies.

6. **asyncio.gather() exception doesn't cancel siblings** - By default, if one task raises, other tasks keep running. Causes resource leaks. **Prevention:** Use `asyncio.TaskGroup` (Python 3.11+) instead of `gather()` - automatically cancels siblings on exception. For subprocess management, always cancel related tasks when subprocess dies.

## Implications for Roadmap

Based on dependencies and testability, the recommended build order is 7 phases:

### Phase 1: TUI Scaffolding and Layout
**Rationale:** Foundation that everything else builds on. Can test with static content before subprocess complexity. Must establish terminal management and task coordination patterns early to avoid rework.

**Delivers:**
- OutputBuffer class (ring buffer with maxlen)
- Layout structure (5 panels: cluster status, narration, monitor output, agent output, workload)
- Panel factory functions for each panel type
- Rich Live context with proper signal handling

**Addresses pitfalls:**
- Terminal state corruption (context managers + signal handlers)
- Task exception handling (TaskGroup architecture choice)

**Research flag:** Standard patterns, well-documented in Rich docs. Skip phase-level research.

### Phase 2: Subprocess Management
**Rationale:** Core infrastructure for running monitor/agent. Independent of keyboard/UI complexity. Can test with simple echo commands before integrating real daemons.

**Delivers:**
- Subprocess spawning functions with proper environment (PYTHONUNBUFFERED=1)
- Graceful shutdown sequence (SIGTERM -> wait -> SIGKILL)
- Async output reader with timeout pattern
- Process lifecycle tracking

**Addresses pitfalls:**
- Subprocess output buffering (environment variables)
- readline blocking forever (timeout pattern)
- Zombie processes (graceful shutdown, start_new_session=True)
- Pipe buffer deadlock (continuous reading)

**Research flag:** High complexity, edge cases in signal handling and buffering. Consider phase-level research if issues arise during implementation.

### Phase 3: Live Output Capture and Display
**Rationale:** Depends on Phase 2 (subprocess management) and Phase 1 (layout). The "demo within a demo" - showing real daemons running is the core value prop.

**Delivers:**
- Integration of subprocess reader with OutputBuffer
- Monitor panel rendering with color coding
- Agent panel rendering with color coding
- Real-time refresh at 4-10 fps

**Addresses pitfalls:**
- Rich Live + concurrent output corruption (use live.console exclusively)
- Refresh rate tuning (10 fps for smooth subprocess output)

**Research flag:** Standard patterns once architecture is in place. Skip phase-level research.

### Phase 4: Cluster Status Polling
**Rationale:** Independent of subprocess work. Reuses existing PDClient/PrometheusClient. Can run in parallel with Phase 3 if needed.

**Delivers:**
- poll_cluster_status() async function
- Cluster status panel with node health (3/3 healthy vs. 2/3 healthy)
- Color-coded health indicators (green/yellow/red)
- Integration with existing subject code

**Addresses features:**
- Cluster status summary (table stakes)
- Node count with health breakdown (table stakes)

**Research flag:** Uses existing clients. Skip phase-level research.

### Phase 5: Keyboard Input and Chapter Navigation
**Rationale:** Depends on Phase 1 (layout exists to update). Simple in isolation, complex in integration with Live display. Non-blocking input is critical for async compatibility.

**Delivers:**
- Non-blocking stdin polling (select.select on Unix, msvcrt.kbhit on Windows)
- Keyboard listener async task
- Chapter state machine (healthy -> fault -> diagnosis -> recovery -> exit)
- Narration panel updates on chapter transition

**Addresses pitfalls:**
- Keyboard input blocking event loop (non-blocking polling)
- Terminal raw mode not restored (try/finally wrapper)

**Research flag:** Platform-specific behavior (Windows vs. Unix). May need phase-level research for Windows compatibility.

### Phase 6: Workload Visualization
**Rationale:** Depends on Phase 4 (cluster polling) for metrics. Uses sparklines library. Visual polish that makes degradation unmissable.

**Delivers:**
- MetricsTracker with rolling window (30 data points)
- Sparkline rendering via sparklines library
- Workload panel with ops/sec display
- Color shift on degradation (green -> yellow -> red)

**Addresses features:**
- Ops/sec histogram or sparkline (differentiator)
- Degradation color shift (differentiator)

**Research flag:** Standard library integration. Skip phase-level research.

### Phase 7: Fault Injection Integration
**Rationale:** Depends on all previous phases (full TUI must exist to show fault impact). Reuses existing ChaosDemo Docker code. Final integration that brings everything together.

**Delivers:**
- Docker client integration (reuse from existing chaos.py)
- Kill container on chapter transition (keypress triggers)
- Restart container on recovery chapter
- Container status in cluster panel
- End-to-end demo flow

**Addresses features:**
- Chapter progression via keypress (table stakes)
- Before/after cluster state (differentiator)
- Detection moment highlighting (differentiator)

**Research flag:** Reuses existing code. Skip phase-level research.

### Phase Ordering Rationale

- **Foundation first (Phase 1-2):** Layout and subprocess management are independent building blocks. Getting these right early prevents rework.
- **Value-driven middle (Phase 3-4):** Live output capture and cluster status are the core demo features. Build these before polish.
- **Polish last (Phase 5-7):** Keyboard navigation, workload viz, and fault injection are the "wow" factors but depend on foundations.
- **Parallel-friendly:** Phase 3 and Phase 4 can run in parallel if resources allow.
- **Testability:** Each phase is independently testable. Phase 2 can be tested with simple subprocesses. Phase 3 can use mock buffers. Phase 5 can be tested with static layouts.

### Research Flags

**Phases needing potential deeper research:**
- **Phase 2 (Subprocess Management):** Complex edge cases in signal handling and buffering. If buffering issues persist despite `PYTHONUNBUFFERED=1`, may need PTY research.
- **Phase 5 (Keyboard Input):** Platform-specific behavior. Windows compatibility may need focused research.

**Phases with standard patterns (skip research):**
- **Phase 1:** Well-documented Rich patterns
- **Phase 3:** Direct application of Phase 1 + Phase 2
- **Phase 4:** Uses existing clients
- **Phase 6:** Standard library integration
- **Phase 7:** Code reuse from existing demo

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Rich 14.x verified on PyPI, official docs comprehensive, asyncio is stdlib. readchar and sparklines are stable, zero-dependency packages. |
| Features | MEDIUM | Feature priorities are based on established TUI patterns (k9s, btop) and conference demo best practices. Technical audience expectations are well-understood, but some features (detection highlighting timing) may need adjustment during implementation. |
| Architecture | MEDIUM | Subprocess pattern is verified via asyncio docs and community examples. Rich + asyncio compatibility is confirmed. However, the specific combination (3 concurrent tasks + Live display + keyboard input) hasn't been battle-tested in this exact configuration. |
| Pitfalls | HIGH | All 6 critical pitfalls are verified via GitHub issues, official docs, and community blogs. Prevention strategies are concrete and testable. Phase mapping is explicit. |

**Overall confidence:** HIGH

The technical approach is sound and well-documented. The main uncertainty is in the "feel" of the demo (timing, color choices, panel sizing) which requires iteration. The architecture avoids risky dependencies and leverages existing stable code.

### Gaps to Address

**Gaps identified during research:**

- **Windows keyboard input compatibility:** Research focused on Unix patterns (select.select). Windows requires msvcrt.kbhit(). Implementation will need platform-specific code. Address in Phase 5 with platform detection.

- **PTY vs. Pipe for non-Python subprocesses:** If the operator adds non-Python daemons in the future, buffering may require PTY. Current implementation with Python subprocesses + PYTHONUNBUFFERED=1 is sufficient. Document limitation.

- **Optimal refresh rate:** Research suggests 4-10 fps, but the "right" rate depends on subprocess output frequency and terminal performance. Plan to make refresh_per_second configurable and tune during testing.

- **Detection timing tuning:** Research doesn't specify exact countdown duration or highlight timing. These are presentation details that need user testing. Plan for iteration in Phase 7.

- **Graceful degradation on AI timeout:** Research doesn't cover fallback UX if Claude API is slow or fails. Existing ChaosDemo has this logic - ensure TUI version preserves it. Document in Phase 7 requirements.

## Sources

### Primary (HIGH confidence)

**Official documentation (verified 2026-01-24):**
- [Rich Live Display](https://rich.readthedocs.io/en/latest/live.html) - Live display patterns, refresh rates, context management
- [Rich Layout](https://rich.readthedocs.io/en/latest/layout.html) - Multi-panel layout splitting, ratios, nesting
- [Python asyncio-subprocess](https://docs.python.org/3/library/asyncio-subprocess.html) - create_subprocess_exec, stdout.readline, pipe patterns
- [Python asyncio-task](https://docs.python.org/3/library/asyncio-task.html) - TaskGroup (Python 3.11+), gather behavior, exception handling
- [readchar PyPI](https://pypi.org/project/readchar/) - Version 4.2.1, cross-platform keyboard input
- [sparklines PyPI](https://pypi.org/project/sparklines/) - Version 0.7.0, unicode visualization

**Verified GitHub issues:**
- [Rich #1530](https://github.com/willmcgugan/rich/issues/1530) - Live displays thread safety, confirmed prevention strategy
- [Rich #3523](https://github.com/Textualize/rich/issues/3523) - Progress with stream output, confirmed console routing pattern

### Secondary (MEDIUM confidence)

**Community resources:**
- [Will McGugan - Building Rich Terminal Dashboards](https://www.willmcgugan.com/blog/tech/post/building-rich-terminal-dashboards/) - Layout patterns from Rich author
- [roguelynn - Graceful Shutdowns with asyncio](https://roguelynn.com/words/asyncio-graceful-shutdowns/) - Signal handling patterns
- [Luca Da Rin Fioretto - Capture subprocess output in real-time](https://lucadrf.dev/blog/python-subprocess-buffers/) - Buffering solutions, PYTHONUNBUFFERED pattern
- [Asyncio Coroutine Patterns](https://yeraydiazdiaz.medium.com/asyncio-coroutine-patterns-errors-and-cancellation-3bb422e961ff) - TaskGroup vs. gather patterns

**Reference implementations:**
- [k9s - Kubernetes CLI](https://k9scli.io/) - Real-time cluster monitoring UX patterns
- [btop](https://linuxblog.io/btop-the-htop-alternative/) - System monitoring dashboard patterns

### Tertiary (LOW confidence)

**Demo best practices:**
- [How to Present Chaos Testing Effectively](https://www.resumly.ai/blog/how-to-present-chaos-testing-and-learnings-effectively) - Presentation narrative, pacing
- [Live Demos Guide](https://www.arcade.software/post/live-demos-guide) - Demo preparation, recovery from failure
- [Dashboard Design UX Patterns](https://www.pencilandpaper.io/articles/ux-pattern-analysis-data-dashboards) - F-pattern, card layout (general UX, not TUI-specific)

---
*Research completed: 2026-01-24*
*Ready for roadmap: yes*
