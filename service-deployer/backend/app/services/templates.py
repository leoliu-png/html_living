from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings

_MAX_RESULT_ROWS = 500

_VAR_PATTERN = re.compile(r"\{\{\s*\.(\w+)(?:\.(\w+))?\s*\}\}")
_LOOP_PATTERN = re.compile(
    r"\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}",
    re.DOTALL,
)


class DataSourceError(ValueError):
    pass


def legacy_sql_mode() -> str:
    """`unsafe` (app privileges, explicit opt-in), `sandbox` or `disabled`."""
    if settings.allow_legacy_sql_data_sources:
        return "unsafe"
    if settings.legacy_sql_database_url:
        return "sandbox"
    return "disabled"


@lru_cache(maxsize=4)
def _sandbox_engine(url: str):
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


def _prepare_query(query: str) -> str:
    stripped = query.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        raise DataSourceError("Only SELECT queries are allowed in data_sources.")
    if "LIMIT" not in stripped.upper():
        return f"({stripped}) LIMIT {_MAX_RESULT_ROWS}"
    return stripped


def _rows(result) -> list[dict[str, Any]]:
    columns = list(result.keys())
    return [dict(zip(columns, row)) for row in result.fetchmany(_MAX_RESULT_ROWS)]


def _execute_readonly_query(db: Session, query: str) -> list[dict[str, Any]]:
    wrapped = _prepare_query(query)
    try:
        return _rows(db.execute(text(wrapped)))
    except Exception as exc:
        raise DataSourceError(f"Query execution failed: {exc}") from exc


def _execute_sandboxed_query(query: str) -> list[dict[str, Any]]:
    """Run one legacy query as the restricted login role, in its own read-only
    transaction. Privileges come from the login role itself, so `SET ROLE` /
    `set_config('role', ...)` cannot climb back to the application role."""

    wrapped = _prepare_query(query)
    timeout = max(100, int(settings.legacy_sql_statement_timeout_ms))
    try:
        with _sandbox_engine(settings.legacy_sql_database_url).connect() as connection:
            with connection.begin() as transaction:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text(f"SET LOCAL statement_timeout = {timeout}"))
                # Unqualified `page_assets` resolves to the filtered view.
                connection.execute(text("SET LOCAL search_path TO legacy_sql"))
                rows = _rows(connection.execute(text(wrapped)))
                transaction.rollback()
                return rows
    except Exception as exc:
        raise DataSourceError(f"Query execution failed: {exc}") from exc


def render_template(html: str, data_sources: dict[str, str], db: Session) -> str:
    mode = legacy_sql_mode()
    if data_sources and mode == "disabled":
        raise DataSourceError(
            "Legacy SQL data_sources are disabled. Use uploaded page datasets instead."
        )
    results: dict[str, list[dict[str, Any]]] = {}
    for name, query in data_sources.items():
        results[name] = (
            _execute_sandboxed_query(query)
            if mode == "sandbox"
            else _execute_readonly_query(db, query)
        )

    def replace_loop(match: re.Match) -> str:
        row_var = match.group(1)
        source_name = match.group(2)
        template = match.group(3)
        rows = results.get(source_name, [])
        parts: list[str] = []
        for row in rows:
            part = template
            for key, value in row.items():
                val_str = _format_value(value)
                part = part.replace(r"{{" + f" .{row_var}.{key} " + r"}}", val_str)
            parts.append(part)
        return "".join(parts)

    html = _LOOP_PATTERN.sub(replace_loop, html)

    def replace_var(match: re.Match) -> str:
        source_name = match.group(1)
        field = match.group(2)
        rows = results.get(source_name, [])
        if not rows:
            return ""
        row = rows[0]
        if field:
            val = row.get(field)
            return _format_value(val)
        return json.dumps(row, ensure_ascii=False, default=str)

    html = _VAR_PATTERN.sub(replace_var, html)
    return html


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
