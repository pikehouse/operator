# Phase 34: Demo End-to-End Validation - Research

**Researched:** 2026-01-28
**Domain:** End-to-end demo testing, subprocess integration, pytest integration patterns
**Confidence:** HIGH

## Summary

This phase validates that both TiKV and rate limiter demos work end-to-end with the v3.0 agent_lab architecture. The codebase already contains a complete demo infrastructure with TUI panels, subprocess management, chapter flow, and health polling. Prior phases (Phase 33) completed database integration and signal handling. The remaining work is to verify existing integration, create proper integration tests, and validate that subprocess output displays correctly in the TUI agent panel.

The demo architecture follows a clean separation: `demo/` contains subject-specific orchestration (chapters, chaos injection), while `operator_core/tui/` provides reusable TUI infrastructure (subprocess management, panels, keyboard handling). The v3.0 agent runs via `python -m operator_core.agent_lab` and already integrates with the TUI via SubprocessManager.

**Primary recommendation:** Create pytest-based integration tests that spawn the demos programmatically, inject chaos, verify monitor detection and agent panel output, then validate full flow completion. Use existing test patterns from scripts/test-demo-flow.py and scripts/test-tui-demo.py as foundation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.0+ | Test framework | Python standard, excellent async support |
| pytest-asyncio | 1.3.0+ | Async test support | Official pytest asyncio plugin |
| Rich | Latest | TUI rendering | Already used for demo panels |
| python-on-whales | Latest | Docker control | Already used for chaos injection |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | Latest | HTTP client for health checks | Already in use for health polling |
| redis.asyncio | Latest | Redis client for validation | Rate limiter demos |
| subprocess (stdlib) | Python 3.11+ | Process management | Test harness subprocess control |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-asyncio | pytest-trio | Trio not used in codebase, asyncio already standard |
| pytest | unittest | pytest provides better fixtures, async support |

**Installation:**
Already installed via pyproject.toml. No additional dependencies needed.

## Architecture Patterns

### Recommended Project Structure
```
scripts/
├── test-demo-flow.py        # Existing component validation
├── test-tui-demo.py          # Existing TUI integration test
└── integration_tests/        # NEW: Proper pytest integration tests
    ├── test_tikv_demo_e2e.py
    └── test_ratelimiter_demo_e2e.py

demo/
├── __main__.py               # Demo entry point
├── tui_integration.py        # TUIDemoController (subject-agnostic)
├── tikv.py                   # TiKV chapters + chaos callbacks
├── ratelimiter.py            # Rate limiter chapters + chaos callbacks
└── types.py                  # Chapter, DemoState protocols

packages/operator-core/src/operator_core/
├── agent_lab/
│   ├── __main__.py           # Entry point: python -m operator_core.agent_lab
│   ├── loop.py               # Agent poll loop with tool_runner
│   └── ticket_ops.py         # TicketOpsDB context manager
└── tui/
    ├── subprocess.py         # SubprocessManager for daemon processes
    ├── keyboard.py           # KeyboardTask for input handling
    └── layout.py             # Rich panel layout
```

### Pattern 1: Integration Test Structure
**What:** pytest-based integration test that spawns demo components programmatically
**When to use:** Testing end-to-end demo flows
**Example:**
```python
# Source: Codebase analysis + pytest best practices
import asyncio
import pytest
from pathlib import Path
from demo.tikv import TIKV_CHAPTERS
from demo.tikv_health import TiKVHealthPoller
from demo.tui_integration import TUIDemoController

@pytest.mark.asyncio
async def test_tikv_demo_runs_end_to_end(tmp_path):
    """Test DEMO-04: TiKV demo completes full flow."""
    # Setup: Clean database
    db_path = tmp_path / "tickets.db"

    # Create controller with null console (avoid terminal issues)
    from rich.console import Console
    console = Console(force_terminal=False, no_color=True)

    controller = TUIDemoController(
        subject_name="tikv",
        chapters=TIKV_CHAPTERS,
        health_poller=TiKVHealthPoller(),
        console=console,
    )

    # Spawn subprocesses and advance through chapters
    # ... test logic ...

    # Verify: Monitor detected violations, agent processed ticket
    assert "violation(s) detected" in monitor_output
    assert "resolved" in agent_output or "escalated" in agent_output
```

