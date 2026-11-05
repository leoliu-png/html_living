"""Page datasets: upload CSV/JSON data files and query them from a page.

A dataset is a tabular data file attached to a published page. The raw bytes
live in R2, the metadata lives in `page_datasets`, and the rows are served (and
optionally filtered) through `/p/{owner}/{slug}/data/{name}`.
"""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import PageAsset, PageDataset
from app.services import storage

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
MAX_QUERY_ROWS = 50_000
DEFAULT_QUERY_LIMIT = 5_000
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")

FORMAT_BY_EXTENSION = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".ndjson": "ndjson",
    ".jsonl": "ndjson",
}

CONTENT_TYPE_BY_FORMAT = {
    "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "ndjson": "application/x-ndjson; charset=utf-8",
}

COMPARISON_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "startswith",
    "endswith",
    "in",
    "nin",
    "empty",
    "notempty",
}


class DatasetError(ValueError):
    """Bad dataset input (unsupported format, invalid name, malformed query)."""


class DatasetNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ParsedDataset:
    format: str
    columns: list[str]
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class DatasetQuery:
    select: Optional[list[str]] = None
    filters: list[tuple[str, str, str]] = field(default_factory=list)
    sort: Optional[str] = None
    order: str = "asc"
    limit: int = DEFAULT_QUERY_LIMIT
    offset: int = 0


@dataclass(frozen=True)
class DatasetQueryResult:
    rows: list[dict[str, Any]]
    total: int
    matched: int
    columns: list[str]


def normalize_dataset_name(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9_-]", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_")
    if not NAME_PATTERN.fullmatch(normalized):
        raise DatasetError(
            "Dataset name must use lowercase letters, numbers, hyphens, or underscores."
        )
    return normalized


def dataset_name_from_filename(filename: str) -> str:
    stem = Path(filename).stem or "data"
    return normalize_dataset_name(stem)


def detect_format(filename: str, declared: Optional[str] = None) -> str:
    if declared:
        fmt = declared.strip().lower()
        if fmt in {"jsonl"}:
            return "ndjson"
        if fmt not in CONTENT_TYPE_BY_FORMAT:
            raise DatasetError(
                f"Unsupported dataset format: {declared}. "
                f"Allowed: {', '.join(sorted(set(FORMAT_BY_EXTENSION.values())))}"
            )
        return fmt
    ext = Path(filename).suffix.lower()
    if ext not in FORMAT_BY_EXTENSION:
        raise DatasetError(
            f"Unsupported dataset file type: {ext or '(none)'}. "
            f"Allowed: {', '.join(sorted(FORMAT_BY_EXTENSION))}"
        )
    return FORMAT_BY_EXTENSION[ext]


