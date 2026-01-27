"""
TiKV health poller implementation for demo framework.

This module provides TiKVHealthPoller which implements HealthPollerProtocol
and polls PD API for cluster health status.

Simplified from ClusterHealthPoller in operator_core/tui/health.py to return
generic dict instead of typed ClusterHealth dataclass, enabling the demo
framework to work with any subject's health data.
"""

import asyncio
from datetime import datetime
from typing import Any

import httpx

from demo.types import HealthPollerProtocol


class TiKVHealthPoller(HealthPollerProtocol):
    """
    Polls PD API for TiKV cluster health.

    Implements HealthPollerProtocol by polling PD /stores and /health endpoints
    and returning health data as a generic dict.

    The health dict contains:
    - "nodes": list of {id, name, type, health, address}
    - "has_issues": bool indicating if any nodes are not UP
    - "last_updated": datetime of last successful poll

    Example:
        poller = TiKVHealthPoller(pd_endpoint="http://localhost:2379")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(poller.run())
            # ... in another task ...
            health = poller.get_health()
            if health and health["has_issues"]:
                print("Cluster has issues!")
            poller.stop()
    """

    def __init__(
        self,
        pd_endpoint: str = "http://localhost:2379",
        poll_interval: float = 2.0,
    ) -> None:
        """
        Initialize TiKV health poller.

        Args:
            pd_endpoint: Base URL for PD API (default: http://localhost:2379)
            poll_interval: Seconds between health polls (default: 2.0)
        """
        self._pd_endpoint = pd_endpoint
        self._poll_interval = poll_interval
        self._shutdown = asyncio.Event()
        self._health: dict[str, Any] | None = None

    async def run(self) -> None:
        """
        Run continuous health polling in background.

        Polls PD API at configured interval until stop() is called.
        On API failure, continues polling without crashing.
        """
        async with httpx.AsyncClient(
            base_url=self._pd_endpoint,
            timeout=5.0,
        ) as client:
            while not self._shutdown.is_set():
                try:
                    self._health = await self._fetch_health(client)
                except Exception:
                    # On failure, continue polling without crashing
                    # Health remains at last successful value or None
                    pass

                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self._poll_interval,
                    )
                except asyncio.TimeoutError:
                    continue

    async def _fetch_health(self, client: httpx.AsyncClient) -> dict[str, Any]:
        """
        Fetch health from PD API endpoints.

        Makes two API calls:
        1. GET /pd/api/v1/stores - TiKV store health
        2. GET /pd/api/v1/health - PD member health

        Args:
            client: Configured httpx client

        Returns:
            Health dict with nodes list, has_issues flag, and timestamp
        """
        nodes: list[dict[str, Any]] = []

        # 1. Get TiKV store health
        stores_resp = await client.get("/pd/api/v1/stores")
        stores_resp.raise_for_status()
        stores_data = stores_resp.json()

        for item in stores_data.get("stores", []):
            store = item.get("store", {})
            state = store.get("state_name", "Unknown")
            store_id = store.get("id", 0)

            # Parse state to health status
            health = self._parse_tikv_state(state)

            nodes.append({
                "id": str(store_id),
                "name": f"tikv-{store_id}",
                "type": "tikv",
                "health": health,
                "address": store.get("address", ""),
            })

        # 2. Get PD member health
        health_resp = await client.get("/pd/api/v1/health")
        health_resp.raise_for_status()
        health_data = health_resp.json()

        for member in health_data:
            nodes.append({
                "id": str(member.get("member_id", "")),
                "name": member.get("name", "pd-?"),
                "type": "pd",
                "health": "up" if member.get("health") else "down",
                "address": ",".join(member.get("client_urls", [])),
            })

        # 3. Get ops/sec from Prometheus (if available)
        ops_per_sec = await self._fetch_ops_per_sec(client)

        return {
            "nodes": nodes,
            "has_issues": any(n["health"] != "up" for n in nodes),
            "last_updated": datetime.now(),
            "ops_per_sec": ops_per_sec,
        }

    async def _fetch_ops_per_sec(self, client: httpx.AsyncClient) -> float | None:
        """
        Fetch TiKV ops/sec from Prometheus.

        Queries the tikv_grpc_msg_duration_seconds_count rate for overall throughput.

        Args:
            client: Configured httpx client

        Returns:
            ops/sec value if available, None otherwise
        """
        try:
            # Query Prometheus for TiKV gRPC request rate
            prom_client = httpx.AsyncClient(
                base_url="http://localhost:9090",
                timeout=5.0,
            )
            async with prom_client:
                query = 'sum(rate(tikv_storage_engine_async_request_total[30s]))'
                resp = await prom_client.get(
                    "/api/v1/query",
                    params={"query": query},
                )
                resp.raise_for_status()
                data = resp.json()

                # Parse Prometheus response
                results = data.get("data", {}).get("result", [])
                if results:
                    value = results[0].get("value", [None, "0"])
                    return float(value[1])
        except Exception:
            pass  # Prometheus not available or query failed

        return None

    def _parse_tikv_state(self, state: str) -> str:
        """
        Map TiKV state_name to simple health status.

        Args:
            state: State name from PD API (e.g., "Up", "Down", "Disconnected")

        Returns:
            Simple health status: "up", "down", "offline", or "unknown"
        """
        state_lower = state.lower()
        if state_lower == "up":
            return "up"
        elif state_lower in ("down", "disconnected"):
            return "down"
        elif state_lower in ("offline", "tombstone"):
            return "offline"
        else:
            return "unknown"

    def get_health(self) -> dict[str, Any] | None:
        """
        Get latest health snapshot.

        Returns:
            Health dict or None if no data available yet
        """
        return self._health

    def stop(self) -> None:
        """
        Stop health polling and clean up resources.

        Sets shutdown event which causes run() loop to exit.
        """
        self._shutdown.set()