### Pattern 2: Subprocess Output Validation
**What:** Capture and assert on subprocess output from agent panel
**When to use:** Verifying DEMO-06 (agent panel displays output)
**Example:**
```python
# Source: packages/operator-core/src/operator_core/tui/subprocess.py
from operator_core.tui.subprocess import SubprocessManager

mgr = SubprocessManager()
agent_proc = await mgr.spawn(
    "agent",
    ["-u", "-m", "operator_core.agent_lab", str(db_path)],
    buffer_size=100,
)

# Start reader task
reader_task = asyncio.create_task(mgr.read_output(agent_proc))

# Wait for agent to process
await asyncio.sleep(5)

# Verify output captured
agent_buf = mgr.get_buffer("agent")
assert agent_buf is not None
output = agent_buf.get_text()
assert "Processing ticket" in output
assert "[Claude]" in output or "[Tool Call]" in output
```

### Pattern 3: Chapter Flow Testing
**What:** Programmatically advance through demo chapters and verify callbacks execute
**When to use:** Testing chapter progression, auto-advance, callbacks
**Example:**
```python
# Source: demo/tui_integration.py + demo/tikv.py
from demo.types import DemoState, Chapter

# Create demo state
chapters = [
    Chapter(title="Welcome", narration="..."),
    Chapter(title="Fault", narration="...", on_enter=inject_fault_callback),
]
state = DemoState(chapters=chapters)

# Advance and execute callback
state.advance()
chapter = state.get_current()
if chapter.on_enter:
    await chapter.on_enter()

# Verify chaos was injected
assert killed_container is not None
```

### Pattern 4: Async Test Fixtures
**What:** pytest-asyncio fixtures for shared setup/teardown
**When to use:** Managing demo infrastructure lifecycle across tests
**Example:**
```python
# Source: pytest-asyncio best practices
import pytest_asyncio

@pytest_asyncio.fixture
async def demo_infrastructure(tmp_path):
    """Setup demo infrastructure with clean database."""
    db_path = tmp_path / "tickets.db"

    # Start docker cluster if needed
    # ... setup code ...

    yield db_path

    # Cleanup
    await cleanup_load_generators()
    db_path.unlink(missing_ok=True)
```

### Anti-Patterns to Avoid
- **Forgetting @pytest.mark.asyncio decorator:** Tests will fail silently or hang
- **Not using null console for programmatic tests:** Rich will try to access terminal and fail
- **Blocking on subprocess.wait() without timeout:** Tests hang if process doesn't exit
- **Not cleaning up subprocesses:** Zombie processes persist after test failures
- **Testing with real API keys in CI:** Use mocks or test mode for CI environments

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Subprocess output capture | Custom pipe reading | SubprocessManager (already exists) | Handles buffering, timeouts, shutdown gracefully |
| Async test fixtures | Manual setup/teardown | pytest-asyncio fixtures | Automatic cleanup, proper event loop management |
| Terminal rendering in tests | Try to use Live context | Rich Console(force_terminal=False) | Avoids terminal state issues in CI |
| Docker container management | subprocess.run("docker ...") | python-on-whales (already in use) | Type-safe, handles errors, already used in demos |
| Test database cleanup | Manual file deletion | tempfile.TemporaryDirectory | Automatic cleanup even on test failure |

**Key insight:** The demo infrastructure is already complete. Don't rebuild components - test what exists. The existing scripts/test-demo-flow.py and scripts/test-tui-demo.py provide excellent patterns but aren't proper pytest tests yet.

