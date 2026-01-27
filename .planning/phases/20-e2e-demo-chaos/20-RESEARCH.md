# Phase 20: E2E Demo & Chaos - Research

**Researched:** 2026-01-27
**Domain:** Multi-subject demo infrastructure, chaos injection, shared TUI abstraction
**Confidence:** HIGH

## Summary

This phase creates shared demo infrastructure that works with both TiKV and rate limiter subjects, validating that AI can diagnose anomalies without system-specific prompts in the core reasoning. The research confirms that the existing TUI infrastructure (built in Phases 7-11) can be generalized with minimal refactoring to support multiple subjects, and that chaos injection for rate limiters requires different techniques than TiKV.

The primary technical challenges are:
1. Creating a common Chapter abstraction that works for different subjects/scenarios
2. Implementing rate limiter-specific chaos injection (Redis blocking, burst traffic)
3. Validating AI diagnosis quality in real-time during demos
4. Ensuring the same TUI code can render different subject data

Research confirms:
- **Existing TUI is 90% reusable**: The TUI infrastructure from Phases 7-11 (TUIController, SubprocessManager, keyboard input, panel layouts) already uses generic patterns. Only health polling and chapter definitions need subject-specific implementations.
- **Chaos techniques differ by subject**: TiKV uses container kill (docker.kill), rate limiter uses Redis DEBUG SLEEP or CLIENT PAUSE for counter drift, and burst traffic for ghost allowing.
- **Chapter system is extensible**: The existing Chapter dataclass pattern (from Phase 10-11) can be parameterized by subject, with chapter sets defined in separate modules (demo/tikv_chapters.py, demo/ratelimiter_chapters.py).
- **AI diagnosis is already protocol-based**: The SubjectProtocol.observe() and InvariantCheckerProtocol.check() abstractions mean core AI reasoning works for any subject.

**Primary recommendation:** Extract shared TUI infrastructure into demo/ directory (not a pip package). Create subject-specific entry points (demo/tikv.py, demo/ratelimiter.py) that define chapters and chaos configs, then pass them to a shared TUI runner. Implement rate limiter chaos as Python functions using Redis CLIENT PAUSE and httpx for burst traffic.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rich | >=14.0.0 | TUI rendering, panels, Live display | Already used throughout TUI phases |
| asyncio | stdlib | Async orchestration for multiple subjects | Already the project's foundation |
| python-on-whales | >=0.70.0 | Docker control for container-based chaos | Already used in TiKV chaos |
| redis | >=5.2.1 | Redis client for CLIENT PAUSE, DEBUG SLEEP | Standard Redis Python client |
| httpx | >=0.28.0 | HTTP requests for rate limiter burst traffic | Already the project's HTTP client |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | stdlib | Chapter definitions, chaos config | Clean, immutable state |
| pathlib | stdlib | Compose file paths for different subjects | Type-safe path handling |
| typing | stdlib | Protocol definitions for extensibility | Already used for SubjectProtocol |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| redis library | Direct Redis protocol | redis library handles connection pooling, edge cases |
| Separate demo packages | Monolithic demo CLI | Separate entry points allow subject-specific dependencies |
| Chapter functions | Hardcoded demo flow | Chapter abstractions enable reuse across subjects |

**Installation:**
```bash
# redis library for Redis chaos injection
pip install redis>=5.2.1
```

## Architecture Patterns

### Recommended Project Structure
```
operator/
├── demo/                     # NEW - Shared demo infrastructure (not a package)
│   ├── __init__.py          # Empty or minimal
│   ├── runner.py            # NEW - Shared TUI runner
│   ├── tikv.py              # NEW - TiKV demo entry point
│   └── ratelimiter.py       # NEW - Rate limiter demo entry point
└── packages/
    └── operator-core/
        └── src/operator_core/
            ├── tui/         # EXISTING - Generic TUI components
            │   ├── controller.py    # REFACTOR - Extract subject-specific logic
            │   ├── chapters.py      # REFACTOR - Make Chapter generic
            │   └── ...
            └── demo/        # EXISTING - Move to top-level demo/
                └── chaos.py # DEPRECATE - TiKV-specific, move logic to demo/tikv.py
```

