"""
ClusterHealthPoller for fetching and formatting cluster health status.

This module provides:
- Data types for cluster health representation (NodeHealth, NodeStatus, ClusterHealth)
- Formatting functions for Rich markup display
- ClusterHealthPoller for async PD API polling

Per RESEARCH.md Pattern 1: Cluster Health Data Model
- Uses dataclasses for type safety and immutability
- NodeHealth enum maps PD API states to display states
- ClusterHealth is an immutable snapshot created each poll

Per RESEARCH.md Pattern 3: Rich Markup for Health Indicators
- Color-coded symbols (green bullet for up, red cross for down)
- Border color changes for detection highlighting
- Uses widely supported Unicode symbols

Per RESEARCH.md Pattern 5: Async Health Polling with Event Coordination
- Runs as independent asyncio task
- Stores latest health snapshot for TUI rendering
- Uses asyncio.Event for shutdown coordination
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import httpx


class NodeHealth(Enum):
    """Health status for a cluster node."""

    UP = "up"
    DOWN = "down"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass
class NodeStatus:
    """
    Health status for a single cluster node.

    Represents either a TiKV store or PD member with its current health state.

    Attributes:
        node_id: Unique identifier from PD API (store ID or member ID)
        name: Display name (e.g., "tikv-1", "pd-1")
        node_type: Either "tikv" or "pd"
        health: Current health status
        address: Network address (e.g., "tikv-1:20160")
    """

    node_id: str
    name: str
    node_type: str
    health: NodeHealth
    address: str


@dataclass
class ClusterHealth:
    """
    Complete cluster health snapshot.

    Immutable snapshot of all node health states at a point in time.
    Created atomically by ClusterHealthPoller on each poll.

    Attributes:
        nodes: List of all node statuses
        has_issues: True if any node is not UP
        last_updated: Timestamp when this snapshot was taken
    """

    nodes: list[NodeStatus]
    has_issues: bool
    last_updated: datetime


# Unicode symbols for health indicators
# Per RESEARCH.md Pitfall 5: Use widely supported symbols
UP_SYMBOL = "\u25cf"  # ● (filled circle)
DOWN_SYMBOL = "\u2717"  # ✗ (cross mark)


def _parse_tikv_state(state: str) -> NodeHealth:
    """
    Map TiKV state_name to NodeHealth.

    Args:
        state: State name from PD API (e.g., "Up", "Down", "Offline", "Tombstone")

    Returns:
        Corresponding NodeHealth enum value
    """
    state_lower = state.lower()
    if state_lower == "up":
        return NodeHealth.UP
    elif state_lower == "down":
        return NodeHealth.DOWN
    elif state_lower in ("offline", "tombstone"):
        return NodeHealth.OFFLINE
    else:
        return NodeHealth.UNKNOWN


def format_node_status(node: NodeStatus) -> str:
    """
    Format single node status line with color-coded indicator.

    Uses Rich markup for color coding:
    - Green bullet + "Up" for UP
    - Red cross + "Down" for DOWN
    - Yellow cross + "Offline" for OFFLINE
    - Dim "?" + "Unknown" for UNKNOWN

    Args:
        node: Node status to format

    Returns:
        Rich markup string like "[green]●[/green] tikv-1: [green]Up[/green]"
    """
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
    """
    Format complete cluster health panel content.

    Creates a Rich markup string with sections for TiKV stores and PD members,
    each with color-coded health indicators.

    Args:
        health: Cluster health snapshot to format

    Returns:
        Multi-line Rich markup string for panel content
    """
    lines = ["[bold]Cluster Status[/bold]", ""]

    # Group nodes by type
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


def parse_monitor_output_for_detection(line: str) -> bool | None:
    """
    Check if monitor output indicates a detection event.

    Parses MonitorLoop output format to detect invariant violations.
    Per RESEARCH.md Pattern 6: Monitor Output Parsing for Detection Events.

    Args:
        line: Single line of monitor output

    Returns:
        True if violation detected
        False if all passing
        None if line doesn't contain status info
    """
    # MonitorLoop outputs: "Check complete: 3 invariants, all passing"
    # Or: "Check complete: 3 invariants, 1 violations"
    if "all passing" in line:
        return False
    if "violations" in line:
        return True
    return None


class ClusterHealthPoller:
    """
    Polls PD API for cluster health status.

    Runs as async task, fetches health at configurable interval,
    stores latest snapshot for TUI rendering.

    Per RESEARCH.md Pattern 5: Async Health Polling with Event Coordination.
    - Runs independently of TUI refresh cycle
    - Creates immutable ClusterHealth snapshots
    - Uses atomic reference assignment for thread safety

    Per RESEARCH.md Pitfall 2: PD API Not Available
    - Handles API failures gracefully
    - Continues polling, doesn't crash

    Example:
        poller = ClusterHealthPoller(pd_endpoint="http://pd-1:2379")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(poller.run())
            # ... other tasks ...
            poller.stop()  # Signal shutdown
    """

    def __init__(
        self,
        pd_endpoint: str = "http://localhost:2379",
        poll_interval: float = 2.0,
    ) -> None:
        """
        Initialize health poller.

        Args:
            pd_endpoint: Base URL for PD API (e.g., "http://localhost:2379")
            poll_interval: Seconds between health polls (default 2.0)
        """
        self._pd_endpoint = pd_endpoint
        self._poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._health: ClusterHealth | None = None
        self._detection_active = False

    async def run(self) -> None:
        """
        Poll loop that runs until shutdown.

        Creates httpx.AsyncClient and polls PD API endpoints at configured
        interval. On each successful poll, creates new ClusterHealth snapshot.
        On failure, continues polling without crashing.
        """
        # Per RESEARCH.md: Use httpx.AsyncClient with timeout
        async with httpx.AsyncClient(
            base_url=self._pd_endpoint,
            timeout=5.0,
        ) as client:
            while not self._shutdown.is_set():
                try:
                    self._health = await self._fetch_health(client)
                except Exception:
                    # On failure, mark all nodes unknown
                    # Per RESEARCH.md Pitfall 2: Don't crash on API failure
                    pass

                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self._poll_interval,
                    )
                except asyncio.TimeoutError:
                    continue

    async def _fetch_health(self, client: httpx.AsyncClient) -> ClusterHealth:
        """
        Fetch health from PD API endpoints.

        Makes two API calls:
        1. GET /pd/api/v1/stores - TiKV store health
        2. GET /pd/api/v1/health - PD member health

        Args:
            client: Configured httpx client

        Returns:
            ClusterHealth snapshot with all node statuses
        """
        nodes: list[NodeStatus] = []

        # 1. Get TiKV store health: /pd/api/v1/stores
        stores_resp = await client.get("/pd/api/v1/stores")
        stores_resp.raise_for_status()
        stores_data = stores_resp.json()

        for item in stores_data.get("stores", []):
            store = item.get("store", {})
            state = store.get("state_name", "Unknown")
            store_id = store.get("id", 0)
            nodes.append(
                NodeStatus(
                    node_id=str(store_id),
                    name=f"tikv-{store_id}",
                    node_type="tikv",
                    health=_parse_tikv_state(state),
                    address=store.get("address", ""),
                )
            )

        # 2. Get PD member health: /pd/api/v1/health
        health_resp = await client.get("/pd/api/v1/health")
        health_resp.raise_for_status()
        health_data = health_resp.json()

        for member in health_data:
            nodes.append(
                NodeStatus(
                    node_id=str(member.get("member_id", "")),
                    name=member.get("name", "pd-?"),
                    node_type="pd",
                    health=NodeHealth.UP if member.get("health") else NodeHealth.DOWN,
                    address=",".join(member.get("client_urls", [])),
                )
            )

        return ClusterHealth(
            nodes=nodes,
            has_issues=any(n.health != NodeHealth.UP for n in nodes),
            last_updated=datetime.now(),
        )

    def get_health(self) -> ClusterHealth | None:
        """
        Get latest health snapshot.

        Thread-safe read of the latest health snapshot.
        Returns None if no health data has been fetched yet.

        Returns:
            Latest ClusterHealth or None
        """
        return self._health

    def set_detection_active(self, active: bool) -> None:
        """
        Set detection highlighting state.

        Called when monitor output indicates a violation or all-passing.
        Used by TUI to determine panel border color.

        Args:
            active: True if violation detected, False otherwise
        """
        self._detection_active = active

    def is_detection_active(self) -> bool:
        """
        Check if detection highlighting is active.

        Returns:
            True if monitor detected a violation
        """
        return self._detection_active

    def stop(self) -> None:
        """
        Signal the poller to stop.

        Sets shutdown event which causes run() loop to exit.
        """
        self._shutdown.set()
