"""Tests for database backend abstraction (--remote flag support).

Tests the get_db() helper, dotenv loading, protocol compliance, and
that analysis functions accept EvalDBProtocol.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.exceptions import Exit as ClickExit

from eval.runner.db import EvalDB, EvalDBProtocol


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database path."""
    return tmp_path / "test_eval.db"


def run_async(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestGetDb:
    """Tests for the get_db() helper function."""

    def test_get_db_local(self, tmp_db):
        """get_db(remote=False) returns an EvalDB instance."""
        from eval.runner.db import get_db

        async def _test():
            db = await get_db(remote=False, db_path=tmp_db)
            assert isinstance(db, EvalDB)
            assert tmp_db.exists()

        run_async(_test())

    def test_get_db_remote_missing_url(self, tmp_db):
        """get_db(remote=True) raises RuntimeError when EVAL_DATABASE_URL is not set."""
        from eval.runner.db import get_db

        async def _test():
            with patch.dict(os.environ, {}, clear=True):
                # Remove EVAL_DATABASE_URL if present
                os.environ.pop("EVAL_DATABASE_URL", None)
                with pytest.raises(RuntimeError):
                    await get_db(remote=True, db_path=tmp_db)

        run_async(_test())

    def test_get_db_remote_with_url(self, tmp_db):
        """get_db(remote=True) returns a PostgresDB instance when URL is set."""
        from eval.runner.db import get_db

        async def _test():
            with patch.dict(os.environ, {"EVAL_DATABASE_URL": "postgresql://localhost/test"}):
                with patch("eval.runner.db_postgres.asyncpg") as mock_asyncpg:
                    # Mock create_pool to return a pool with proper acquire() async CM
                    mock_conn = AsyncMock()
                    mock_conn.execute = AsyncMock()

                    mock_acquire_cm = MagicMock()
                    mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
                    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)

                    mock_pool = MagicMock()
                    mock_pool.acquire.return_value = mock_acquire_cm

                    mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

                    db = await get_db(remote=True, db_path=tmp_db)

                    from eval.runner.db_postgres import PostgresDB
                    assert isinstance(db, PostgresDB)

        run_async(_test())


class TestDotenvLoading:
    """Tests for the _load_dotenv() function."""

    def test_dotenv_loading(self, tmp_path):
        """_load_dotenv() picks up .env files from ancestor directories."""
        from eval.cli import _load_dotenv

        # Create a temp .env file
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_VAR_XYZ=hello_world\n")

        # Remove from env if set
        os.environ.pop("TEST_DOTENV_VAR_XYZ", None)

        with patch("eval.cli.Path.cwd", return_value=tmp_path):
            _load_dotenv()

        assert os.environ.get("TEST_DOTENV_VAR_XYZ") == "hello_world"

        # Cleanup
        del os.environ["TEST_DOTENV_VAR_XYZ"]

    def test_dotenv_no_override(self, tmp_path):
        """_load_dotenv() does not override variables already in os.environ."""
        from eval.cli import _load_dotenv

        # Create a temp .env file
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_NOOVERRIDE=from_file\n")

        # Set the var in env first
        os.environ["TEST_DOTENV_NOOVERRIDE"] = "from_env"

        with patch("eval.cli.Path.cwd", return_value=tmp_path):
            _load_dotenv()

        assert os.environ.get("TEST_DOTENV_NOOVERRIDE") == "from_env"

        # Cleanup
        del os.environ["TEST_DOTENV_NOOVERRIDE"]


class TestProtocolCompliance:
    """Tests that both backends satisfy EvalDBProtocol."""

    def test_evaldb_is_protocol(self):
        """EvalDB satisfies EvalDBProtocol (runtime_checkable)."""
        db = EvalDB(Path("dummy.db"))
        assert isinstance(db, EvalDBProtocol)

    def test_postgresdb_is_protocol(self):
        """PostgresDB satisfies EvalDBProtocol (runtime_checkable)."""
        with patch("eval.runner.db_postgres.asyncpg") as mock_asyncpg:
            mock_asyncpg.__bool__ = lambda self: True
            from eval.runner.db_postgres import PostgresDB
            db = PostgresDB("postgresql://localhost/test")
            assert isinstance(db, EvalDBProtocol)


class TestAnalysisAcceptsProtocol:
    """Tests that analysis functions accept EvalDBProtocol."""

    def test_analyze_campaign_signature(self):
        """analyze_campaign accepts EvalDBProtocol in its signature."""
        from eval.analysis.scoring import analyze_campaign
        import inspect

        sig = inspect.signature(analyze_campaign)
        db_param = sig.parameters["db"]
        assert db_param.annotation is EvalDBProtocol

    def test_compare_campaigns_signature(self):
        """compare_campaigns accepts EvalDBProtocol in its signature."""
        from eval.analysis.comparison import compare_campaigns
        import inspect

        sig = inspect.signature(compare_campaigns)
        db_param = sig.parameters["db"]
        assert db_param.annotation is EvalDBProtocol

    def test_compare_baseline_signature(self):
        """compare_baseline accepts EvalDBProtocol in its signature."""
        from eval.analysis.comparison import compare_baseline
        import inspect

        sig = inspect.signature(compare_baseline)
        db_param = sig.parameters["db"]
        assert db_param.annotation is EvalDBProtocol

    def test_compare_variants_signature(self):
        """compare_variants accepts EvalDBProtocol in its signature."""
        from eval.analysis.comparison import compare_variants
        import inspect

        sig = inspect.signature(compare_variants)
        db_param = sig.parameters["db"]
        assert db_param.annotation is EvalDBProtocol
