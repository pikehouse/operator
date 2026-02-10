"""Structured diff between two pg_state snapshots (initial vs final).

Returns a dict describing what changed in PostgreSQL config during a trial:
settings changed, indexes added/removed, tables/columns added/removed.
"""

from __future__ import annotations

from typing import Any


def diff_db_config(
    initial: dict[str, Any] | None,
    final: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute structured diff between two db_config snapshots.

    Handles None/error inputs gracefully (returns has_changes: False).
    """
    empty = {
        "settings_changed": [],
        "indexes_added": [],
        "indexes_removed": [],
        "tables_added": [],
        "tables_removed": [],
        "columns_added": [],
        "columns_removed": [],
        "has_changes": False,
    }

    # Graceful degradation for missing/error data
    if not initial or not final:
        return empty
    if "error" in initial or "error" in final:
        return empty

    result: dict[str, Any] = {
        "settings_changed": _diff_settings(
            initial.get("settings", {}),
            final.get("settings", {}),
        ),
        "indexes_added": _diff_indexes_added(
            initial.get("indexes", []),
            final.get("indexes", []),
        ),
        "indexes_removed": _diff_indexes_added(
            final.get("indexes", []),
            initial.get("indexes", []),
        ),
        "tables_added": _diff_tables(
            initial.get("tables", {}),
            final.get("tables", {}),
        ),
        "tables_removed": _diff_tables(
            final.get("tables", {}),
            initial.get("tables", {}),
        ),
        "columns_added": _diff_columns(
            initial.get("tables", {}),
            final.get("tables", {}),
        ),
        "columns_removed": _diff_columns(
            final.get("tables", {}),
            initial.get("tables", {}),
        ),
    }

    result["has_changes"] = any(
        bool(v) for k, v in result.items() if k != "has_changes"
    )

    return result


def _diff_settings(
    initial: dict[str, str],
    final: dict[str, str],
) -> list[dict[str, str]]:
    """Return settings whose values changed between snapshots."""
    changed = []
    all_keys = set(initial) | set(final)
    for key in sorted(all_keys):
        before = initial.get(key)
        after = final.get(key)
        if before != after:
            changed.append({"name": key, "before": before or "", "after": after or ""})
    return changed


def _diff_indexes_added(
    old: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return indexes present in *new* but not in *old* (by name)."""
    old_names = {idx["name"] for idx in old}
    return [
        {"name": idx["name"], "table": idx["table"], "definition": idx["definition"]}
        for idx in new
        if idx["name"] not in old_names
    ]


def _diff_tables(
    old_tables: dict[str, Any],
    new_tables: dict[str, Any],
) -> list[str]:
    """Return table names present in new_tables but not in old_tables."""
    return sorted(set(new_tables) - set(old_tables))


def _diff_columns(
    old_tables: dict[str, Any],
    new_tables: dict[str, Any],
) -> list[dict[str, str]]:
    """Return columns present in new_tables but not in old_tables (for shared tables)."""
    added = []
    shared = set(old_tables) & set(new_tables)
    for table in sorted(shared):
        old_cols = {c["name"] for c in old_tables[table].get("columns", [])}
        for col in new_tables[table].get("columns", []):
            if col["name"] not in old_cols:
                added.append({
                    "table": table,
                    "name": col["name"],
                    "type": col["type"],
                })
    return added
