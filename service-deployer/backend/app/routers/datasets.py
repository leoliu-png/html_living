"""Dataset endpoints: attach CSV/JSON files to a page and query them at runtime."""

from __future__ import annotations

import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_context import actor_can_manage_page, get_request_actor, parse_email_list
from app.config import settings
from app.database import get_db
from app.models import PageAsset, PageDataset
from app.schemas import ApiResponse, PageDatasetListResponse, PageDatasetResponse
from app.services import datasets as dataset_service
from app.services.settings import get_submitter_allowlist_value
from app.services.sharing import data_token_actor, require_owner, require_view, viewer_data_token
from app.services.storage import StorageNotConfiguredError, StorageObjectNotFoundError

router = APIRouter(tags=["datasets"])
DbSession = Annotated[Session, Depends(get_db)]

DataTokenQuery = Query(default=None, description="Page data token")
SelectQuery = Query(default=None, alias="select")
WhereQuery = Query(default=None, description="Filter: column:op:value (repeatable)")
SortQuery = Query(default=None)
OrderQuery = Query(default="asc")
LimitQuery = Query(default=None, ge=0)
OffsetQuery = Query(default=0, ge=0)
FormatQuery = Query(default="json", description="json | rows | csv")

CORS_HEADERS = {
    # Published pages run under `CSP: sandbox` (opaque origin), so even
    # same-path fetches arrive as cross-origin requests with `Origin: null`.
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Accept, Content-Type",
    "Access-Control-Max-Age": "600",
    "Cache-Control": "no-store",
}

USAGE_HINT = (
    "In your page HTML call `const rows = await PageData.load('<name>')`, or "
    "`await PageData.query('<name>', { where: { column: value }, sort: 'column', "
    "order: 'desc', limit: 100 })` for server-side filtering."
)


def _data_endpoint(page: PageAsset) -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/p/{page.owner}/{page.slug}/data"


def _to_response(page: PageAsset, dataset: PageDataset) -> PageDatasetResponse:
    return PageDatasetResponse(
        id=dataset.id,
        page_id=dataset.page_id,
        name=dataset.name,
        filename=dataset.filename,
        format=dataset.format,
        size_bytes=dataset.size_bytes,
        row_count=dataset.row_count,
        columns=list(dataset.columns or []),
        data_url=f"{_data_endpoint(page)}/{dataset.name}",
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _load_manageable_page(request: Request, db: Session, page_id: str) -> PageAsset:
    actor = get_request_actor(request, db)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    require_view(db, actor, page)
    if page.visibility != "org":
        require_owner(db, actor, page)
    allowlist = parse_email_list(get_submitter_allowlist_value(db))
    if not actor_can_manage_page(
        actor,
        page.submitter,
        page.user_id,
        page.user_email,
        allowlist=allowlist,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage datasets on pages you own or unassigned pages.",
        )
    return page


@router.get(
    "/api/pages/{page_id}/datasets",
    response_model=ApiResponse[PageDatasetListResponse],
)
def list_page_datasets(
    page_id: str,
    request: Request,
    db: DbSession,
) -> ApiResponse[PageDatasetListResponse]:
    page = _load_manageable_page(request, db, page_id)
    items = dataset_service.list_datasets(db, page.id)
    return ApiResponse(
        data=PageDatasetListResponse(
            items=[_to_response(page, item) for item in items],
            data_endpoint=_data_endpoint(page),
            data_token=viewer_data_token(db, get_request_actor(request, db), page),
            usage=USAGE_HINT,
        )
    )


@router.post(
    "/api/pages/{page_id}/datasets",
    response_model=ApiResponse[PageDatasetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_page_dataset(
    page_id: str,
    request: Request,
    db: DbSession,
    file: UploadFile,
    name: Annotated[Optional[str], Form()] = None,
    format: Annotated[Optional[str], Form()] = None,
) -> ApiResponse[PageDatasetResponse]:
    page = _load_manageable_page(request, db, page_id)
    filename = file.filename or "data.csv"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    # Mirrors the image upload endpoint, which answers 413 for oversized files.
    if len(contents) > dataset_service.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {dataset_service.MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    try:
        dataset_name = (
            dataset_service.normalize_dataset_name(name)
            if name
            else dataset_service.dataset_name_from_filename(filename)
        )
        dataset = dataset_service.save_dataset(
            db,
            page=page,
            name=dataset_name,
            filename=filename,
            contents=contents,
            declared_format=format,
        )
    except dataset_service.DatasetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage is not configured: {exc}",
        ) from exc

    return ApiResponse(msg="dataset saved", data=_to_response(page, dataset))


@router.delete(
    "/api/pages/{page_id}/datasets/{dataset_id}",
    response_model=ApiResponse[dict],
)
def delete_page_dataset(
    page_id: str,
    dataset_id: str,
    request: Request,
    db: DbSession,
) -> ApiResponse[dict]:
    page = _load_manageable_page(request, db, page_id)
    try:
        dataset = dataset_service.get_dataset(db, page.id, dataset_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    dataset_service.delete_dataset(db, dataset)
    return ApiResponse(msg="dataset deleted", data={"id": dataset_id})


@router.options("/p/{owner}/{slug}/data/{name}")
def dataset_preflight(owner: str, slug: str, name: str) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(CORS_HEADERS))


@router.get("/p/{owner}/{slug}/data/{name}")
def read_page_dataset(
    owner: str,
    slug: str,
    name: str,
    request: Request,
    db: DbSession,
    k: Optional[str] = DataTokenQuery,
    select_columns: Optional[str] = SelectQuery,
    where: Optional[list[str]] = WhereQuery,
    sort: Optional[str] = SortQuery,
    order: str = OrderQuery,
    limit: Optional[int] = LimitQuery,
    offset: int = OffsetQuery,
    format: str = FormatQuery,
) -> Response:
    page = db.scalar(select(PageAsset).where(PageAsset.owner == owner, PageAsset.slug == slug))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    actor = get_request_actor(request, db)
    if actor is None:
        actor = data_token_actor(db, k, page)
    # Compatibility for already open, legacy org pages only. Restricted data
    # always uses a signed viewer credential and rechecks grants on every read.
    legacy_org_token = bool(
        page.visibility == "org" and k and page.data_token and k == page.data_token
    )
    if actor is not None:
        require_view(db, actor, page)
    elif not legacy_org_token:
        raise HTTPException(401, "Dataset access requires an authorized viewer.")

    try:
        dataset = dataset_service.get_dataset_by_name(db, page.id, name)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        query = dataset_service.build_query(
            select_columns=select_columns.split(",") if select_columns else None,
            filters=where,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        parsed = dataset_service.load_rows(dataset)
        result = dataset_service.run_query(parsed, query)
    except dataset_service.DatasetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageObjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset file is missing from storage.",
        ) from exc
    except StorageNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage is not configured: {exc}",
        ) from exc

    output = (format or "json").strip().lower()
    if output == "csv":
        body = dataset_service.rows_to_csv(result.rows, result.columns)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers=dict(CORS_HEADERS),
        )
    if output == "rows":
        payload: object = result.rows
    elif output == "json":
        payload = {
            "name": dataset.name,
            "format": dataset.format,
            "columns": result.columns,
            "total": result.total,
            "matched": result.matched,
            "count": len(result.rows),
            "offset": query.offset,
            "limit": query.limit,
            "rows": result.rows,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported format. Use json, rows, or csv.",
        )

    return Response(
        content=json.dumps(payload, ensure_ascii=False, default=str),
        media_type="application/json; charset=utf-8",
        headers=dict(CORS_HEADERS),
    )
