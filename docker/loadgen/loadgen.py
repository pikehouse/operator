#!/usr/bin/env python3
"""
Load generator for rate limiter cluster testing.

Sends configurable traffic patterns to the rate limiter cluster,
including steady rate and burst spikes for testing rate limiting behavior.
"""

import asyncio
import itertools
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx


# Configuration from environment variables
TARGETS = os.environ.get(
    "TARGETS",
    "http://ratelimiter-1:8000,http://ratelimiter-2:8000,http://ratelimiter-3:8000"
).split(",")
RPS = int(os.environ.get("RPS", "10"))
DURATION = int(os.environ.get("DURATION", "60"))  # 0 for infinite
BURST_ENABLED = os.environ.get("BURST_ENABLED", "true").lower() in ("true", "1", "yes")
BURST_MULTIPLIER = int(os.environ.get("BURST_MULTIPLIER", "5"))
BURST_DURATION = int(os.environ.get("BURST_DURATION", "5"))
BURST_INTERVAL = int(os.environ.get("BURST_INTERVAL", "30"))

# Stats reporting interval
STATS_INTERVAL = 10


@dataclass
class Stats:
    """Track request statistics."""
    requests: int = 0
    success: int = 0  # 200 responses
    blocked: int = 0  # 429 responses
    failed: int = 0   # Connection errors, other status codes
    start_time: float = field(default_factory=time.time)

    def rps(self) -> float:
        """Calculate actual requests per second."""
        elapsed = time.time() - self.start_time
        return self.requests / elapsed if elapsed > 0 else 0.0


class LoadGenerator:
    """Async load generator for rate limiter cluster."""

    def __init__(self, targets: list[str], rps: int):
        self.targets = targets
        self.target_cycle = itertools.cycle(targets)
        self.base_rps = rps
        self.current_rps = rps
        self.stats = Stats()
        self.semaphore = asyncio.Semaphore(100)
        self.shutdown_event = asyncio.Event()
        self.in_flight: set[asyncio.Task] = set()
        self.burst_mode = False

    async def send_request(self, client: httpx.AsyncClient) -> None:
        """Send a single rate limit check request."""
        target = next(self.target_cycle)
        url = f"{target}/check"
        payload = {
            "key": f"loadgen-{str(uuid4())[:8]}",
            "limit": 100,
            "window_ms": 60000
        }

        async with self.semaphore:
            self.stats.requests += 1
            try:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    self.stats.success += 1
                elif response.status_code == 429:
                    self.stats.blocked += 1
                else:
                    self.stats.failed += 1
            except (httpx.RequestError, httpx.TimeoutException):
                self.stats.failed += 1

    def print_stats(self) -> None:
        """Print current statistics."""
        mode = "BURST" if self.burst_mode else "STEADY"
        print(
            f"[{mode}] Requests: {self.stats.requests} | "
            f"Success: {self.stats.success} | "
            f"Blocked: {self.stats.blocked} | "
            f"Failed: {self.stats.failed} | "
            f"RPS: {self.stats.rps():.1f}",
            flush=True
        )

    def print_final_summary(self) -> None:
        """Print final summary statistics."""
        elapsed = time.time() - self.stats.start_time
        print("\n" + "=" * 60, flush=True)
        print("LOAD GENERATOR SUMMARY", flush=True)
        print("=" * 60, flush=True)
        print(f"Duration: {elapsed:.1f}s", flush=True)
        print(f"Total requests: {self.stats.requests}", flush=True)
        print(f"Success (200): {self.stats.success}", flush=True)
        print(f"Blocked (429): {self.stats.blocked}", flush=True)
        print(f"Failed: {self.stats.failed}", flush=True)
        print(f"Average RPS: {self.stats.rps():.1f}", flush=True)
        print("=" * 60, flush=True)

    async def stats_reporter(self) -> None:
        """Report stats periodically."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(STATS_INTERVAL)
            if not self.shutdown_event.is_set():
                self.print_stats()

    async def burst_controller(self) -> None:
        """Control burst mode timing."""
        if not BURST_ENABLED:
            return

        while not self.shutdown_event.is_set():
            # Wait for burst interval
            await asyncio.sleep(BURST_INTERVAL)
            if self.shutdown_event.is_set():
                break

            # Enter burst mode
            self.burst_mode = True
            self.current_rps = self.base_rps * BURST_MULTIPLIER
            print(f"\n>>> BURST MODE: {self.current_rps} RPS <<<", flush=True)

            # Stay in burst mode
            await asyncio.sleep(BURST_DURATION)

            # Return to steady mode
            self.burst_mode = False
            self.current_rps = self.base_rps
            print(f"\n>>> STEADY MODE: {self.current_rps} RPS <<<", flush=True)

    async def request_sender(self, client: httpx.AsyncClient) -> None:
        """Send requests at the configured rate."""
        while not self.shutdown_event.is_set():
            task = asyncio.create_task(self.send_request(client))
            self.in_flight.add(task)
            task.add_done_callback(self.in_flight.discard)

            # Sleep to maintain target RPS
            await asyncio.sleep(1.0 / self.current_rps)

    async def duration_timer(self) -> None:
        """Stop the generator after duration expires."""
        if DURATION == 0:
            # Infinite duration, wait for shutdown signal
            await self.shutdown_event.wait()
        else:
            await asyncio.sleep(DURATION)
            self.shutdown_event.set()

    def handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        print(f"\nReceived signal {signum}, shutting down...", flush=True)
        self.shutdown_event.set()

    async def run(self) -> None:
        """Run the load generator."""
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        print("=" * 60, flush=True)
        print("LOAD GENERATOR STARTING", flush=True)
        print("=" * 60, flush=True)
        print(f"Targets: {', '.join(self.targets)}", flush=True)
        print(f"Base RPS: {self.base_rps}", flush=True)
        print(f"Duration: {'infinite' if DURATION == 0 else f'{DURATION}s'}", flush=True)
        print(f"Burst enabled: {BURST_ENABLED}", flush=True)
        if BURST_ENABLED:
            print(f"Burst pattern: {BURST_MULTIPLIER}x RPS for {BURST_DURATION}s every {BURST_INTERVAL}s", flush=True)
        print("=" * 60 + "\n", flush=True)

        limits = httpx.Limits(max_connections=100)
        timeout = httpx.Timeout(10.0)

        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            # Start background tasks
            tasks = [
                asyncio.create_task(self.stats_reporter()),
                asyncio.create_task(self.burst_controller()),
                asyncio.create_task(self.request_sender(client)),
                asyncio.create_task(self.duration_timer()),
            ]

            # Wait for shutdown
            await self.shutdown_event.wait()

            # Cancel background tasks
            for task in tasks:
                task.cancel()

            # Wait for in-flight requests to complete
            if self.in_flight:
                print(f"Waiting for {len(self.in_flight)} in-flight requests...", flush=True)
                await asyncio.gather(*self.in_flight, return_exceptions=True)

        self.print_final_summary()


async def main() -> None:
    """Main entry point."""
    generator = LoadGenerator(TARGETS, RPS)
    await generator.run()


if __name__ == "__main__":
    asyncio.run(main())
