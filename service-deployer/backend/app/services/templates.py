from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
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


def _execute_readonly_query(db: Session, query: str) -> list[dict[str, Any]]:
    stripped = query.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        raise DataSourceError("Only SELECT queries are allowed in data_sources.")
    if "LIMIT" not in stripped.upper():
        wrapped = f"({stripped}) LIMIT {_MAX_RESULT_ROWS}"
    else:
        wrapped = stripped
    try:
        result = db.execute(text(wrapped))
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as exc:
        raise DataSourceError(f"Query execution failed: {exc}") from exc


def render_template(html: str, data_sources: dict[str, str], db: Session) -> str:
    if data_sources and not settings.allow_legacy_sql_data_sources:
        raise DataSourceError(
            "Legacy SQL data_sources are disabled. Use uploaded page datasets instead."
        )
    results: dict[str, list[dict[str, Any]]] = {}
    for name, query in data_sources.items():
        results[name] = _execute_readonly_query(db, query)

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