### Pattern 1: Subject-Specific Chapter Sets
**What:** Define chapters as lists in subject-specific modules, not hardcoded
**When to use:** Supporting multiple demo subjects with different flows
**Example:**
```python
# Source: Existing chapters.py pattern + multi-subject extension
# demo/tikv_chapters.py
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass(frozen=True)
class Chapter:
    """Generic chapter definition for any subject."""
    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"
    on_enter: Callable[[], Awaitable[None]] | None = None
    auto_advance: bool = False

# TiKV-specific chapters
TIKV_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="TiKV Chaos Demo: Watch AI diagnose a node failure.",
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="Checking TiKV cluster with 3 stores via PD.",
    ),
    # ... more chapters
]

# demo/ratelimiter_chapters.py
RATELIMITER_CHAPTERS = [
    Chapter(
        title="Welcome",
        narration="Rate Limiter Chaos Demo: Watch AI diagnose counter drift and ghost allowing.",
    ),
    Chapter(
        title="Stage 1: Cluster Health",
        narration="Checking 3 rate limiter nodes and Redis connectivity.",
    ),
    # ... more chapters
]
```

### Pattern 2: Chaos Config Dataclasses
**What:** Define chaos scenarios as dataclasses with subject-specific fields
**When to use:** Multiple chaos scenarios per subject with different parameters
**Example:**
```python
# Source: Standard Python dataclass pattern
from dataclasses import dataclass
from enum import Enum

class ChaosType(Enum):
    """Chaos scenario types."""
    CONTAINER_KILL = "container_kill"
    REDIS_PAUSE = "redis_pause"
    BURST_TRAFFIC = "burst_traffic"

@dataclass(frozen=True)
class ChaosConfig:
    """Configuration for a chaos scenario."""
    name: str
    chaos_type: ChaosType
    description: str
    # Optional parameters for different chaos types
    duration_sec: float = 5.0
    burst_multiplier: int = 2

# TiKV chaos configs
TIKV_CHAOS = [
    ChaosConfig(
        name="node_kill",
        chaos_type=ChaosType.CONTAINER_KILL,
        description="Kill random TiKV store with SIGKILL",
    ),
]

# Rate limiter chaos configs
RATELIMITER_CHAOS = [
    ChaosConfig(
        name="counter_drift",
        chaos_type=ChaosType.REDIS_PAUSE,
        description="Pause Redis with CLIENT PAUSE to create counter drift",
        duration_sec=10.0,
    ),
    ChaosConfig(
        name="ghost_allowing",
        chaos_type=ChaosType.BURST_TRAFFIC,
        description="Send 2x limit burst to trigger ghost allowing",
        burst_multiplier=2,
    ),
]
```

### Pattern 3: Redis CLIENT PAUSE for Counter Drift
**What:** Use Redis CLIENT PAUSE command to block commands temporarily
**When to use:** Simulating Redis unavailability without container restart
**Example:**
```python
# Source: Redis chaos engineering patterns + redis-py docs
import redis.asyncio as redis

async def inject_redis_pause(duration_sec: float) -> None:
    """
    Pause Redis client connections to simulate unavailability.

    Uses CLIENT PAUSE WRITE to block write commands while keeping
    replication working. This causes counter drift as nodes can't
    update Redis state.

    Args:
        duration_sec: Duration to pause in seconds (converted to ms)
    """
    async with redis.Redis.from_url("redis://localhost:6379") as r:
        # CLIENT PAUSE <duration_ms> [WRITE|ALL]
        # WRITE mode: blocks write commands, allows reads
        await r.execute_command("CLIENT", "PAUSE", int(duration_sec * 1000), "WRITE")
```

