# Phase 9: Cluster Health Display - Research

**Researched:** 2026-01-25
**Domain:** TUI health indicators, PD API health polling, Rich text styling for visual feedback
**Confidence:** HIGH

## Summary

This phase implements the cluster health display panel with color-coded health indicators for all 6 cluster nodes (3 TiKV stores, 3 PD members) and detection highlighting when the monitor detects issues. The research confirms that:

1. **PD API provides all health data needed**: `/pd/api/v1/stores` returns TiKV store health (state_name: "Up"/"Down"/"Offline"/"Tombstone"), and `/pd/api/v1/health` returns PD member health (health: boolean).

2. **Rich markup provides all styling needed**: Green/red text colors via `[green]text[/green]` and `[red]text[/red]`, plus border_style parameter on Panel for visual emphasis. Unicode symbols (bullet: `\u25cf`, cross: `\u2717`) work in Rich text.

3. **Integration architecture is clear**: The TUIController already has `_refresh_panels()` called every 250ms. Add a ClusterHealthPoller that fetches health data independently and exposes it for the cluster panel to render.

**Primary recommendation:** Create a ClusterHealthPoller class that polls PD API endpoints at configurable intervals, maintains health state, and provides formatted Rich markup for the cluster panel. Use border color change (cyan to red/yellow) for detection highlighting when monitor detects issues.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rich | >=14.0.0 | Text markup for color-coded indicators, Panel styling | Already in use, supports markup syntax |
| httpx | >=0.27.0 | Async HTTP client for PD API | Already in use for PDClient |
| asyncio | stdlib (3.11+) | Async polling, Event coordination | Already in use throughout TUI |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| collections.deque | stdlib | Optional: Detection event history buffer | If tracking recent detections for flash effect |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PD API polling | Prometheus metrics | PD API is simpler, direct, lower latency for health status |
| Text color for status | Emoji icons | Unicode symbols work everywhere, emoji support varies by terminal |
| Border color for highlighting | Blink text | Blink is annoying and has terminal compatibility issues |

**Installation:**
No new dependencies needed. All required functionality is already available (Rich, httpx, asyncio).

## Architecture Patterns

### Recommended Module Structure
```
operator_core/
└── tui/
    ├── __init__.py
    ├── layout.py         # Existing - Layout factory, make_panel
    ├── buffer.py         # Existing - OutputBuffer class
    ├── controller.py     # Modified - Add health polling integration
    ├── subprocess.py     # Existing - SubprocessManager
    └── health.py         # NEW - ClusterHealthPoller and formatting
```

### Pattern 1: Cluster Health Data Model
**What:** Define data structures for health state that can be rendered
**When to use:** Separating data fetching from rendering
**Example:**
```python
# Source: Synthesized from existing types + requirements
from dataclasses import dataclass
from enum import Enum

class NodeHealth(Enum):
    UP = "up"
    DOWN = "down"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

@dataclass
class NodeStatus:
    """Health status for a single cluster node."""
    node_id: str
    name: str  # Display name (e.g., "tikv-1", "pd-1")
    node_type: str  # "tikv" or "pd"
    health: NodeHealth
    address: str  # e.g., "tikv-1:20160"

@dataclass
class ClusterHealth:
    """Complete cluster health snapshot."""
    nodes: list[NodeStatus]
    has_issues: bool  # Any node not UP
    last_updated: datetime
```

### Pattern 2: PD API Health Fetching
**What:** Fetch health from both /stores and /health endpoints
**When to use:** Getting complete cluster health picture
**Example:**
```python
# Source: https://tikv.org/docs/6.5/deploy/monitor/api/ + PingCAP PD API docs
async def fetch_cluster_health(pd_client: httpx.AsyncClient) -> ClusterHealth:
    """Fetch health status from PD API."""
    nodes: list[NodeStatus] = []

    # 1. Get TiKV store health
    # GET /pd/api/v1/stores -> {"stores": [{"store": {"state_name": "Up"}}]}
    stores_resp = await pd_client.get("/pd/api/v1/stores")
    stores_resp.raise_for_status()
    stores_data = stores_resp.json()

    for item in stores_data.get("stores", []):
        store = item.get("store", {})
        state = store.get("state_name", "Unknown")
        nodes.append(NodeStatus(
            node_id=str(store.get("id")),
            name=f"tikv-{store.get('id')}",
            node_type="tikv",
            health=_parse_tikv_state(state),  # Up->UP, Down->DOWN, etc.
            address=store.get("address", ""),
        ))

    # 2. Get PD member health
    # GET /pd/api/v1/health -> [{"name": "pd-1", "health": true}]
    health_resp = await pd_client.get("/pd/api/v1/health")
    health_resp.raise_for_status()
    health_data = health_resp.json()

    for member in health_data:
        nodes.append(NodeStatus(
            node_id=str(member.get("member_id")),
            name=member.get("name", "pd-?"),
            node_type="pd",
            health=NodeHealth.UP if member.get("health") else NodeHealth.DOWN,
            address=",".join(member.get("client_urls", [])),
        ))

    return ClusterHealth(
        nodes=nodes,
        has_issues=any(n.health != NodeHealth.UP for n in nodes),
        last_updated=datetime.now(),
    )
```

