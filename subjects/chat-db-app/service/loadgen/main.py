"""
Load generator for the chat-db-app.

Simulates multiple users sending messages concurrently.
Configurable intensity from light to heavy load.

Under light load: app is healthy.
Under heavy load: naive patterns break (pool exhaustion, lock contention).

Environment variables:
    APP_URL: Base URL of the chat app (default: http://app:8000)
    NUM_USERS: Number of simulated concurrent users (default: 3)
    REQUEST_DELAY: Seconds between requests per user (default: 2.0)
    STREAM_RATIO: Fraction of requests that are streaming (default: 0.3)
    RAMP_UP_SECONDS: Time to ramp up to full load (default: 10)
    READ_RATIO: Fraction of non-streaming requests that read messages (default: 0.3)
    BURST_MODE: When true, each user fires concurrent writes to same conversation (default: false)
    BURST_CONCURRENCY: Parallel writes per burst when BURST_MODE is true (default: 1)
    SEARCH_ENABLED: Enable search requests (default: false)
    SEARCH_RATIO: Fraction of iterations that include a search request (default: 0.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("loadgen")

APP_URL = os.environ.get("APP_URL", "http://app:8000")
NUM_USERS = int(os.environ.get("NUM_USERS", "3"))
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "2.0"))
STREAM_RATIO = float(os.environ.get("STREAM_RATIO", "0.3"))
RAMP_UP_SECONDS = float(os.environ.get("RAMP_UP_SECONDS", "10"))
READ_RATIO = float(os.environ.get("READ_RATIO", "0.3"))
BURST_MODE = os.environ.get("BURST_MODE", "false").lower() in ("true", "1", "yes")
BURST_CONCURRENCY = int(os.environ.get("BURST_CONCURRENCY", "1"))
SEARCH_ENABLED = os.environ.get("SEARCH_ENABLED", "false").lower() in ("true", "1", "yes")
SEARCH_RATIO = float(os.environ.get("SEARCH_RATIO", "0.0"))

SEARCH_TERMS = [
    "quantum", "database", "PostgreSQL", "connection", "deadlock",
    "ACID", "consistency", "Raft", "consensus", "microservices",
    "observer", "threads", "garbage", "race", "capital",
    "connection pool", "CAP theorem", "garbage collection",
    "kubernetes", "terraform", "monitoring",
]

SAMPLE_MESSAGES = [
    "What is the capital of France?",
    "Explain quantum computing in simple terms.",
    "Write a haiku about databases.",
    "How do connection pools work in PostgreSQL?",
    "What are the ACID properties?",
    "Describe the difference between SQL and NoSQL.",
    "What is a deadlock and how can it be prevented?",
    "Explain the CAP theorem.",
    "What is eventual consistency?",
    "How does Raft consensus work?",
    "What are the benefits of microservices?",
    "Explain the observer pattern.",
    "What is the difference between threads and processes?",
    "How does garbage collection work?",
    "What is a race condition?",
]


async def wait_for_app(client: httpx.AsyncClient) -> None:
    """Wait for the app to become healthy."""
    for attempt in range(60):
        try:
            resp = await client.get(f"{APP_URL}/health")
            if resp.status_code == 200:
                log.info("App is healthy")
                return
        except httpx.ConnectError:
            pass
        log.info(f"Waiting for app... (attempt {attempt + 1})")
        await asyncio.sleep(2)
    raise RuntimeError("App did not become healthy in time")


async def simulate_user(user_id: int, client: httpx.AsyncClient) -> None:
    """Simulate a single user sending messages."""
    # Stagger start times during ramp-up
    delay = (user_id / max(NUM_USERS, 1)) * RAMP_UP_SECONDS
    await asyncio.sleep(delay)

    log.info(f"User {user_id} starting")

    conversation_id = None

    while True:
        try:
            # Create a new conversation periodically
            if conversation_id is None or random.random() < 0.1:
                resp = await client.post(
                    f"{APP_URL}/api/conversations",
                    json={"title": f"User {user_id} conversation"},
                    timeout=30,
                )
                if resp.status_code == 200:
                    conversation_id = resp.json()["id"]
                    log.info(f"User {user_id}: created conversation {conversation_id[:8]}")
                else:
                    log.warning(f"User {user_id}: failed to create conversation: {resp.status_code}")
                    await asyncio.sleep(REQUEST_DELAY)
                    continue

            # Send a message (streaming or regular)
            message = random.choice(SAMPLE_MESSAGES)
            token_count = len(message.split()) * 2  # rough token estimate

            if random.random() < STREAM_RATIO:
                # Streaming request (holds transaction open)
                start = time.monotonic()
                resp = await client.post(
                    f"{APP_URL}/api/conversations/{conversation_id}/stream",
                    json={"content": message, "token_count": token_count},
                    timeout=60,
                )
                elapsed = time.monotonic() - start
                if resp.status_code == 200:
                    log.info(f"User {user_id}: stream response {elapsed:.1f}s")
                else:
                    log.warning(f"User {user_id}: stream failed {resp.status_code} ({elapsed:.1f}s)")
            else:
                # Regular message
                start = time.monotonic()
                resp = await client.post(
                    f"{APP_URL}/api/conversations/{conversation_id}/messages",
                    json={
                        "content": message,
                        "role": "user",
                        "token_count": token_count,
                    },
                    timeout=30,
                )
                elapsed = time.monotonic() - start
                if resp.status_code == 200:
                    log.info(f"User {user_id}: message sent {elapsed:.1f}s")
                else:
                    log.warning(f"User {user_id}: message failed {resp.status_code} ({elapsed:.1f}s)")

            # Also occasionally list conversations or read messages
            if random.random() < 0.2:
                await client.get(f"{APP_URL}/api/conversations", timeout=10)

            if random.random() < READ_RATIO and conversation_id:
                await client.get(
                    f"{APP_URL}/api/conversations/{conversation_id}/messages",
                    timeout=10,
                )

            if SEARCH_ENABLED and random.random() < SEARCH_RATIO:
                term = random.choice(SEARCH_TERMS)
                try:
                    resp = await client.get(
                        f"{APP_URL}/api/conversations/search",
                        params={"q": term},
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        results = resp.json()
                        log.info(f"User {user_id}: search '{term}' returned {len(results)} results")
                    else:
                        log.warning(f"User {user_id}: search failed {resp.status_code}")
                except httpx.TimeoutException:
                    log.warning(f"User {user_id}: search timed out for '{term}'")

        except httpx.TimeoutException:
            log.warning(f"User {user_id}: request timed out")
        except httpx.ConnectError:
            log.warning(f"User {user_id}: connection error, retrying...")
            await asyncio.sleep(5)
            continue
        except Exception as e:
            log.error(f"User {user_id}: unexpected error: {e}")

        # Wait between requests
        jitter = random.uniform(0.5, 1.5)
        await asyncio.sleep(REQUEST_DELAY * jitter)


async def simulate_user_burst(user_id: int, client: httpx.AsyncClient) -> None:
    """Simulate a user firing concurrent writes to the same conversation.

    Each burst creates one conversation then fires BURST_CONCURRENCY
    parallel add_message requests, triggering read-modify-write races
    on the token counter.
    """
    delay = (user_id / max(NUM_USERS, 1)) * RAMP_UP_SECONDS
    await asyncio.sleep(delay)

    log.info(f"Burst user {user_id} starting (concurrency={BURST_CONCURRENCY})")

    while True:
        try:
            # Create a fresh conversation for each burst
            resp = await client.post(
                f"{APP_URL}/api/conversations",
                json={"title": f"Burst user {user_id} conversation"},
                timeout=30,
            )
            if resp.status_code != 200:
                log.warning(f"Burst user {user_id}: failed to create conversation: {resp.status_code}")
                await asyncio.sleep(REQUEST_DELAY)
                continue

            conversation_id = resp.json()["id"]

            # Fire concurrent writes
            async def _send_one(idx: int) -> None:
                message = random.choice(SAMPLE_MESSAGES)
                token_count = len(message.split()) * 2
                start = time.monotonic()
                r = await client.post(
                    f"{APP_URL}/api/conversations/{conversation_id}/messages",
                    json={
                        "content": message,
                        "role": "user",
                        "token_count": token_count,
                    },
                    timeout=30,
                )
                elapsed = time.monotonic() - start
                if r.status_code == 200:
                    log.info(f"Burst user {user_id}[{idx}]: sent {elapsed:.1f}s")
                else:
                    log.warning(f"Burst user {user_id}[{idx}]: failed {r.status_code} ({elapsed:.1f}s)")

            await asyncio.gather(*[_send_one(i) for i in range(BURST_CONCURRENCY)])

        except httpx.TimeoutException:
            log.warning(f"Burst user {user_id}: request timed out")
        except httpx.ConnectError:
            log.warning(f"Burst user {user_id}: connection error, retrying...")
            await asyncio.sleep(5)
            continue
        except Exception as e:
            log.error(f"Burst user {user_id}: unexpected error: {e}")

        jitter = random.uniform(0.5, 1.5)
        await asyncio.sleep(REQUEST_DELAY * jitter)


async def main() -> None:
    mode = "burst" if BURST_MODE else "normal"
    search_info = f", search={SEARCH_RATIO:.0%}" if SEARCH_ENABLED else ""
    log.info(
        f"Load generator starting: {NUM_USERS} users, {REQUEST_DELAY}s delay, "
        f"{STREAM_RATIO:.0%} streaming, read_ratio={READ_RATIO}, mode={mode}{search_info}"
    )

    async with httpx.AsyncClient() as client:
        await wait_for_app(client)

        # Choose user simulation function based on mode
        user_fn = simulate_user_burst if BURST_MODE else simulate_user
        tasks = [
            asyncio.create_task(user_fn(i, client))
            for i in range(NUM_USERS)
        ]

        # Run until cancelled
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Load generator shutting down")


if __name__ == "__main__":
    asyncio.run(main())