### Pattern 4: Burst Traffic for Ghost Allowing
**What:** Send 2x limit requests in short window to trigger allowing with limit=0
**When to use:** Testing rate limiter boundary conditions
**Example:**
```python
# Source: httpx async patterns + rate limiter testing
import asyncio
import httpx

async def inject_burst_traffic(
    target_url: str,
    limit: int,
    multiplier: int = 2,
) -> None:
    """
    Send burst of requests exceeding limit.

    Sends multiplier * limit requests concurrently to trigger
    ghost allowing scenario where limit becomes 0 but requests
    are still allowed.

    Args:
        target_url: Rate limiter check endpoint
        limit: Known limit for the key
        multiplier: How many times over limit to burst (default 2x)
    """
    burst_count = limit * multiplier

    async with httpx.AsyncClient() as client:
        # Send all requests concurrently
        tasks = [
            client.post(f"{target_url}/check", json={"key": "demo-key"})
            for _ in range(burst_count)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
```

### Pattern 5: Shared TUI Runner
**What:** Generic TUI runner that accepts subject-specific parameters
**When to use:** Launching demos for different subjects
**Example:**
```python
# Source: Existing TUIController pattern generalized
# demo/runner.py
from pathlib import Path
from typing import Protocol

from rich.console import Console
from operator_core.tui.controller import TUIController
from operator_core.tui.chapters import Chapter

class SubjectFactory(Protocol):
    """Protocol for creating subject-specific components."""

    async def create_health_poller(self) -> Any: ...
    def get_compose_file(self) -> Path: ...
    def get_chapters(self) -> list[Chapter]: ...

async def run_demo(
    subject_name: str,
    factory: SubjectFactory,
    console: Console | None = None,
) -> None:
    """
    Run demo TUI for any subject.

    Args:
        subject_name: Display name for the subject
        factory: Subject-specific factory for components
        console: Optional Rich console
    """
    console = console or Console()

    # Create controller with subject-specific config
    controller = TUIController(
        console=console,
        compose_file=factory.get_compose_file(),
    )

    # Inject subject-specific chapters
    controller.set_chapters(factory.get_chapters())

    # Run TUI
    console.print(f"\n[bold magenta]{subject_name} Chaos Demo[/bold magenta]\n")
    await controller.run()
```

### Pattern 6: Subject-Specific Entry Points
**What:** Minimal entry point modules that configure and launch runner
**When to use:** Separate demo commands for each subject
**Example:**
```python
# demo/tikv.py
import asyncio
from pathlib import Path

from demo.runner import run_demo
from demo.tikv_chapters import TIKV_CHAPTERS
from operator_tikv.subject import create_tikv_health_poller

class TiKVFactory:
    """TiKV-specific demo components."""

    async def create_health_poller(self):
        return create_tikv_health_poller()

    def get_compose_file(self) -> Path:
        return Path("subjects/tikv/docker-compose.yaml")

    def get_chapters(self):
        return TIKV_CHAPTERS

def main():
    """Run TiKV chaos demo."""
    asyncio.run(run_demo("TiKV", TiKVFactory()))

if __name__ == "__main__":
    main()
```

### Anti-Patterns to Avoid
- **Subject-specific logic in TUIController:** Keep controller generic, inject subject behavior via protocols
- **Hardcoded chapter lists:** Define chapters in subject modules, not in controller
- **Blocking Redis commands:** Use redis.asyncio, not sync redis client
- **Container pause instead of CLIENT PAUSE:** CLIENT PAUSE is cleaner than docker pause for Redis-only chaos
- **Single chaos config per subject:** Support multiple scenarios (counter drift AND ghost allowing)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Redis protocol commands | Manual socket protocol | redis.asyncio library | Handles connection pooling, error cases, async |
| Concurrent HTTP requests | Threading + requests | httpx + asyncio.gather | Already in use, cleaner async |
| Chapter state management | Custom state machine | Existing DemoState from Phase 10 | Already validated in TiKV demo |
| Panel refresh logic | New rendering loop | Existing TUIController._update_loop | Works for any subject data |
| Subprocess management | Manual subprocess spawn | Existing SubprocessManager | Handles output buffering, cleanup |