## Common Pitfalls

### Pitfall 1: SubprocessManager Shutdown Race Conditions
**What goes wrong:** Tests hang because subprocesses aren't terminated properly, or reader tasks continue after test exits
**Why it happens:** SubprocessManager has multiple async components (reader tasks, processes) that must shut down in correct order
**How to avoid:** Always use try/finally pattern and set shutdown event before terminating
**Warning signs:** Tests that hang on cleanup, pytest warnings about unawaited coroutines

**Example:**
```python
# Source: packages/operator-core/src/operator_core/tui/subprocess.py
mgr = SubprocessManager()
try:
    proc = await mgr.spawn("agent", [...])
    reader_task = asyncio.create_task(mgr.read_output(proc))
    # ... test logic ...
finally:
    mgr.shutdown.set()  # Signal readers to stop
    await mgr.terminate_all()  # Terminate processes
    reader_task.cancel()  # Cancel reader task
    try:
        await reader_task
    except asyncio.CancelledError:
        pass
```

### Pitfall 2: Agent Panel Output Timing
**What goes wrong:** Test checks agent output too early, before agent has processed ticket
**Why it happens:** Agent poll loop has 1 second sleep, plus ticket processing time
**How to avoid:** Wait sufficiently (5-10 seconds) or poll until expected output appears
**Warning signs:** Intermittent test failures, "output not in buffer" assertions

**Example:**
```python
# BAD: Check immediately
agent_buf = mgr.get_buffer("agent")
assert "resolved" in agent_buf.get_text()  # May fail

# GOOD: Wait for agent to process
await asyncio.sleep(5)  # Agent poll interval + processing time
agent_buf = mgr.get_buffer("agent")
output = agent_buf.get_text()
assert "Processing ticket" in output
```

### Pitfall 3: Docker State Between Tests
**What goes wrong:** Tests interfere with each other because containers/data persist
**Why it happens:** Demo chaos leaves containers in killed state, counters in Redis, etc.
**How to avoid:** Each test should clean database, flush Redis, restart killed containers
**Warning signs:** Tests pass individually but fail when run together

**Example:**
```python
# Source: scripts/run-demo.sh cleanup pattern
@pytest.fixture(autouse=True)
async def clean_demo_state():
    """Ensure clean state before each test."""
    # Clear ticket database
    db_path = Path.home() / ".operator" / "tickets.db"
    db_path.unlink(missing_ok=True)

    # Flush Redis
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "docker-redis-1", "redis-cli", "FLUSHALL"
    )
    await proc.wait()

    # Restart any killed containers
    # ... restart logic ...

    yield
```

### Pitfall 4: pytest-asyncio Mode Configuration
**What goes wrong:** Tests don't run or run with wrong event loop
**Why it happens:** pytest-asyncio requires explicit mode configuration
**How to avoid:** Set asyncio_mode = "auto" in pyproject.toml
**Warning signs:** Tests skip with "not an async function" or hang indefinitely

**Example:**
```toml
# Source: pyproject.toml (already configured correctly)
[tool.pytest.ini_options]
testpaths = ["packages", "scripts/integration_tests"]
asyncio_mode = "auto"
```

## Code Examples

Verified patterns from official sources:

