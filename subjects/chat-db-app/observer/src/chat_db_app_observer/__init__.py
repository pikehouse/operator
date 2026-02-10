"""
Chat DB App subject implementation for the AI-powered operator.

This package provides the chat-db-app implementation of the Subject interface
defined in operator-protocols. It observes a naive chat application backed by
PostgreSQL, detecting connection pool exhaustion, lock contention, idle-in-
transaction sessions, and other database health issues.

Includes:
- ChatDBAppSubject: SubjectProtocol implementation
- ChatDBAppInvariantChecker: InvariantCheckerProtocol implementation
- AppClient: HTTP client for app /health and /metrics
- PgClient: PostgreSQL diagnostic client (pg_stat_activity, pg_stat_database)
- Factory function for CLI integration
"""

# Subject-specific context for agent system prompt
AGENT_PROMPT = """
Chat DB App context:
- A FastAPI chat application backed by PostgreSQL (like a naive ChatGPT backend)
- The app has intentional naive patterns that break under load:
  1. No connection pool limits (pool grows until max_connections)
  2. Read-modify-write for token counters (race condition)
  3. Streaming responses hold transactions open for 10-30s
  4. No index on messages.conversation_id (full table scans)
  5. No retry on serialization failures
  6. No statement_timeout

File layout (relative to workspace root):
  docker-compose.yaml   ← compose file for all containers
  app/
    main.py             ← FastAPI endpoints
    pool.py             ← asyncpg pool creation (add max_size, command_timeout)
    models.py           ← query functions (fix read-modify-write, add index)
    streaming.py        ← streaming logic (narrow transaction scope)
    Dockerfile          ← app container image
  loadgen/              ← load generator
  config/               ← prometheus config

Key diagnostic queries:
  - pg_stat_activity: connection states, idle-in-transaction, lock waiters
  - pg_stat_database: deadlock counts
  - EXPLAIN ANALYZE: run on slow queries to check for sequential scans, missing indexes
App endpoints: /health (pool status), /metrics (Prometheus format)
Containers: postgres, app, loadgen, prometheus

IMPORTANT: The loadgen container simulates production user traffic. Do not stop,
restart, or modify the loadgen — treat it as an external workload you cannot
control. Focus on fixing the app code to handle the load correctly.
"""

from operator_protocols import InvariantViolation

from chat_db_app_observer.app_client import AppClient
from chat_db_app_observer.factory import create_chat_db_app_subject_and_checker
from chat_db_app_observer.invariants import (
    DB_UNREACHABLE_CONFIG,
    HIGH_ERROR_RATE_CONFIG,
    HIGH_LATENCY_CONFIG,
    IDLE_IN_TRANSACTION_CONFIG,
    LOCK_CONTENTION_CONFIG,
    POOL_EXHAUSTION_CONFIG,
    ChatDBAppInvariantChecker,
    InvariantConfig,
)
from chat_db_app_observer.pg_client import PgClient
from chat_db_app_observer.subject import ChatDBAppSubject
from chat_db_app_observer.types import (
    AppHealthResponse,
    EndpointMetrics,
    LongRunningQuery,
    PgDatabaseStats,
    PgSessionStats,
    PoolMetrics,
)

__all__ = [
    "AGENT_PROMPT",
    "ChatDBAppSubject",
    "ChatDBAppInvariantChecker",
    "create_chat_db_app_subject_and_checker",
    "AppClient",
    "PgClient",
    "InvariantConfig",
    "InvariantViolation",
    "POOL_EXHAUSTION_CONFIG",
    "DB_UNREACHABLE_CONFIG",
    "IDLE_IN_TRANSACTION_CONFIG",
    "LOCK_CONTENTION_CONFIG",
    "HIGH_LATENCY_CONFIG",
    "HIGH_ERROR_RATE_CONFIG",
    "AppHealthResponse",
    "EndpointMetrics",
    "LongRunningQuery",
    "PgDatabaseStats",
    "PgSessionStats",
    "PoolMetrics",
]
