"""Tests for ChatDBAppEvalSubject."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.subjects.chat_db_app.subject import (
    BASE_APP_PORT,
    BASE_PG_PORT,
    BASE_PROM_PORT,
    CHAOS_PROFILES,
    LIGHT_LOAD,
    PORT_INCREMENT,
    ChatDBAppEvalSubject,
)


class TestPortAllocation:
    def test_instance_0_uses_base_ports(self):
        subj = ChatDBAppEvalSubject(instance_id=0)
        assert subj.app_port == BASE_APP_PORT
        assert subj.pg_port == BASE_PG_PORT
        assert subj.prom_port == BASE_PROM_PORT

    def test_instance_1_offsets_ports(self):
        subj = ChatDBAppEvalSubject(instance_id=1)
        assert subj.app_port == BASE_APP_PORT + PORT_INCREMENT
        assert subj.pg_port == BASE_PG_PORT + PORT_INCREMENT
        assert subj.prom_port == BASE_PROM_PORT + PORT_INCREMENT

    def test_instance_2_offsets_ports(self):
        subj = ChatDBAppEvalSubject(instance_id=2)
        assert subj.app_port == BASE_APP_PORT + 2 * PORT_INCREMENT
        assert subj.pg_port == BASE_PG_PORT + 2 * PORT_INCREMENT


class TestProjectNaming:
    def test_instance_0_default_project_name(self):
        subj = ChatDBAppEvalSubject(instance_id=0)
        assert subj.project_name == "chat-db-app"

    def test_instance_n_gets_numbered_project_name(self):
        subj = ChatDBAppEvalSubject(instance_id=3)
        assert subj.project_name == "chat-db-eval-3"


class TestChaosTypes:
    def test_returns_all_per_defect_types(self):
        subj = ChatDBAppEvalSubject(instance_id=0)
        types = subj.get_chaos_types()
        assert "missing_index" in types
        assert "pool_exhaustion" in types
        assert "streaming_txn" in types
        assert "counter_race" in types
        assert "fulltext_search" in types
        assert "read_scale" in types
        assert "unbounded_results" in types
        assert "write_contention" in types
        assert "write_amplification" in types
        assert "correlated_subquery" in types
        assert "notification_fanout" in types
        assert "notification_counter" in types
        assert "notification_realtime" in types
        assert "notification_poll_idle" in types
        assert "notification_mark_read" in types
        assert "notification_n_plus_one" in types
        assert "notification_payload" in types
        assert "notification_cleanup" in types
        assert "notification_serialize" in types
        assert len(types) == 19


class TestSourceDir:
    def test_source_dir_points_to_chat_db_app_service(self):
        subj = ChatDBAppEvalSubject(instance_id=0)
        # Should point to subjects/chat-db-app/service/ relative to repo root
        assert subj.source_dir.name == "service"
        assert "chat-db-app" in str(subj.source_dir)


class TestEnsureWorkspace:
    @pytest.mark.asyncio
    async def test_creates_workspace_and_env_file(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)

        # Patch CodeWorkspace.create_from to avoid needing real source
        mock_ws = MagicMock()
        mock_ws.workspace_dir = tmp_path / "chat-db-app-0"
        mock_ws.workspace_dir.mkdir(parents=True, exist_ok=True)
        mock_ws.initial_commit = "abc123"

        with patch(
            "eval.subjects.chat_db_app.subject.CodeWorkspace.create_from",
            return_value=mock_ws,
        ):
            ws = await subj._ensure_workspace()

        assert ws is mock_ws
        assert subj.workspace is mock_ws

        # .env file should contain port mappings and light load
        env_file = mock_ws.workspace_dir / ".env"
        assert env_file.exists()
        env_text = env_file.read_text()
        assert f"APP_HOST_PORT={BASE_APP_PORT}" in env_text
        assert f"PG_HOST_PORT={BASE_PG_PORT}" in env_text
        assert f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}" in env_text

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = tmp_path / "chat-db-app-0"
        mock_ws.workspace_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "eval.subjects.chat_db_app.subject.CodeWorkspace.create_from",
            return_value=mock_ws,
        ) as mock_create:
            await subj._ensure_workspace()
            await subj._ensure_workspace()

        # Should only create once
        assert mock_create.call_count == 1


class TestInjectChaos:
    @pytest.mark.asyncio
    async def test_unknown_chaos_type_raises(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        subj.workspace = MagicMock()

        with pytest.raises(ValueError, match="Unknown chaos type"):
            await subj.inject_chaos("node_kill")

    @pytest.mark.asyncio
    async def test_load_pressure_alias_resolves_to_pool_exhaustion(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws._run_compose = MagicMock()
        subj.workspace = mock_ws

        pool_profile = CHAOS_PROFILES["pool_exhaustion"]
        metadata = await subj.inject_chaos("load_pressure")

        assert metadata["chaos_type"] == "pool_exhaustion"
        assert metadata["original_chaos_type"] == "load_pressure"
        assert metadata["load_params"]["NUM_USERS"] == pool_profile["NUM_USERS"]

        env_text = (ws_dir / ".env").read_text()
        assert f"NUM_USERS={pool_profile['NUM_USERS']}" in env_text

    @pytest.mark.asyncio
    async def test_per_defect_chaos_type(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws._run_compose = MagicMock()
        subj.workspace = mock_ws

        profile = CHAOS_PROFILES["streaming_txn"]
        metadata = await subj.inject_chaos("streaming_txn")

        assert metadata["chaos_type"] == "streaming_txn"
        assert metadata["load_params"]["STREAM_RATIO"] == profile["STREAM_RATIO"]

        env_text = (ws_dir / ".env").read_text()
        assert f"STREAM_RATIO={profile['STREAM_RATIO']}" in env_text

    @pytest.mark.asyncio
    async def test_counter_race_enables_burst_mode(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws._run_compose = MagicMock()
        subj.workspace = mock_ws

        metadata = await subj.inject_chaos("counter_race")

        assert metadata["load_params"]["BURST_MODE"] == "true"
        assert metadata["load_params"]["BURST_CONCURRENCY"] == "10"

        env_text = (ws_dir / ".env").read_text()
        assert "BURST_MODE=true" in env_text
        assert "BURST_CONCURRENCY=10" in env_text

    @pytest.mark.asyncio
    async def test_accepts_overrides(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws._run_compose = MagicMock()
        subj.workspace = mock_ws

        metadata = await subj.inject_chaos(
            "pool_exhaustion", num_users=50, request_delay=0.1
        )

        assert metadata["load_params"]["NUM_USERS"] == "50"
        assert metadata["load_params"]["REQUEST_DELAY"] == "0.1"

        env_text = (ws_dir / ".env").read_text()
        assert "NUM_USERS=50" in env_text
        assert "REQUEST_DELAY=0.1" in env_text


class TestCleanupChaos:
    @pytest.mark.asyncio
    async def test_restores_light_load(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws._run_compose = MagicMock()
        subj.workspace = mock_ws

        await subj.cleanup_chaos({
            "chaos_type": "pool_exhaustion",
            "load_params": CHAOS_PROFILES["pool_exhaustion"],
        })

        env_text = (ws_dir / ".env").read_text()
        assert f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}" in env_text
        assert f"REQUEST_DELAY={LIGHT_LOAD['REQUEST_DELAY']}" in env_text

    @pytest.mark.asyncio
    async def test_cleanup_works_for_all_chaos_types(self, tmp_path):
        for chaos_type in CHAOS_PROFILES:
            subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
            ws_dir = tmp_path / "chat-db-app-0"
            ws_dir.mkdir(parents=True, exist_ok=True)

            mock_ws = MagicMock()
            mock_ws.workspace_dir = ws_dir
            mock_ws._run_compose = MagicMock()
            subj.workspace = mock_ws

            await subj.cleanup_chaos({"chaos_type": chaos_type})

            env_text = (ws_dir / ".env").read_text()
            assert f"NUM_USERS={LIGHT_LOAD['NUM_USERS']}" in env_text

    @pytest.mark.asyncio
    async def test_noop_for_empty_metadata(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        subj.workspace = MagicMock()
        # Should not raise
        await subj.cleanup_chaos({})
        await subj.cleanup_chaos({"chaos_type": "something_else"})


class TestGetAgentContext:
    def test_no_workspace_returns_empty(self):
        subj = ChatDBAppEvalSubject(instance_id=0)
        assert subj.get_agent_context() == ""

    def test_includes_compose_command(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)
        ws_dir = tmp_path / "chat-db-app-0"
        ws_dir.mkdir(parents=True)

        mock_ws = MagicMock()
        mock_ws.workspace_dir = ws_dir
        mock_ws.compose_command = "docker compose -f /tmp/ws/docker-compose.yaml -p test"
        subj.workspace = mock_ws

        ctx = subj.get_agent_context()
        assert "docker compose -f /tmp/ws/docker-compose.yaml -p test" in ctx
        assert "build app" in ctx
        assert "up -d app" in ctx
        assert "git -C" in ctx
        assert str(ws_dir) in ctx


class TestCaptureState:
    @pytest.mark.asyncio
    async def test_includes_workspace_snapshot(self, tmp_path):
        subj = ChatDBAppEvalSubject(instance_id=0, workspace_base=tmp_path)

        mock_ws = MagicMock()
        mock_ws.snapshot.return_value = {
            "commit_hash": "abc",
            "tree_hash": "def",
            "dirty": False,
            "diff_stat": "",
            "log": "initial",
        }
        mock_ws.full_diff.return_value = ""
        subj.workspace = mock_ws

        # Patch httpx to avoid real HTTP calls
        with patch("eval.subjects.chat_db_app.subject.httpx.AsyncClient") as mock_httpx:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"status": "healthy"}
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client

            state = await subj.capture_state()

        assert "code_workspace" in state
        assert state["code_workspace"]["commit_hash"] == "abc"
        assert "code_diff" in state
        assert "app" in state


class TestSubjectRegistration:
    def test_chat_db_app_registered_in_factory(self):
        from eval.subjects.factory import SubjectRegistry

        assert SubjectRegistry.is_registered("chat-db-app", "local")
        assert "chat-db-app" in SubjectRegistry.list_subjects()

    def test_factory_creates_correct_type(self):
        from eval.subjects.factory import SubjectRegistry

        subj = SubjectRegistry.create("chat-db-app", instance_id=0)
        assert isinstance(subj, ChatDBAppEvalSubject)
        assert subj.instance_id == 0