### Full Integration Test Template
```python
# Source: scripts/test-tui-demo.py + pytest-asyncio best practices
import asyncio
import pytest
from pathlib import Path
from rich.console import Console

from demo.tikv import TIKV_CHAPTERS
from demo.tikv_health import TiKVHealthPoller
from demo.tui_integration import TUIDemoController
from operator_core.tui.subprocess import SubprocessManager

@pytest.mark.asyncio
async def test_tikv_demo_end_to_end(tmp_path):
    """
    Test DEMO-04: TiKV demo runs end-to-end.

    Verifies:
    - Startup: Monitor and agent subprocesses start
    - Fault injection: Chaos callback kills TiKV node
    - Agent diagnosis: Monitor detects, agent processes ticket
    - Resolution: Agent resolves ticket (autonomous or escalated)
    """
    db_path = tmp_path / "tickets.db"

    # Create controller with null console
    console = Console(force_terminal=False, no_color=True)
    health_poller = TiKVHealthPoller(
        pd_endpoint="http://localhost:2379",
        poll_interval=2.0,
    )

    controller = TUIDemoController(
        subject_name="tikv",
        chapters=TIKV_CHAPTERS,
        health_poller=health_poller,
        console=console,
    )

    # Initialize subprocess manager
    mgr = SubprocessManager()

    try:
        # Spawn monitor subprocess
        monitor_proc = await mgr.spawn(
            "monitor",
            ["-u", "-m", "operator_core.cli.main", "monitor", "run",
             "--subject", "tikv", "-i", "3"],
            buffer_size=50,
        )

        # Spawn agent subprocess
        agent_proc = await mgr.spawn(
            "agent",
            ["-u", "-m", "operator_core.agent_lab", str(db_path)],
            buffer_size=100,
            env={"OPERATOR_SAFETY_MODE": "execute"},
        )

        # Start reader tasks
        reader_tasks = [
            asyncio.create_task(mgr.read_output(monitor_proc)),
            asyncio.create_task(mgr.read_output(agent_proc)),
        ]

        # Start health poller
        import httpx
        health_poller._running = True
        health_poller._client = httpx.AsyncClient(timeout=5.0)
        poller_task = asyncio.create_task(health_poller.run())

        # Wait for initialization
        await asyncio.sleep(4)

        # Advance to fault injection chapter and execute
        controller._demo_state.advance()  # Welcome -> Stage 1
        controller._demo_state.advance()  # Stage 1 -> Load

        stage_load = controller._demo_state.get_current()
        if stage_load.on_enter:
            await stage_load.on_enter()

        controller._demo_state.advance()  # Load -> Fault
        stage_fault = controller._demo_state.get_current()
        if stage_fault.on_enter:
            await stage_fault.on_enter()  # Injects fault

        # Wait for monitor to detect and agent to process
        await asyncio.sleep(10)

        # Verify monitor detected violation
        monitor_buf = mgr.get_buffer("monitor")
        assert monitor_buf is not None
        monitor_output = monitor_buf.get_text()
        assert "violation(s) detected" in monitor_output

        # Verify agent processed ticket (DEMO-06)
        agent_buf = mgr.get_buffer("agent")
        assert agent_buf is not None
        agent_output = agent_buf.get_text()
        assert "Processing ticket" in agent_output
        assert "[Claude]" in agent_output or "[Tool Call]" in agent_output

    finally:
        # Cleanup
        health_poller.stop()
        mgr.shutdown.set()
        await mgr.terminate_all()

        for task in reader_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass

        if health_poller._client:
            await health_poller._client.aclose()
```