### Pattern 3: Rich Markup for Health Indicators
**What:** Format health status with color-coded symbols
**When to use:** Rendering cluster health in TUI panel
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/markup.html
def format_node_status(node: NodeStatus) -> str:
    """Format single node status line with color-coded indicator."""
    # Unicode symbols that render well in terminals
    UP_SYMBOL = "\u25cf"     # ● (filled circle)
    DOWN_SYMBOL = "\u2717"   # ✗ (cross mark)

    if node.health == NodeHealth.UP:
        indicator = f"[green]{UP_SYMBOL}[/green]"
        status = "[green]Up[/green]"
    elif node.health == NodeHealth.DOWN:
        indicator = f"[red]{DOWN_SYMBOL}[/red]"
        status = "[bold red]Down[/bold red]"
    elif node.health == NodeHealth.OFFLINE:
        indicator = f"[yellow]{DOWN_SYMBOL}[/yellow]"
        status = "[yellow]Offline[/yellow]"
    else:
        indicator = "[dim]?[/dim]"
        status = "[dim]Unknown[/dim]"

    return f"{indicator} {node.name}: {status}"

def format_cluster_panel(health: ClusterHealth) -> str:
    """Format complete cluster health panel content."""
    lines = ["[bold]Cluster Status[/bold]", ""]

    # Group by type
    tikv_nodes = [n for n in health.nodes if n.node_type == "tikv"]
    pd_nodes = [n for n in health.nodes if n.node_type == "pd"]

    lines.append("[dim]TiKV Stores:[/dim]")
    for node in tikv_nodes:
        lines.append(f"  {format_node_status(node)}")

    lines.append("")
    lines.append("[dim]PD Members:[/dim]")
    for node in pd_nodes:
        lines.append(f"  {format_node_status(node)}")

    return "\n".join(lines)
```

### Pattern 4: Detection Highlighting via Border Color
**What:** Change panel border color when issues detected
**When to use:** Visual emphasis for TUI-04 requirement
**Example:**
```python
# Source: https://rich.readthedocs.io/en/stable/reference/panel.html
from rich.panel import Panel

def make_cluster_panel(health: ClusterHealth, detection_active: bool = False) -> Panel:
    """Create cluster panel with detection highlighting."""
    content = format_cluster_panel(health)

    # Border color reflects state
    if detection_active:
        # Monitor detected an issue - emphasize with red border
        border_style = "bold red"
        title = "[bold red]! Cluster Status ![/bold red]"
    elif health.has_issues:
        # Cluster has issues but no active detection
        border_style = "yellow"
        title = "[bold yellow]Cluster Status[/bold yellow]"
    else:
        # All healthy
        border_style = "cyan"
        title = "[bold cyan]Cluster Status[/bold cyan]"

    return Panel(
        content,
        title=title,
        border_style=border_style,
        padding=(0, 1),
    )
