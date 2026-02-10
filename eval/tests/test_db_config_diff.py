"""Unit tests for eval.analysis.db_config_diff (no database needed)."""

from eval.analysis.db_config_diff import diff_db_config


def _make_state(
    tables=None,
    indexes=None,
    settings=None,
):
    return {
        "tables": tables or {},
        "indexes": indexes or [],
        "settings": settings or {},
    }


class TestDiffSettings:
    def test_setting_changed(self):
        initial = _make_state(settings={"statement_timeout": "0", "max_connections": "100"})
        final = _make_state(settings={"statement_timeout": "30000", "max_connections": "100"})
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert len(result["settings_changed"]) == 1
        assert result["settings_changed"][0] == {
            "name": "statement_timeout",
            "before": "0",
            "after": "30000",
        }

    def test_multiple_settings_changed(self):
        initial = _make_state(settings={"statement_timeout": "0", "work_mem": "4MB"})
        final = _make_state(settings={"statement_timeout": "30000", "work_mem": "8MB"})
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert len(result["settings_changed"]) == 2
        names = {s["name"] for s in result["settings_changed"]}
        assert names == {"statement_timeout", "work_mem"}

    def test_no_settings_changed(self):
        state = _make_state(settings={"statement_timeout": "0"})
        result = diff_db_config(state, state)
        assert result["settings_changed"] == []


class TestDiffIndexes:
    def test_index_added(self):
        initial = _make_state(indexes=[
            {"name": "users_pkey", "table": "users", "definition": "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)"},
        ])
        final = _make_state(indexes=[
            {"name": "users_pkey", "table": "users", "definition": "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)"},
            {"name": "idx_messages_conversation_id", "table": "messages", "definition": "CREATE INDEX idx_messages_conversation_id ON public.messages USING btree (conversation_id)"},
        ])
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert len(result["indexes_added"]) == 1
        assert result["indexes_added"][0]["name"] == "idx_messages_conversation_id"
        assert result["indexes_added"][0]["table"] == "messages"
        assert result["indexes_removed"] == []

    def test_index_removed(self):
        initial = _make_state(indexes=[
            {"name": "users_pkey", "table": "users", "definition": "CREATE UNIQUE INDEX ..."},
            {"name": "idx_old", "table": "users", "definition": "CREATE INDEX ..."},
        ])
        final = _make_state(indexes=[
            {"name": "users_pkey", "table": "users", "definition": "CREATE UNIQUE INDEX ..."},
        ])
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert len(result["indexes_removed"]) == 1
        assert result["indexes_removed"][0]["name"] == "idx_old"
        assert result["indexes_added"] == []


class TestDiffColumns:
    def test_column_added(self):
        initial = _make_state(tables={
            "messages": {"columns": [
                {"name": "id", "type": "uuid", "nullable": "NO", "default": "gen_random_uuid()"},
            ]},
        })
        final = _make_state(tables={
            "messages": {"columns": [
                {"name": "id", "type": "uuid", "nullable": "NO", "default": "gen_random_uuid()"},
                {"name": "metadata", "type": "jsonb", "nullable": "YES", "default": None},
            ]},
        })
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert len(result["columns_added"]) == 1
        assert result["columns_added"][0] == {
            "table": "messages",
            "name": "metadata",
            "type": "jsonb",
        }
        assert result["columns_removed"] == []

    def test_table_added(self):
        initial = _make_state(tables={"users": {"columns": []}})
        final = _make_state(tables={
            "users": {"columns": []},
            "audit_log": {"columns": [
                {"name": "id", "type": "integer", "nullable": "NO", "default": None},
            ]},
        })
        result = diff_db_config(initial, final)

        assert result["has_changes"] is True
        assert "audit_log" in result["tables_added"]
        assert result["tables_removed"] == []


class TestNoChanges:
    def test_identical_inputs(self):
        state = _make_state(
            tables={"users": {"columns": [
                {"name": "id", "type": "uuid", "nullable": "NO", "default": None},
            ]}},
            indexes=[
                {"name": "users_pkey", "table": "users", "definition": "CREATE UNIQUE INDEX ..."},
            ],
            settings={"statement_timeout": "0", "max_connections": "100"},
        )
        result = diff_db_config(state, state)

        assert result["has_changes"] is False
        assert result["settings_changed"] == []
        assert result["indexes_added"] == []
        assert result["indexes_removed"] == []
        assert result["tables_added"] == []
        assert result["tables_removed"] == []
        assert result["columns_added"] == []
        assert result["columns_removed"] == []


class TestErrorHandling:
    def test_none_initial(self):
        result = diff_db_config(None, _make_state())
        assert result["has_changes"] is False

    def test_none_final(self):
        result = diff_db_config(_make_state(), None)
        assert result["has_changes"] is False

    def test_both_none(self):
        result = diff_db_config(None, None)
        assert result["has_changes"] is False

    def test_initial_has_error(self):
        result = diff_db_config({"error": "connection refused"}, _make_state())
        assert result["has_changes"] is False

    def test_final_has_error(self):
        result = diff_db_config(_make_state(), {"error": "timeout"})
        assert result["has_changes"] is False

    def test_empty_dicts(self):
        result = diff_db_config({}, {})
        assert result["has_changes"] is False
