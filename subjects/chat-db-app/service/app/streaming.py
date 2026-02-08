"""
Streaming response logic for the chat application.

INTENTIONALLY NAIVE: Holds a database transaction open for the entire
duration of the simulated streaming response (10-30 seconds).
This ties up a connection from the pool for the entire stream.

Under heavy load with many concurrent streams, this exhausts the
connection pool and causes pool_exhaustion.

The fix: Write the message first (narrow transaction), then stream
the response without holding a connection.
"""

from __future__ import annotations

import asyncio
import random
import uuid

import asyncpg


# Simulated response chunks (like an LLM generating tokens)
RESPONSE_FRAGMENTS = [
    "I understand your question. ",
    "Let me think about that. ",
    "Based on my analysis, ",
    "there are several factors to consider. ",
    "First, we should look at ",
    "the underlying assumptions. ",
    "Additionally, it's worth noting that ",
    "this relates to broader patterns ",
    "in the field. ",
    "To summarize, ",
    "the key insight is that ",
    "we need to balance multiple considerations. ",
    "I hope this helps clarify things. ",
    "Let me know if you have follow-up questions.",
]


async def stream_response(
    pool: asyncpg.Pool,
    conversation_id: str,
    user_content: str,
    user_token_count: int,
) -> list[str]:
    """
    Simulate a streaming LLM response while holding a transaction open.

    NAIVE: The entire operation - inserting user message, generating response,
    inserting assistant message, updating counters - happens in ONE transaction.
    The connection is held for the full streaming duration (several seconds).

    Fix: Split into two operations:
    1. Insert user message + start assistant placeholder (narrow transaction)
    2. Stream response chunks without holding a DB connection
    3. Update assistant message content when done (narrow transaction)
    """
    chunks: list[str] = []
    num_chunks = random.randint(5, len(RESPONSE_FRAGMENTS))
    selected = random.sample(RESPONSE_FRAGMENTS, num_chunks)

    async with pool.acquire() as conn:
        # BUG: Transaction wraps the entire streaming response
        async with conn.transaction():
            # Insert user message
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, token_count)
                VALUES ($1, 'user', $2, $3)
                """,
                uuid.UUID(conversation_id),
                user_content,
                user_token_count,
            )

            # Simulate streaming - each chunk takes 200-800ms
            # Connection is held the entire time
            full_response = ""
            total_tokens = 0
            for chunk in selected:
                await asyncio.sleep(random.uniform(0.2, 0.8))
                full_response += chunk
                total_tokens += len(chunk.split())
                chunks.append(chunk)

            # Insert assistant message
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, token_count)
                VALUES ($1, 'assistant', $2, $3)
                """,
                uuid.UUID(conversation_id),
                full_response,
                total_tokens,
            )

            # Update conversation
            await conn.execute(
                """
                UPDATE conversations
                SET message_count = message_count + 2,
                    updated_at = now()
                WHERE id = $1
                """,
                uuid.UUID(conversation_id),
            )

            # BUG: Read-modify-write for token counter
            conv = await conn.fetchrow(
                "SELECT user_id FROM conversations WHERE id = $1",
                uuid.UUID(conversation_id),
            )
            if conv:
                current = await conn.fetchval(
                    "SELECT token_usage FROM users WHERE id = $1",
                    conv["user_id"],
                )
                total = user_token_count + total_tokens
                await conn.execute(
                    "UPDATE users SET token_usage = $1, updated_at = now() WHERE id = $2",
                    (current or 0) + total,
                    conv["user_id"],
                )

    return chunks