```

### Pattern 5: Async Health Polling with Event Coordination
**What:** Poll health independently, coordinate with TUI refresh
**When to use:** Background health fetching without blocking TUI
**Example:**
```python
# Source: Adapted from SubprocessManager pattern
class ClusterHealthPoller:
    """Polls PD API for cluster health status."""

    def __init__(
        self,
        pd_endpoint: str = "http://localhost:2379",
        poll_interval: float = 2.0,
    ) -> None:
        self._pd_endpoint = pd_endpoint
        self._poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._health: ClusterHealth | None = None
        self._detection_active = False  # Set when monitor reports issue

    async def run(self) -> None:
        """Poll loop that runs until shutdown."""
        async with httpx.AsyncClient(
            base_url=self._pd_endpoint,
            timeout=5.0,
        ) as client:
            while not self._shutdown.is_set():
                try:
                    self._health = await fetch_cluster_health(client)
                except Exception as e:
                    # Mark all as unknown on fetch failure
                    pass  # Log but don't crash

                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self._poll_interval,
                    )
                except asyncio.TimeoutError:
                    continue

    def get_health(self) -> ClusterHealth | None:
        """Get latest health snapshot (thread-safe read)."""
        return self._health

    def set_detection_active(self, active: bool) -> None:
        """Set detection highlighting state (called from monitor output parsing)."""
        self._detection_active = active

    def is_detection_active(self) -> bool:
        return self._detection_active

    def stop(self) -> None:
        self._shutdown.set()
```

### Pattern 6: Monitor Output Parsing for Detection Events
**What:** Parse monitor subprocess output to detect violations
**When to use:** Triggering detection highlighting from monitor output
**Example:**
```python
# Source: Existing MonitorLoop output patterns
def parse_monitor_output_for_detection(line: str) -> bool | None:
    """
    Check if monitor output indicates a detection event.

    Returns:
        True if violation detected
        False if all passing
        None if line doesn't contain status info
    """
    # MonitorLoop outputs: "Check complete: 3 invariants, all passing"
    # Or: "Check complete: 3 invariants, 1 violations"
    if "Check complete:" in line:
        if "all passing" in line:
            return False
        if "violations" in line:
            return True
    return None
```

### Anti-Patterns to Avoid
- **Polling too fast:** PD API calls add latency. 2-second interval is sufficient for health display
- **Blocking TUI refresh on API call:** Health polling must be async and independent
- **Using blink effect:** Terminal compatibility issues, distracting for users
- **Hardcoding node count:** Demo has 6 nodes, but code should handle dynamic counts
- **Not handling API failures:** PD might be down; show "Unknown" state, don't crash

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Color-coded text | ANSI escape sequences | Rich markup `[green]...[/green]` | Rich handles terminal compatibility |
| Health data structure | Raw dicts | Dataclasses | Type safety, IDE support |
| Async HTTP client | requests + threading | httpx.AsyncClient | Already in use, async-native |
| Status symbols | ASCII approximations | Unicode `\u25cf` / `\u2717` | Works in modern terminals |
| Poll interval coordination | time.sleep | asyncio.wait_for(event, timeout) | Interruptible, async-native |

**Key insight:** Rich markup handles all the terminal compatibility complexity. Just use `[color]text[/color]` syntax and let Rich figure out the ANSI codes.

## Common Pitfalls

### Pitfall 1: Health Poll Blocks TUI Refresh
**What goes wrong:** TUI freezes for 100-500ms during each health poll
**Why it happens:** Health fetch runs synchronously in refresh loop
**How to avoid:**
- Run health polling as separate asyncio task
- Store latest health snapshot in shared state
- TUI refresh reads snapshot, never waits for API
**Warning signs:** TUI becomes less responsive as health poll interval decreases

### Pitfall 2: PD API Not Available
**What goes wrong:** Cluster panel shows no data or crashes
**Why it happens:** PD server down, network issues, or wrong endpoint
**How to avoid:**
- Wrap API calls in try/except
- Show "Unknown" state on failure, not crash
- Log errors but continue polling
**Warning signs:** Exception traces in panel or stderr

### Pitfall 3: State Race Between Poller and Renderer
**What goes wrong:** Partial health data rendered, visual glitches
**Why it happens:** Health object modified while being read
**How to avoid:**
- Health object is immutable dataclass
- Poller creates new ClusterHealth each poll
- Single atomic reference assignment: `self._health = new_health`
**Warning signs:** Intermittent "NoneType has no attribute" errors

### Pitfall 4: Detection Highlighting Never Clears
**What goes wrong:** Red border stays forever after issue resolves
**Why it happens:** Detection state set on violation but never cleared
**How to avoid:**
- Parse monitor output for both "violations" and "all passing"
- Clear detection state when "all passing" seen
- Consider timeout: auto-clear after N seconds without new violation
**Warning signs:** Panel stays red even after node restored

### Pitfall 5: Wrong Unicode Symbol in Terminal
**What goes wrong:** Symbols show as boxes or question marks
**Why it happens:** Terminal font doesn't support chosen Unicode characters
**How to avoid:**
- Use widely supported symbols: `\u25cf` (●) and `\u2717` (✗)
- Test in common terminals: iTerm2, Terminal.app, Alacritty, Windows Terminal
- Have ASCII fallback: `*` for up, `X` for down
**Warning signs:** "Unknown character" boxes in output

### Pitfall 6: Too Many API Calls Under Load
**What goes wrong:** PD becomes slow, health polling times out
**Why it happens:** Health poll interval too aggressive during high-traffic demo
**How to avoid:**
- Default 2-second interval is reasonable
- Make interval configurable
- Consider exponential backoff on repeated failures
**Warning signs:** Health data becomes stale, "Unknown" states appear

## Code Examples

Verified patterns from official sources:

### Rich Markup for Colored Status (Verified)
```python
# Source: https://rich.readthedocs.io/en/stable/markup.html
from rich.console import Console