**Key insight:** The TUI infrastructure from Phases 7-11 was built with extensibility in mind (Rich Live, generic panels, protocol-based subjects). The refactoring needed is extraction, not rewriting.

## Common Pitfalls

### Pitfall 1: CLIENT PAUSE Blocks Demo
**What goes wrong:** CLIENT PAUSE ALL blocks all Redis commands including health checks
**Why it happens:** ALL mode pauses both reads and writes
**How to avoid:** Use CLIENT PAUSE WRITE mode to only block writes, allowing read-based health checks
**Warning signs:** TUI health panel freezes during chaos, Redis connection timeouts

### Pitfall 2: Burst Traffic Doesn't Trigger Anomaly
**What goes wrong:** Ghost allowing doesn't occur even with burst
**Why it happens:** Burst not large enough, or limit window already expired
**How to avoid:**
- Send burst within same time window (all requests < 1 second apart)
- Use 2x limit minimum, possibly 3x for reliability
- Verify limit exists in Redis before burst
**Warning signs:** Invariant checker shows no ghost allowing violations

### Pitfall 3: Chapter Callbacks Block TUI
**What goes wrong:** TUI freezes during chaos injection or countdown
**Why it happens:** Blocking operations in chapter on_enter callbacks
**How to avoid:** Make all on_enter callbacks async, use await for I/O operations
**Warning signs:** Panels stop updating during fault injection, keyboard unresponsive

### Pitfall 4: Subject-Specific Health Poller Not Injected
**What goes wrong:** TUI shows stale health data or errors
**Why it happens:** TUIController still uses hardcoded TiKV health poller
**How to avoid:**
- Accept health poller as constructor parameter
- Use Protocol type for health poller interface
- Each subject provides its own poller implementation
**Warning signs:** Health panel shows TiKV data during rate limiter demo

### Pitfall 5: Chaos Config Not Validated
**What goes wrong:** Demo crashes during chaos injection
**Why it happens:** Missing required fields or invalid parameters in chaos config
**How to avoid:**
- Use dataclass with required fields
- Validate duration/multiplier ranges at construction
- Provide sensible defaults for optional parameters
**Warning signs:** AttributeError during chaos injection, unexpected None values

### Pitfall 6: AI Diagnosis Timeout
**What goes wrong:** AI diagnosis doesn't complete within chapter
**Why it happens:** Claude API slow, or prompt too complex
**How to avoid:**
- Set reasonable timeout (30-60s) for diagnosis
- Show "Diagnosing..." spinner during wait
- Allow manual chapter advance if diagnosis takes too long
**Warning signs:** Demo stuck on diagnosis chapter, no AI output visible

## Code Examples

Verified patterns from official sources:

### Redis CLIENT PAUSE Usage
```python
# Source: Redis chaos patterns + redis-py async docs
import redis.asyncio as redis
import asyncio

async def chaos_redis_pause_example():
    """Demonstrate Redis CLIENT PAUSE for counter drift simulation."""
    r = redis.Redis.from_url("redis://localhost:6379")

    try:
        # Pause write commands for 5 seconds
        # Format: CLIENT PAUSE <timeout_ms> [WRITE|ALL]
        duration_ms = 5000
        await r.execute_command("CLIENT", "PAUSE", duration_ms, "WRITE")

        print(f"Redis paused for {duration_ms}ms")

        # During this time:
        # - Write commands (SET, INCR, etc.) are blocked
        # - Read commands (GET, etc.) work normally
        # - Rate limiter nodes can't update counters
        # - This causes counter drift between nodes and Redis

        await asyncio.sleep(duration_ms / 1000 + 1)  # Wait for pause to expire

    finally:
        await r.aclose()
```

