"""
Connection pool setup for the chat application.

INTENTIONALLY NAIVE: No max_size, no checkout timeout, no statement_timeout.
Under heavy load this will exhaust PostgreSQL connections.

The fix (for the agent to discover):
- Set max_size=20 on the pool
- Set command_timeout=5 for checkout timeout
- Set statement_timeout via server_settings
"""

import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    """
    Create an asyncpg connection pool.

    NAIVE: No max_size means pool grows unbounded until PG max_connections.
    No timeout means callers block forever waiting for a connection.
    No statement_timeout means bad queries run forever.
    """
    pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        # BUG: no max_size - pool grows unbounded
        # BUG: no command_timeout - no checkout timeout
        # BUG: no server_settings={"statement_timeout": "30000"}
    )
    return pool
