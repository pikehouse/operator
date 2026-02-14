"""
Database schema and query functions for the chat application.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg


async def create_schema(pool: asyncpg.Pool) -> None:
    """Create database tables."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT UNIQUE NOT NULL,
                token_usage BIGINT NOT NULL DEFAULT 0,
                plan_tier TEXT NOT NULL DEFAULT 'free',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id),
                title TEXT NOT NULL DEFAULT 'New conversation',
                message_count INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                token_count INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

        """)


async def ensure_default_user(pool: asyncpg.Pool, user_id: str) -> None:
    """Create a default user if it doesn't exist."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, email, plan_tier)
            VALUES ($1, $2, 'free')
            ON CONFLICT (id) DO NOTHING
            """,
            uuid.UUID(user_id),
            f"user-{user_id[:8]}@example.com",
        )


async def create_conversation(
    pool: asyncpg.Pool, user_id: str, title: str
) -> dict:
    """Create a new conversation."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, $2)
            RETURNING id, user_id, title, message_count, updated_at, created_at
            """,
            uuid.UUID(user_id),
            title,
        )
        return dict(row)


async def list_conversations(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """List conversations for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, title, message_count, updated_at, created_at
            FROM conversations
            WHERE user_id = $1
            ORDER BY updated_at DESC
            """,
            uuid.UUID(user_id),
        )
        return [dict(r) for r in rows]


async def get_messages(pool: asyncpg.Pool, conversation_id: str) -> list[dict]:
    """Get messages for a conversation."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, conversation_id, role, content, token_count, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            """,
            uuid.UUID(conversation_id),
        )
        return [dict(r) for r in rows]


async def add_message(
    pool: asyncpg.Pool,
    conversation_id: str,
    role: str,
    content: str,
    token_count: int,
) -> dict:
    """Add a message to a conversation."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Insert the message
            row = await conn.fetchrow(
                """
                INSERT INTO messages (conversation_id, role, content, token_count)
                VALUES ($1, $2, $3, $4)
                RETURNING id, conversation_id, role, content, token_count, created_at
                """,
                uuid.UUID(conversation_id),
                role,
                content,
                token_count,
            )

            # Update conversation message count and timestamp
            await conn.execute(
                """
                UPDATE conversations
                SET message_count = message_count + 1,
                    updated_at = now()
                WHERE id = $1
                """,
                uuid.UUID(conversation_id),
            )

            conv = await conn.fetchrow(
                "SELECT user_id FROM conversations WHERE id = $1",
                uuid.UUID(conversation_id),
            )
            if conv:
                current = await conn.fetchval(
                    "SELECT token_usage FROM users WHERE id = $1",
                    conv["user_id"],
                )
                await conn.execute(
                    "UPDATE users SET token_usage = $1, updated_at = now() WHERE id = $2",
                    (current or 0) + token_count,
                    conv["user_id"],
                )

            return dict(row)


async def search_messages(
    pool: asyncpg.Pool, user_id: str, query: str, limit: int = 50
) -> list[dict]:
    """Search messages across a user's conversations."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, m.conversation_id, m.role, m.content,
                   m.token_count, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = $1
              AND m.content ILIKE '%' || $2 || '%'
            ORDER BY m.created_at DESC
            LIMIT $3
            """,
            uuid.UUID(user_id),
            query,
            limit,
        )
        return [dict(r) for r in rows]


async def delete_conversation(pool: asyncpg.Pool, conversation_id: str) -> bool:
    """
    Delete a conversation and its messages.

    Messages are cascade-deleted via FK. Updates user token count.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get total tokens to subtract
            total_tokens = await conn.fetchval(
                "SELECT COALESCE(SUM(token_count), 0) FROM messages WHERE conversation_id = $1",
                uuid.UUID(conversation_id),
            )

            # Get user_id before deleting
            conv = await conn.fetchrow(
                "SELECT user_id FROM conversations WHERE id = $1",
                uuid.UUID(conversation_id),
            )
            if not conv:
                return False

            # Delete conversation (messages cascade)
            await conn.execute(
                "DELETE FROM conversations WHERE id = $1",
                uuid.UUID(conversation_id),
            )

            current = await conn.fetchval(
                "SELECT token_usage FROM users WHERE id = $1",
                conv["user_id"],
            )
            new_usage = max(0, (current or 0) - total_tokens)
            await conn.execute(
                "UPDATE users SET token_usage = $1, updated_at = now() WHERE id = $2",
                new_usage,
                conv["user_id"],
            )

            return True