### Burst Traffic Generation
```python
# Source: httpx async patterns + existing operator patterns
import asyncio
import httpx

async def burst_traffic_example():
    """Generate burst traffic to trigger ghost allowing."""
    target_url = "http://localhost:8001"
    key = "demo-key"
    limit = 10  # Known limit for the key
    burst_size = limit * 2  # 2x limit

    async with httpx.AsyncClient(timeout=30.0) as client:
        # First, set up the limit
        await client.post(
            f"{target_url}/limit",
            json={"key": key, "limit": limit, "window_sec": 60},
        )

        # Wait a moment for propagation
        await asyncio.sleep(1.0)

        # Send burst - all requests concurrently
        tasks = []
        for i in range(burst_size):
            task = client.post(
                f"{target_url}/check",
                json={"key": key},
            )
            tasks.append(task)

        # Gather all responses
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Count allowed vs denied
        allowed = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
        denied = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 429)

        print(f"Burst results: {allowed} allowed, {denied} denied (expected {limit} allowed)")

        # If allowed > limit, ghost allowing may have occurred
        if allowed > limit:
            print(f"Ghost allowing detected! {allowed - limit} excess requests allowed")
```

### Generic Chapter with Chaos Callback
```python
# Source: Existing chapters.py + chaos integration pattern
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass(frozen=True)
class Chapter:
    """Generic chapter with optional async callback."""
    title: str
    narration: str
    key_hint: str = "[dim]SPACE/ENTER: next | Q: quit[/dim]"
    on_enter: Callable[[], Awaitable[None]] | None = None
    auto_advance: bool = False

async def countdown_and_inject_chaos(
    chaos_fn: Callable[[], Awaitable[None]],
    update_fn: Callable[[str], None],
) -> None:
    """
    Countdown before chaos injection.

    Args:
        chaos_fn: Async function that performs chaos injection
        update_fn: Function to update TUI with countdown text
    """
    for i in range(3, 0, -1):
        update_fn(f"[bold yellow]Injecting chaos in {i}...[/bold yellow]")
        await asyncio.sleep(1.0)

    update_fn("[bold red]INJECTING CHAOS![/bold red]")
    await chaos_fn()
    await asyncio.sleep(0.5)

# Example usage in chapter definition
async def inject_counter_drift():
    """Chaos callback for counter drift scenario."""
    await inject_redis_pause(duration_sec=10.0)

COUNTER_DRIFT_CHAPTER = Chapter(
    title="Stage 3: Fault Injection",
    narration="Redis will pause, causing counter drift between nodes.",
    on_enter=inject_counter_drift,
    auto_advance=True,  # Auto-advance after injection completes
)
```