console = Console()

# Green for healthy
console.print("[green]\u25cf[/green] tikv-1: [green]Up[/green]")

# Red for down
console.print("[red]\u2717[/red] tikv-2: [bold red]Down[/bold red]")

# Yellow for offline
console.print("[yellow]\u2717[/yellow] tikv-3: [yellow]Offline[/yellow]")

# Combined with bold
console.print("[bold red]! Alert: Node down ![/bold red]")
```

### Panel Border Style (Verified)
```python
# Source: https://rich.readthedocs.io/en/stable/reference/panel.html
from rich.panel import Panel

# Normal state - cyan border
panel_normal = Panel(
    "Content here",
    title="[bold]Cluster Status[/bold]",
    border_style="cyan",
)

# Alert state - red border
panel_alert = Panel(
    "Content here",
    title="[bold red]! Cluster Status ![/bold red]",
    border_style="bold red",
)

# Warning state - yellow border
panel_warning = Panel(
    "Content here",
    title="[bold yellow]Cluster Status[/bold yellow]",
    border_style="yellow",
)
```

### PD API Endpoint Calls (Verified)
```python
# Source: https://tikv.org/docs/6.5/deploy/monitor/api/
# Source: https://docs-download.pingcap.com/api/pd-api/pd-api-v1.html
import httpx

async def get_tikv_stores(client: httpx.AsyncClient) -> list[dict]:
    """GET /pd/api/v1/stores -> TiKV store health."""
    resp = await client.get("/pd/api/v1/stores")
    resp.raise_for_status()
    data = resp.json()
    # Response: {"count": 3, "stores": [{"store": {"id": 1, "state_name": "Up"}}]}
    return data.get("stores", [])

async def get_pd_health(client: httpx.AsyncClient) -> list[dict]:
    """GET /pd/api/v1/health -> PD member health."""
    resp = await client.get("/pd/api/v1/health")
    resp.raise_for_status()
    data = resp.json()
    # Response: [{"name": "pd-1", "member_id": 123, "health": true}]
    return data