### Subprocess Output Validation Pattern
```python
# Source: packages/operator-core/src/operator_core/tui/subprocess.py
def verify_agent_panel_output(subprocess_manager: SubprocessManager):
    """
    Test DEMO-06: Agent panel displays subprocess output.

    Verifies SubprocessManager captures output and makes it available
    via get_buffer() for TUI panel display.
    """
    agent_buf = subprocess_manager.get_buffer("agent")
    assert agent_buf is not None, "Agent buffer should exist"

    # Check buffer has content
    assert len(agent_buf) > 0, "Agent buffer should contain output"

    # Check for expected agent log patterns
    output = agent_buf.get_text()

    # Agent should log these patterns (from loop.py)
    expected_patterns = [
        "Agent loop starting",  # Startup message
        "Processing ticket",    # Ticket processing
        "[Claude]",             # Reasoning output
        "[Tool Call]",          # Tool execution
        "[Tool Result]",        # Tool results
    ]

    found_patterns = [p for p in expected_patterns if p in output]
    assert len(found_patterns) >= 2, \
        f"Expected agent output patterns, found {found_patterns}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual test scripts (test-demo-flow.py) | pytest-based integration tests | Phase 34 (this phase) | Proper test infrastructure, CI integration |
| agent_v2 with manual orchestration | agent_lab v3.0 with tool_runner | Phase 31-33 | Autonomous tool execution, audit logging |
| Module-level ticket functions | TicketOpsDB context manager | Phase 33 | Auto-schema initialization, proper resource management |
| Run demos manually | Integration tests verify demos | Phase 34 | Automated validation, regression detection |

**Deprecated/outdated:**
- Manual test scripts in scripts/: Should be converted to proper pytest tests for CI integration
- Old agent_v2 imports: Use agent_lab (v3.0) instead

## Open Questions

Things that couldn't be fully resolved:

1. **CI Environment ANTHROPIC_API_KEY**
   - What we know: Tests require real Claude API calls via agent_lab
   - What's unclear: How to handle API costs in CI, whether to mock or use test budget
   - Recommendation: Start with manual testing, add CI when budget/mocking strategy decided

2. **Docker Cluster State Management**
   - What we know: Tests need TiKV/ratelimiter clusters running
   - What's unclear: Should tests start/stop clusters or require them running?
   - Recommendation: Require clusters running (like existing scripts), document in test docstrings

3. **Test Execution Time**
   - What we know: Full demo flows take 10-20 seconds (chaos injection + agent processing)
   - What's unclear: Acceptable test suite runtime for CI
   - Recommendation: Mark as integration tests, use pytest markers for selective execution

## Sources

### Primary (HIGH confidence)
- Codebase files: demo/tui_integration.py, demo/tikv.py, demo/ratelimiter.py (verified architecture)
- Codebase files: packages/operator-core/src/operator_core/agent_lab/loop.py (v3.0 agent implementation)
- Codebase files: packages/operator-core/src/operator_core/tui/subprocess.py (subprocess management patterns)
- Codebase files: scripts/test-demo-flow.py, scripts/test-tui-demo.py (existing test patterns)
- Codebase file: pyproject.toml (pytest configuration, dependencies)
- Codebase file: .planning/REQUIREMENTS.md (requirements tracking)

### Secondary (MEDIUM confidence)
- [pytest-asyncio documentation](https://pypi.org/project/pytest-asyncio/) - Official asyncio plugin docs
- [async test patterns for Pytest](https://tonybaloney.github.io/posts/async-test-patterns-for-pytest-and-unittest.html) - Community best practices
- [pytest-subprocess documentation](https://pytest-subprocess.readthedocs.io/) - Subprocess mocking patterns
- [End-to-End Python Integration Testing Guide](https://www.testmu.ai/learning-hub/python-integration-testing/) - Integration test patterns

### Tertiary (LOW confidence)
None - all findings verified with primary codebase sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pytest-asyncio already configured in pyproject.toml
- Architecture: HIGH - demo infrastructure exists and is well-structured
- Pitfalls: HIGH - identified from existing code patterns and async pitfalls

**Research date:** 2026-01-28
**Valid until:** 60 days - pytest-asyncio is stable, demo architecture won't change

## Requirements Mapping

| Requirement | Research Findings |
|-------------|-------------------|
| DEMO-04 | TiKV demo flow exists, needs integration test to verify end-to-end |
| DEMO-05 | Rate limiter demo flow exists, needs integration test to verify end-to-end |
| DEMO-06 | SubprocessManager captures output, needs test to verify agent panel display |
| TEST-01 | pytest pattern identified for TiKV integration test |
| TEST-02 | pytest pattern identified for ratelimiter integration test |

**Key Finding:** All demo infrastructure is complete. Phase 34 is purely about validation and testing, not building new features.
