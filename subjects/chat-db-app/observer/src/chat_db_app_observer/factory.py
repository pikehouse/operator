"""
Factory function for creating ChatDBApp subject and checker instances.

Provides a factory for CLI integration, allowing operator-core CLI to
create instances without direct imports.
"""

from __future__ import annotations

import httpx

from chat_db_app_observer.app_client import AppClient
from chat_db_app_observer.invariants import ChatDBAppInvariantChecker
from chat_db_app_observer.pg_client import PgClient
from chat_db_app_observer.subject import ChatDBAppSubject


async def create_chat_db_app_subject_and_checker(
    app_url: str,
    db_dsn: str,
    app_http: httpx.AsyncClient | None = None,
) -> tuple[ChatDBAppSubject, ChatDBAppInvariantChecker]:
    """
    Create a ChatDBApp subject and checker pair.

    Args:
        app_url: Base URL of the chat app (e.g., "http://localhost:8000")
        db_dsn: PostgreSQL connection string for diagnostic queries
            (e.g., "postgresql://operator@localhost:5432/chatdb")
        app_http: Optional pre-configured httpx client for the app.
            If None, a new client is created with 10s timeout.

    Returns:
        Tuple of (ChatDBAppSubject, ChatDBAppInvariantChecker) ready for use.

    Example:
        subject, checker = await create_chat_db_app_subject_and_checker(
            app_url="http://localhost:8000",
            db_dsn="postgresql://chatapp:chatapp@localhost:5432/chatdb",
        )
        observation = await subject.observe()
        violations = checker.check(observation)
    """
    if app_http is None:
        app_http = httpx.AsyncClient(base_url=app_url, timeout=10.0)

    app_client = AppClient(http=app_http)
    pg_client = await PgClient.create(db_dsn)

    subject = ChatDBAppSubject(app_client=app_client, pg_client=pg_client)
    checker = ChatDBAppInvariantChecker()

    return subject, checker