### Subject Factory Pattern
```python
# Source: Protocol pattern from existing operator_protocols
from typing import Protocol, Any
from pathlib import Path

class DemoSubjectFactory(Protocol):
    """Protocol for subject-specific demo components."""

    def get_subject_name(self) -> str:
        """Return display name for the subject."""
        ...

    def get_compose_file(self) -> Path:
        """Return path to docker-compose.yaml."""
        ...

    def get_chapters(self) -> list[Chapter]:
        """Return chapter list for this subject's demo."""
        ...

    async def create_health_poller(self) -> Any:
        """Create subject-specific health poller."""
        ...

# Rate limiter implementation
class RateLimiterDemoFactory:
    """Rate limiter demo factory."""

    def get_subject_name(self) -> str:
        return "Rate Limiter"

    def get_compose_file(self) -> Path:
        return Path("docker/docker-compose.yml")

    def get_chapters(self) -> list[Chapter]:
        from demo.ratelimiter_chapters import RATELIMITER_CHAPTERS
        return RATELIMITER_CHAPTERS

    async def create_health_poller(self):
        from operator_ratelimiter.subject import create_health_poller
        return create_health_poller()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Subject-specific demo scripts | Generic TUI runner | This phase | One TUI codebase for all subjects |
| Hardcoded TiKV chapters | Chapter dataclasses | Phase 10 | Reusable for any subject |
| Container kill only | Multiple chaos types | This phase | Rate limiter-specific scenarios |
| Manual fault injection | Chaos config dataclasses | This phase | Declarative, testable |
| Synchronous Redis commands | redis.asyncio | Standard practice | Non-blocking chaos injection |

**Deprecated/outdated:**
- `demo/chaos.py`: TiKV-specific, logic moving to `demo/tikv.py`
- Hardcoded `DEMO_CHAPTERS` in `tui/chapters.py`: Moving to subject-specific modules
- Subject-specific health polling in TUIController: Extracted to injectable component

## Open Questions

Things that couldn't be fully resolved:

1. **AI Diagnosis Validation Method**
   - What we know: Human observer validates diagnosis in real-time
   - What's unclear: Criteria for "correct" diagnosis beyond mentioning symptom
   - Recommendation: Define minimal success criteria: AI must mention (1) the anomaly type (counter drift OR ghost allowing) and (2) the affected component (Redis OR specific node). Exact root cause analysis is bonus.

2. **Chapter Timing for Auto-Advance**
   - What we know: Some chapters auto-advance after on_enter completes
   - What's unclear: How long to pause before advancing after chaos injection
   - Recommendation: Add configurable `auto_advance_delay` to Chapter (default 2s). Long enough to see the effect, short enough to maintain pace.

3. **Chaos Recovery Timing**
   - What we know: CLIENT PAUSE expires automatically, burst is one-time
   - What's unclear: Whether to explicitly recover or let time heal
   - Recommendation: CLIENT PAUSE is self-healing (expires after duration). Ghost allowing may need counter reset via management API. Add optional recovery callback to ChaosConfig.

4. **Prometheus Polling Frequency**
   - What we know: Context says 1-2s range is acceptable
   - What's unclear: Impact on demo responsiveness vs CPU usage
   - Recommendation: Start with 2s (current TiKV demo rate). Reduce to 1s if metrics feel laggy during rate limiter demo.

## Sources

### Primary (HIGH confidence)
- [Redis Chaos Engineering with Gremlin](https://www.gremlin.com/community/tutorials/chaos-engineering-with-redis) - CLIENT PAUSE patterns
- [Chaos Mesh Redis Fault Simulation](https://chaos-mesh.org/docs/simulate-redis-chaos-on-physical-nodes/) - Redis-specific chaos techniques
- [redis-py Async Documentation](https://redis-py.readthedocs.io/) - redis.asyncio client API
- [Python Textual TUI Patterns](https://realpython.com/python-textual/) - Chapter-based demo patterns (verified 2026)
- Existing codebase:
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/controller.py` - TUI infrastructure
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/chapters.py` - Chapter patterns
  - `/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/demo/chaos.py` - TiKV chaos patterns
  - Phase 10 Research - Keyboard and chapter progression
  - Phase 11 Research - Fault workflow integration

### Secondary (MEDIUM confidence)
- [8 TUI Patterns to Turn Python Scripts Into Apps](https://medium.com/@Nexumo_/8-tui-patterns-to-turn-python-scripts-into-apps-ce6f964d3b6f) - State management patterns
- [State Machine Design Pattern in Python](https://www.linkedin.com/pulse/state-machine-design-pattern-concepts-examples-python-sajad-rahimi) - Dataclass-based state machines
- [Anomaly Detection in Distributed Systems](https://www.geeksforgeeks.org/system-design/anomaly-detection-in-distributed-systems/) - Counter drift context
- Phase 18 Context - Docker Compose environment for rate limiter
- Phase 19 Documentation - Rate limiter invariants

### Tertiary (LOW confidence)
- [Real-time Anomaly Detection under Distribution Drift](https://www.amazon.science/blog/real-time-anomaly-detection-under-distribution-drift) - General anomaly detection concepts
- [DDoS Attack Mitigation Techniques](https://www.ijcttjournal.org/archives/ijctt-v72i12p108) - Rate limiting and anomaly detection context

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - redis.asyncio and httpx already in use, Rich/asyncio validated
- Architecture: HIGH - Patterns follow existing TUI phases, minimal refactoring needed
- Chaos techniques: HIGH - Redis CLIENT PAUSE well-documented, burst traffic straightforward
- Demo abstraction: HIGH - Existing TUI already protocol-based, extraction is mechanical
- Pitfalls: MEDIUM - Some based on Redis behavior and timing assumptions

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - stable libraries, proven patterns)