def _decode(contents: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return contents.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DatasetError("Unable to decode file: expected UTF-8 text.")


def _coerce_scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _parse_delimited(text: str, delimiter: str) -> ParsedDataset:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = [name.strip() for name in (reader.fieldnames or []) if name is not None]
    if not columns:
        raise DatasetError("File has no header row.")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        if len(rows) >= MAX_ROWS:
            raise DatasetError(f"Too many rows (max {MAX_ROWS}).")
        row = {}
        for key, value in raw.items():
            if key is None:
                continue
            row[key.strip()] = value
        rows.append(row)
    return ParsedDataset(format="csv" if delimiter == "," else "tsv", columns=columns, rows=rows)


def _rows_from_json(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "records", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    raise DatasetError("JSON dataset must be an array of objects.")


def _parse_json_rows(raw_rows: list[Any]) -> ParsedDataset:
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    seen: set[str] = set()
    for item in raw_rows:
        if len(rows) >= MAX_ROWS:
            raise DatasetError(f"Too many rows (max {MAX_ROWS}).")
        if not isinstance(item, dict):
            item = {"value": item}
        row = {key: _coerce_scalar(value) for key, value in item.items()}
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
        rows.append(row)
    return ParsedDataset(format="json", columns=columns, rows=rows)


def parse_dataset(contents: bytes, fmt: str) -> ParsedDataset:
    if len(contents) > MAX_UPLOAD_BYTES:
        raise DatasetError(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    text = _decode(contents)
    if fmt == "csv":
        return _parse_delimited(text, ",")
    if fmt == "tsv":
        return _parse_delimited(text, "\t")
    if fmt == "json":
        try:
            payload = json.loads(text or "[]")
        except json.JSONDecodeError as exc:
            raise DatasetError(f"Invalid JSON: {exc.msg} (line {exc.lineno}).") from exc
        parsed = _parse_json_rows(_rows_from_json(payload))
        return ParsedDataset(format="json", columns=parsed.columns, rows=parsed.rows)
    if fmt == "ndjson":
        raw_rows: list[Any] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw_rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise DatasetError(f"Invalid NDJSON on line {lineno}: {exc.msg}.") from exc
        parsed = _parse_json_rows(raw_rows)
        return ParsedDataset(format="ndjson", columns=parsed.columns, rows=parsed.rows)
    raise DatasetError(f"Unsupported dataset format: {fmt}")


def build_storage_key(page_id: str, name: str, fmt: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(4)
    extension = "ndjson" if fmt == "ndjson" else fmt
    return f"datasets/{page_id}/{name}-{stamp}{suffix}.{extension}"


def ensure_page_data_token(db: Session, page: PageAsset) -> str:
    """Return the page's data token, creating it once even under concurrency.

    Two simultaneous first renders of the same page must not generate two
    tokens: the loser's HTML would carry a token the database no longer holds,
    and every data request from that page would 401. The conditional UPDATE
    lets exactly one writer win, then both re-read the stored value.
    """

    if page.data_token:
        return page.data_token
    db.execute(
        update(PageAsset)
        .where(PageAsset.id == page.id, PageAsset.data_token.is_(None))
        .values(data_token=secrets.token_urlsafe(24))
    )
    db.commit()
    db.refresh(page)
    return page.data_token


def list_datasets(db: Session, page_id: str) -> list[PageDataset]:
    return list(
        db.scalars(
            select(PageDataset)
            .where(PageDataset.page_id == page_id)
            .order_by(PageDataset.name.asc())
        )
    )


def get_dataset_by_name(db: Session, page_id: str, name: str) -> PageDataset:
    dataset = db.scalar(
        select(PageDataset).where(PageDataset.page_id == page_id, PageDataset.name == name)
    )
    if dataset is None:
        raise DatasetNotFoundError("Dataset not found.")
    return dataset


def get_dataset(db: Session, page_id: str, dataset_id: str) -> PageDataset:
    dataset = db.scalar(
        select(PageDataset).where(PageDataset.page_id == page_id, PageDataset.id == dataset_id)
    )
    if dataset is None:
        raise DatasetNotFoundError("Dataset not found.")
    return dataset


def save_dataset(
    db: Session,
    *,
    page: PageAsset,
    name: str,
    filename: str,
    contents: bytes,
    declared_format: Optional[str] = None,
) -> PageDataset:
    """Create or replace the dataset called `name` on `page`."""

    dataset_name = normalize_dataset_name(name)
    fmt = detect_format(filename, declared_format)
    parsed = parse_dataset(contents, fmt)

    storage_key = build_storage_key(page.id, dataset_name, fmt)
    storage.put_object(storage_key, contents, CONTENT_TYPE_BY_FORMAT[fmt])

    existing = db.scalar(
        select(PageDataset).where(
            PageDataset.page_id == page.id, PageDataset.name == dataset_name
        )
    )
    previous_key = existing.storage_key if existing else None

    if existing is None:
        existing = PageDataset(page_id=page.id, name=dataset_name)
        db.add(existing)

    existing.filename = filename[:255]
    existing.format = fmt
    existing.content_type = CONTENT_TYPE_BY_FORMAT[fmt]
    existing.storage_key = storage_key
    existing.size_bytes = len(contents)
    existing.row_count = len(parsed.rows)
    existing.columns = parsed.columns
    db.commit()
    db.refresh(existing)

    _cache_put(storage_key, parsed)
    if previous_key and previous_key != storage_key:
        storage.delete_object(previous_key)
        _cache_drop(previous_key)
    ensure_page_data_token(db, page)
    return existing


def delete_dataset(db: Session, dataset: PageDataset) -> None:
    storage_key = dataset.storage_key
    db.delete(dataset)
    db.commit()
    storage.delete_object(storage_key)
    _cache_drop(storage_key)


# --- parsed-row cache -------------------------------------------------------
# Datasets are immutable per storage key, so a small process-local cache avoids
# re-downloading and re-parsing R2 objects on every dashboard request.
# Sync routes run in Starlette's threadpool, so every mutation takes the lock:
# without it, a read populating the cache while an upload evicts an entry can
# raise "dictionary changed size during iteration".

_CACHE_MAX_ROWS = 300_000
_cache: dict[str, ParsedDataset] = {}
_cache_order: list[str] = []
_cache_lock = threading.RLock()


def _cache_put(key: str, parsed: ParsedDataset) -> None:
    with _cache_lock:
        _cache[key] = parsed
        if key in _cache_order:
            _cache_order.remove(key)
        _cache_order.append(key)
        total = sum(len(item.rows) for item in _cache.values())
        while _cache_order and total > _CACHE_MAX_ROWS and len(_cache_order) > 1:
            oldest = _cache_order.pop(0)
            dropped = _cache.pop(oldest, None)
            if dropped is not None:
                total -= len(dropped.rows)


def _cache_drop(key: str) -> None:
    with _cache_lock:
        _cache.pop(key, None)
        if key in _cache_order:
            _cache_order.remove(key)


def clear_dataset_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _cache_order.clear()


def load_rows(dataset: PageDataset) -> ParsedDataset:
    with _cache_lock:
        cached = _cache.get(dataset.storage_key)
    if cached is not None:
        return cached
    # Fetch and parse outside the lock so one slow download cannot stall every
    # other dataset request in the worker.
    contents = storage.get_object(dataset.storage_key)
    parsed = parse_dataset(contents, dataset.format)
    _cache_put(dataset.storage_key, parsed)
    return parsed


# --- query engine -----------------------------------------------------------


def parse_filter_expression(expression: str) -> tuple[str, str, str]:
    """Parse `column:op:value` (op optional, defaults to `eq`)."""

    parts = expression.split(":", 2)
    if len(parts) == 1:
        raise DatasetError(
            f"Invalid filter '{expression}'. Use column:op:value, e.g. country:eq:US."
        )
    column = parts[0].strip()
    if not column:
        raise DatasetError("Filter is missing a column name.")
    if len(parts) == 2:
        candidate = parts[1].strip().lower()
        if candidate in {"empty", "notempty"}:
            return column, candidate, ""
        return column, "eq", parts[1]
    operator = parts[1].strip().lower() or "eq"
    if operator not in COMPARISON_OPERATORS:
        raise DatasetError(
            f"Unsupported filter operator '{operator}'. "
            f"Allowed: {', '.join(sorted(COMPARISON_OPERATORS))}"
        )
    return column, operator, parts[2]


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _compare(left: Any, right: str, operator: str) -> bool:
    left_number = _as_number(left)
    right_number = _as_number(right)
    if left_number is not None and right_number is not None:
        if operator == "gt":
            return left_number > right_number
        if operator == "gte":
            return left_number >= right_number
        if operator == "lt":
            return left_number < right_number
        if operator == "lte":
            return left_number <= right_number
    left_text = "" if left is None else str(left)
    if operator == "gt":
        return left_text > right
    if operator == "gte":
        return left_text >= right
    if operator == "lt":
        return left_text < right
    return left_text <= right


def row_matches(row: dict[str, Any], column: str, operator: str, value: str) -> bool:
    cell = row.get(column)
    cell_text = "" if cell is None else str(cell)
    if operator == "empty":
        return cell_text.strip() == ""
    if operator == "notempty":
        return cell_text.strip() != ""
    if operator in {"eq", "ne"}:
        cell_number = _as_number(cell)
        value_number = _as_number(value)
        if cell_number is not None and value_number is not None:
            equal = cell_number == value_number
        else:
            equal = cell_text.casefold() == value.casefold()
        return equal if operator == "eq" else not equal
    if operator == "contains":
        return value.casefold() in cell_text.casefold()
    if operator == "startswith":
        return cell_text.casefold().startswith(value.casefold())
    if operator == "endswith":
        return cell_text.casefold().endswith(value.casefold())
    if operator in {"in", "nin"}:
        options = {item.strip().casefold() for item in value.split(",") if item.strip()}
        contained = cell_text.casefold() in options
        return contained if operator == "in" else not contained
    return _compare(cell, value, operator)


def _sort_key(value: Any) -> tuple[int, float, str]:
    number = _as_number(value)
    if number is not None:
        return (0, number, "")
    text = "" if value is None else str(value)
    return (1, 0.0, text.casefold())


def build_query(
    *,
    select_columns: Optional[list[str]] = None,
    filters: Optional[list[str]] = None,
    sort: Optional[str] = None,
    order: str = "asc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> DatasetQuery:
    parsed_filters = [parse_filter_expression(item) for item in (filters or []) if item.strip()]
    normalized_order = (order or "asc").strip().lower()
    if normalized_order not in {"asc", "desc"}:
        raise DatasetError("Order must be 'asc' or 'desc'.")
    resolved_limit = DEFAULT_QUERY_LIMIT if limit is None else int(limit)
    if resolved_limit < 0:
        raise DatasetError("Limit cannot be negative.")
    resolved_limit = min(resolved_limit, MAX_QUERY_ROWS)
    if offset < 0:
        raise DatasetError("Offset cannot be negative.")
    columns: Optional[list[str]] = None
    if select_columns:
        columns = [item.strip() for item in select_columns if item.strip()]
        columns = columns or None
    return DatasetQuery(
        select=columns,
        filters=parsed_filters,
        sort=(sort or "").strip() or None,
        order=normalized_order,
        limit=resolved_limit,
        offset=offset,
    )


def run_query(parsed: ParsedDataset, query: DatasetQuery) -> DatasetQueryResult:
    known_columns = parsed.columns
    for column, _, _ in query.filters:
        if known_columns and column not in known_columns:
            raise DatasetError(
                f"Unknown column '{column}'. Available: {', '.join(known_columns)}"
            )
    if query.sort and known_columns and query.sort not in known_columns:
        raise DatasetError(
            f"Unknown sort column '{query.sort}'. Available: {', '.join(known_columns)}"
        )
    if query.select:
        for column in query.select:
            if known_columns and column not in known_columns:
                raise DatasetError(
                    f"Unknown column '{column}'. Available: {', '.join(known_columns)}"
                )

    rows = parsed.rows
    for column, operator, value in query.filters:
        rows = [row for row in rows if row_matches(row, column, operator, value)]
    matched = len(rows)

    if query.sort:
        rows = sorted(
            rows,
            key=lambda row: _sort_key(row.get(query.sort)),
            reverse=query.order == "desc",
        )

    window = rows[query.offset : query.offset + query.limit] if query.limit else []
    if query.select:
        window = [{column: row.get(column) for column in query.select} for row in window]
        columns = list(query.select)
    else:
        columns = list(known_columns)

    return DatasetQueryResult(
        rows=window,
        total=len(parsed.rows),
        matched=matched,
        columns=columns,
    )


def rows_to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _csv_cell(row.get(column)) for column in columns})
    return buffer.getvalue()


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
