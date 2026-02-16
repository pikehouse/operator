"""
Streaming response logic for the chat application.
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
    """Simulate a streaming LLM response.

    Split into separate transactions so we don't hold a DB connection
    during the simulated generation time.
    """
    conv_uuid = uuid.UUID(conversation_id)

    # Transaction 1: Insert user message
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, token_count)
            VALUES ($1, 'user', $2, $3)
            """,
            conv_uuid,
            user_content,
            user_token_count,
        )

    # Simulate streaming — no DB connection held
    chunks: list[str] = []
    num_chunks = random.randint(5, len(RESPONSE_FRAGMENTS))
    selected = random.sample(RESPONSE_FRAGMENTS, num_chunks)

    full_response = ""
    total_tokens = 0
    for chunk in selected:
        await asyncio.sleep(random.uniform(0.2, 0.8))
        full_response += chunk
        total_tokens += len(chunk.split())
        chunks.append(chunk)

    # Transaction 2: Insert assistant message and update counters
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, token_count)
                VALUES ($1, 'assistant', $2, $3)
                """,
                conv_uuid,
                full_response,
                total_tokens,
            )

            await conn.execute(
                """
                UPDATE conversations
                SET message_count = message_count + 2,
                    updated_at = now()
                WHERE id = $1
                """,
                conv_uuid,
            )

            conv = await conn.fetchrow(
                "SELECT user_id FROM conversations WHERE id = $1",
                conv_uuid,
            )
            if conv:
                total = user_token_count + total_tokens
                await conn.execute(
                    "UPDATE users SET token_usage = token_usage + $1, updated_at = now() WHERE id = $2",
                    total,
                    conv["user_id"],
                )

    return chunks