```

### TUIController Integration Point
```python
# Source: Existing TUIController._refresh_panels pattern
def _refresh_panels(self) -> None:
    """Update panel contents from subprocess output buffers."""
    if self._subprocess_mgr is None:
        return

    # Existing: Update monitor panel
    monitor_buf = self._subprocess_mgr.get_buffer("monitor")
    if monitor_buf:
        # NEW: Check for detection events in recent monitor output
        for line in monitor_buf.get_lines(n=5):
            detection = parse_monitor_output_for_detection(line)
            if detection is not None:
                self._health_poller.set_detection_active(detection)

        self._layout["main"]["monitor"].update(
            make_panel(monitor_buf.get_text(n=20), "Monitor", "blue")
        )

    # NEW: Update cluster panel with health status
    health = self._health_poller.get_health()
    if health:
        self._layout["cluster"].update(
            make_cluster_panel(
                health,
                detection_active=self._health_poller.is_detection_active(),
            )
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ANSI escape codes manually | Rich markup `[color]text[/color]` | Rich adoption | Cross-terminal compatibility |
| Sync requests + threading | httpx.AsyncClient | httpx maturity | Simpler async code |
| Print statements for debug | Structured Panel output | TUI adoption | Professional appearance |

**Deprecated/outdated:**
- Raw ANSI codes: Use Rich markup instead
- `requests` library for async: Use httpx

## Open Questions

Things that couldn't be fully resolved:

1. **Detection highlight duration**
   - What we know: Should highlight when monitor reports violation
   - What's unclear: How long should highlight persist after all-passing?
   - Recommendation: Clear immediately when "all passing" seen. If that feels too abrupt, add 3-second delay.

2. **Health poll interval vs demo pacing**
   - What we know: 2 seconds is reasonable default
   - What's unclear: Will demo presenter want faster/slower updates?
   - Recommendation: Make configurable via CLI argument. Default 2s, allow 0.5s-10s.

3. **Fallback when PD unreachable**
   - What we know: Should show "Unknown" state
   - What's unclear: Should it keep trying or give up after N failures?
   - Recommendation: Keep trying forever but with exponential backoff (2s -> 4s -> 8s, max 30s).

4. **Node name display format**
   - What we know: "tikv-1", "pd-1" etc.
   - What's unclear: Should use actual hostname or synthetic names?
   - Recommendation: Use store/member ID to generate synthetic names for consistency.

## Sources

### Primary (HIGH confidence)
- [Rich Markup Documentation](https://rich.readthedocs.io/en/stable/markup.html) - Color syntax, style nesting
- [Rich Panel Reference](https://rich.readthedocs.io/en/stable/reference/panel.html) - border_style parameter
- [Rich Style Documentation](https://rich.readthedocs.io/en/stable/style.html) - Available attributes (bold, etc.)
- [TiKV PD API Documentation](https://tikv.org/docs/6.5/deploy/monitor/api/) - /stores endpoint, state_name values
- [PingCAP PD API Reference](https://docs-download.pingcap.com/api/pd-api/pd-api-v1.html) - /health endpoint, JSON structure
- [Existing PDClient](/Users/jrtipton/x/operator/packages/operator-tikv/src/operator_tikv/pd_client.py) - httpx usage patterns
- [Existing TUIController](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/tui/controller.py) - Integration point patterns
- [Existing MonitorLoop](/Users/jrtipton/x/operator/packages/operator-core/src/operator_core/monitor/loop.py) - Output format for detection parsing

### Secondary (MEDIUM confidence)
- [Phase 7 Research](/Users/jrtipton/x/operator/.planning/phases/07-tui-foundation/07-RESEARCH.md) - Layout patterns, make_panel
- [Phase 8 Research](/Users/jrtipton/x/operator/.planning/phases/08-subprocess-management/08-RESEARCH.md) - Async task patterns, subprocess output

### Tertiary (LOW confidence)
- None - all critical findings verified with primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components already in use (Rich, httpx, asyncio)
- Architecture: HIGH - Patterns follow existing codebase conventions
- API integration: HIGH - PD API well-documented, already using PDClient
- Visual styling: HIGH - Rich markup documented and tested
- Pitfalls: HIGH - Based on codebase patterns and API behavior

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - Rich and PD API are stable)

---

## Key Answers to Phase Questions

**Q1: How to fetch TiKV/PD node health status via PD API?**
- TiKV stores: `GET /pd/api/v1/stores` - check `store.state_name` ("Up", "Down", "Offline", "Tombstone")
- PD members: `GET /pd/api/v1/health` - check `health` boolean per member
- Use existing httpx.AsyncClient pattern from PDClient

**Q2: Rich markup for color-coded status indicators?**
- `[green]\u25cf[/green]` for green bullet (up)
- `[red]\u2717[/red]` for red cross (down)
- `[bold red]...[/bold red]` for emphasis
- Border color via `border_style="red"` on Panel

**Q3: How to integrate health polling into TUIController?**
- Create ClusterHealthPoller class with async run() method
- Add as TaskGroup task in TUIController.run()
- Call `get_health()` in `_refresh_panels()` to render cluster panel
- Store reference to poller on controller: `self._health_poller`

**Q4: How to highlight detection events?**
- Parse monitor output for "violations" vs "all passing" strings
- Set `detection_active` flag on health poller
- When rendering panel, check flag and use `border_style="bold red"` if active
- Change panel title to include "!" markers: `[bold red]! Cluster Status ![/bold red]`

**Q5: Coordination between monitor subprocess output and cluster panel updates?**
- Monitor output flows through OutputBuffer (existing)
- In `_refresh_panels()`, scan recent monitor lines for detection keywords
- Update health poller's detection state
- Health poller's state is read when rendering cluster panel
- No direct communication needed - shared state via poller object
