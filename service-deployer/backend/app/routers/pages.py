from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.params import Query as QueryParam
from markdownify import markdownify as html_to_markdown
from sqlalchemy import and_, desc, distinct, func, not_, or_, select
from sqlalchemy.orm import Session

from app.auth_context import (
    actor_can_manage_page,
    get_request_actor,
    is_assigned_page_identity,
    is_real_user_email,
    is_unassigned_page,
    parse_email_list,
)
from app.config import settings
from app.database import get_db
from app.models import PageAsset
from app.schemas import (
    ApiResponse,
    CountByOwnerResponse,
    CountBySubmitterResponse,
    PageAssetResponse,
    PageDetailResponse,
    PageIdentityFilterResponse,
    PageListResponse,
    PagePublishRequest,
    PagePublishResponse,
    PageStatsResponse,
    PageUpdateRequest,
    PaginationResponse,
)
from app.services.datasets import list_datasets
from app.services.page_data_runtime import build_page_data_runtime, inject_page_data_runtime
from app.services.pages import (
    InvalidOwnerError,
    InvalidSlugError,
    NoFieldsToUpdateError,
    PageNotFoundError,
    PublishHtmlPageInput,
    SlugConflictError,
    SubmissionContext,
    build_public_page_url,
    claim_page,
    delete_page,
    detect_device,
    publish_html_page,
    update_html_page,
)
from app.services.settings import get_submitter_allowlist_value
from app.services.sharing import (
    audit_admin_read,
    audit_claim,
    discovery_filter,
    publish_sharing,
    require_owner,
    require_view,
    set_sharing,
    validate_grants,
    viewer_data_token,
    visible_sharing,
)
from app.services.templates import DataSourceError, legacy_sql_mode, render_template

router = APIRouter(tags=["pages"])
DbSession = Annotated[Session, Depends(get_db)]
CreatedRange = Literal["all", "24h", "7d", "30d"]
CreatedRangeQuery = Query(default="all")


def get_client_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def to_page_asset_response(
    page: PageAsset,
    *,
    allowlist: set[str],
    db: Optional[Session] = None,
    actor=None,
) -> PageAssetResponse:
    # Grant lists (who else can see the page) are only returned to owners/admins.
    return PageAssetResponse(
        **(
            visible_sharing(db, actor, page).model_dump()
            if db is not None
            else {"visibility": page.visibility, "listed": page.listed}
        ),
        id=page.id,
        owner=page.owner,
        slug=page.slug,
        url=build_public_page_url(settings.public_base_url, page.owner, page.slug),
        title=page.title,
        submitter=page.submitter,
        description=page.description,
        submit_ip=page.submit_ip,
        submit_device=page.submit_device,
        submit_user_agent=page.submit_user_agent,
        user_id=page.user_id,
        user_email=page.user_email,
        data_sources=page.data_sources,
        is_unassigned=is_unassigned_page(
            page.submitter,
            page.user_id,
            page.user_email,
            allowlist=allowlist,
        ),
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def to_page_detail_response(
    page: PageAsset,
    *,
    allowlist: set[str],
    db: Optional[Session] = None,
    actor=None,
) -> PageDetailResponse:
    data = to_page_asset_response(page, allowlist=allowlist, db=db, actor=actor).model_dump()
    return PageDetailResponse(**data, html=page.html)


def build_copy_source_toolbar(*, html: str, markdown: str) -> str:
    html_json = json.dumps(html).replace("</", "<\\/")
    markdown_json = json.dumps(markdown).replace("</", "<\\/")
    return f"""
<script>
window.__feedmobPageSource = {{
  html: {html_json},
  markdown: {markdown_json}
}};
</script>
<div id="feedmob-source-toolbar" data-feedmob-toolbar data-open="false">
  <div data-copy-split-button>
    <button
      type="button"
      data-copy-drag-handle
      aria-label="Drag copy toolbar"
      title="Drag to move"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" focusable="false">
        <circle cx="5.5" cy="4.5" r="1.15"></circle>
        <circle cx="10.5" cy="4.5" r="1.15"></circle>
        <circle cx="5.5" cy="8" r="1.15"></circle>
        <circle cx="10.5" cy="8" r="1.15"></circle>
        <circle cx="5.5" cy="11.5" r="1.15"></circle>
        <circle cx="10.5" cy="11.5" r="1.15"></circle>
      </svg>
    </button>
    <button type="button" data-copy-source="markdown">
      Copy page
    </button>
    <button
      type="button"
      data-copy-menu-toggle
      aria-expanded="false"
      aria-label="More copy options"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" focusable="false">
        <path d="M4.5 6.25 8 9.75l3.5-3.5" />
      </svg>
    </button>
  </div>
  <div data-copy-menu role="menu">
    <button type="button" data-copy-source="html" role="menuitem">Copy HTML</button>
  </div>
  <div data-copy-status aria-live="polite"></div>
</div>
<style>
#feedmob-source-toolbar {{
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 2147483647;
  display: inline-flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 6px;
  color: #172026;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
}}
#feedmob-source-toolbar[data-dragging="true"] {{
  cursor: grabbing;
}}
#feedmob-source-toolbar [data-copy-split-button] {{
  display: inline-flex;
  height: 34px;
  border: 1px solid rgba(15, 23, 42, 0.14);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(10px);
  overflow: hidden;
}}
#feedmob-source-toolbar button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  color: #4b5563;
  border: 0;
  background: transparent;
  box-shadow: none;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}}
#feedmob-source-toolbar button:hover {{
  background: rgba(15, 23, 42, 0.05);
}}
#feedmob-source-toolbar [data-copy-drag-handle] {{
  width: 28px;
  padding: 0;
  color: #94a3b8;
  cursor: grab;
  line-height: 0;
  border-right: 1px solid rgba(15, 23, 42, 0.12);
}}
#feedmob-source-toolbar[data-dragging="true"] [data-copy-drag-handle] {{
  cursor: grabbing;
}}
#feedmob-source-toolbar [data-copy-drag-handle] svg {{
  display: block;
  width: 14px;
  height: 14px;
  fill: currentColor;
}}
#feedmob-source-toolbar [data-copy-source="markdown"] {{
  padding: 0 13px;
  white-space: nowrap;
}}
#feedmob-source-toolbar [data-copy-menu-toggle] {{
  width: 34px;
  padding: 0;
  border-left: 1px solid rgba(15, 23, 42, 0.12);
  color: #8a96a0;
  line-height: 0;
}}
#feedmob-source-toolbar [data-copy-menu-toggle] svg {{
  display: block;
  width: 16px;
  height: 16px;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
}}
#feedmob-source-toolbar [data-copy-menu] {{
  display: none;
  width: max-content;
  min-width: 108px;
  padding: 4px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
  box-sizing: border-box;
}}
#feedmob-source-toolbar[data-open="true"] [data-copy-menu] {{
  display: grid;
  gap: 4px;
}}
#feedmob-source-toolbar [data-copy-menu] button {{
  width: 100%;
  min-height: 30px;
  padding: 0 9px;
  justify-content: flex-start;
  text-align: left;
  border-color: transparent;
  border-radius: 8px;
  background: transparent;
  box-shadow: none;
}}
#feedmob-source-toolbar [data-copy-menu] button:hover {{
  background: rgba(15, 23, 42, 0.05);
}}
#feedmob-source-toolbar [data-copy-status] {{
  min-width: 0;
  max-width: 174px;
  min-height: 0;
  padding: 5px 8px;
  opacity: 0;
  color: #334155;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.10);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  pointer-events: none;
  transform: translateY(-2px);
  transition: opacity 120ms ease, transform 120ms ease;
}}
#feedmob-source-toolbar[data-status="true"] [data-copy-status] {{
  opacity: 1;
  transform: translateY(0);
}}
@media (max-width: 640px) {{
  #feedmob-source-toolbar {{
    right: 10px;
  }}
}}
</style>
<script>
(function () {{
  var toolbar = document.getElementById("feedmob-source-toolbar");
  var toggle = toolbar ? toolbar.querySelector("[data-copy-menu-toggle]") : null;
  var status = toolbar ? toolbar.querySelector("[data-copy-status]") : null;
  var dragHandle = toolbar ? toolbar.querySelector("[data-copy-drag-handle]") : null;
  var dragState = null;
  var DRAG_THRESHOLD = 5;

  function setOpen(open) {{
    if (!toolbar) return;
    toolbar.setAttribute("data-open", open ? "true" : "false");
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }}
  function setStatus(text) {{
    if (!status) return;
    status.textContent = text;
    toolbar.setAttribute("data-status", "true");
    window.clearTimeout(setStatus._timer);
    setStatus._timer = window.setTimeout(function () {{
      status.textContent = "";
      toolbar.setAttribute("data-status", "false");
    }}, 1600);
  }}
  function clamp(value, min, max) {{
    return Math.min(Math.max(value, min), max);
  }}
  function placeToolbar(left, top) {{
    if (!toolbar) return;
    var rect = toolbar.getBoundingClientRect();
    var maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    var maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    var nextLeft = clamp(left, 8, maxLeft);
    var nextTop = clamp(top, 8, maxTop);
    toolbar.style.left = nextLeft + "px";
    toolbar.style.top = nextTop + "px";
    toolbar.style.right = "auto";
    toolbar.style.bottom = "auto";
  }}
  function endDrag(event) {{
    if (!dragState || !toolbar) return;
    if (dragState.pointerId !== null && event && event.pointerId !== dragState.pointerId) return;
    if (dragHandle && dragState.pointerId !== null) {{
      try {{ dragHandle.releasePointerCapture(dragState.pointerId); }} catch (error) {{}}
    }}
    toolbar.setAttribute("data-dragging", "false");
    dragState = null;
  }}
  async function copySource(kind) {{
    var source = window.__feedmobPageSource && window.__feedmobPageSource[kind];
    if (typeof source !== "string") return;
    try {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        await navigator.clipboard.writeText(source);
      }} else {{
        var textArea = document.createElement("textarea");
        textArea.value = source;
        textArea.setAttribute("readonly", "");
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }}
      setStatus(kind === "html" ? "HTML copied" : "Markdown copied");
      setOpen(false);
    }} catch (error) {{
      setStatus("Copy failed");
    }}
  }}
  if (!toolbar) return;

  if (dragHandle) {{
    dragHandle.addEventListener("pointerdown", function (event) {{
      if (event.button !== undefined && event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      var rect = toolbar.getBoundingClientRect();
      dragState = {{
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originLeft: rect.left,
        originTop: rect.top,
        moved: false
      }};
      try {{ dragHandle.setPointerCapture(event.pointerId); }} catch (error) {{}}
    }});
    dragHandle.addEventListener("pointermove", function (event) {{
      if (!dragState || dragState.pointerId !== event.pointerId) return;
      var dx = event.clientX - dragState.startX;
      var dy = event.clientY - dragState.startY;
      if (!dragState.moved) {{
        if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
        dragState.moved = true;
        toolbar.setAttribute("data-dragging", "true");
      }}
      event.preventDefault();
      placeToolbar(dragState.originLeft + dx, dragState.originTop + dy);
    }});
    dragHandle.addEventListener("pointerup", endDrag);
    dragHandle.addEventListener("pointercancel", endDrag);
  }}

  toolbar.addEventListener("click", function (event) {{
    if (toolbar.getAttribute("data-dragging") === "true") {{
      event.preventDefault();
      event.stopPropagation();
      return;
    }}
    var target = event.target instanceof Element ? event.target : null;
    if (target && target.closest("[data-copy-drag-handle]")) {{
      event.preventDefault();
      event.stopPropagation();
      return;
    }}
    var toggleButton = target ? target.closest("[data-copy-menu-toggle]") : null;
    var sourceButton = target ? target.closest("[data-copy-source]") : null;
    if (toggleButton) {{
      event.stopPropagation();
      event.preventDefault();
      setOpen(toolbar.getAttribute("data-open") !== "true");
      return;
    }}
    if (!(sourceButton instanceof HTMLElement)) return;
    var kind = sourceButton.getAttribute("data-copy-source");
    if (kind === "html" || kind === "markdown") {{
      event.stopPropagation();
      event.preventDefault();
      copySource(kind);
    }}
  }});
  document.addEventListener("click", function (event) {{
    if (event.target instanceof Node && !toolbar.contains(event.target)) setOpen(false);
  }});
  window.addEventListener("resize", function () {{
    if (!toolbar || !toolbar.style.left) return;
    var rect = toolbar.getBoundingClientRect();
    placeToolbar(rect.left, rect.top);
  }});
}})();
</script>
"""


def convert_html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return html_to_markdown(
        str(soup),
        heading_style="ATX",
        bullets="-",
    ).strip()


def attach_page_datasets(html: str, page: PageAsset, db: Session, actor) -> str:
    """Expose the page's uploaded datasets to its own JavaScript via `PageData`."""

    datasets = list_datasets(db, page.id)
    if not datasets:
        return html
    token = viewer_data_token(db, actor, page)
    manifest = [
        {
            "name": dataset.name,
            "filename": dataset.filename,
            "format": dataset.format,
            "columns": list(dataset.columns or []),
            "row_count": dataset.row_count,
            "size_bytes": dataset.size_bytes,
            "updated_at": dataset.updated_at,
        }
        for dataset in datasets
    ]
    snippet = build_page_data_runtime(
        endpoint=f"/p/{page.owner}/{page.slug}/data",
        token=token,
        datasets=manifest,
    )
    return inject_page_data_runtime(html, snippet)


def reject_disabled_sql_data_sources(data_sources) -> None:
    """Fail fast instead of saving a SQL-template page that can never render."""
    if data_sources and legacy_sql_mode() == "disabled":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Legacy SQL data_sources are disabled on this server because they can bypass "
                "page permissions. Upload page datasets instead."
            ),
        )


def inject_copy_source_toolbar(html: str, *, source_html: str) -> str:
    markdown = convert_html_to_markdown(source_html)
    toolbar = build_copy_source_toolbar(html=source_html, markdown=markdown)
    lower_html = html.lower()
    body_index = lower_html.rfind("</body>")
    if body_index == -1:
        return f"{html}{toolbar}"
    return f"{html[:body_index]}{toolbar}{html[body_index:]}"


@router.post(
    "/api/pages",
    response_model=ApiResponse[PagePublishResponse],
    status_code=status.HTTP_201_CREATED,
)
def publish_page(
    payload: PagePublishRequest,
    request: Request,
    db: DbSession,
) -> ApiResponse[PagePublishResponse]:
    user_agent = request.headers.get("user-agent")
    actor = get_request_actor(request, db)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A verified user email is required to publish pages.",
        )
    if actor.source != "admin_token" and not is_real_user_email(actor.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A verified FeedMob user email is required to publish pages.",
        )
    reject_disabled_sql_data_sources(payload.data_sources)
    sharing = publish_sharing(db, actor, payload)
    validate_grants(db, sharing.share_with)
    try:
        page = publish_html_page(
            db,
            PublishHtmlPageInput(
                html=payload.html,
                owner=payload.owner,
                submitter=actor.email,
                description=payload.description,
                slug=payload.slug,
                title=payload.title,
                data_sources=payload.data_sources,
            ),
            SubmissionContext(
                submit_ip=get_client_ip(request),
                submit_user_agent=user_agent,
                submit_device=detect_device(user_agent),
                user_id=actor.user_id,
                user_email=actor.email,
            ),
            commit=False,
        )
        effective = set_sharing(db, actor, page, sharing, initial=True)
        db.commit()
    except (InvalidOwnerError, InvalidSlugError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except SlugConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ApiResponse(
        msg="page published",
        data=PagePublishResponse(
            **effective.model_dump(),
            id=page.id,
            owner=page.owner,
            slug=page.slug,
            url=build_public_page_url(settings.public_base_url, page.owner, page.slug),
            created_at=page.created_at,
        ),
    )


def build_page_search_filter(q: Optional[str]):
    if not q:
        return None

    keyword = q.strip()
    if not keyword:
        return None

    pattern = f"%{keyword}%"
    return or_(
        PageAsset.owner.ilike(pattern),
        PageAsset.slug.ilike(pattern),
        PageAsset.title.ilike(pattern),
        PageAsset.submitter.ilike(pattern),
        PageAsset.description.ilike(pattern),
    )


def page_unassigned_filter(allowlist: set[str]):
    return or_(
        PageAsset.user_email.is_(None),
        PageAsset.user_email == "",
        ~func.lower(PageAsset.user_email).like("%@feedmob.com"),
    )


def page_owner_filter(actor_email: str, actor_user_id: Optional[str]):
    filters = [func.lower(PageAsset.user_email) == actor_email.lower()]
    if actor_user_id:
        filters.append(PageAsset.user_id == actor_user_id)
    return or_(*filters)


def page_identity_filter(*, user_email: Optional[str], user_id: Optional[str]):
    filters = []
    if user_email:
        filters.append(func.lower(PageAsset.user_email) == user_email.lower())
    if user_id:
        filters.append(PageAsset.user_id == user_id)
    if not filters:
        return None
    return or_(*filters)


def legacy_submitter_filter(allowlist: set[str]):
    return and_(
        page_unassigned_filter(allowlist),
        PageAsset.submitter.is_not(None),
        PageAsset.submitter != "",
    )


def created_range_filter(created_range: CreatedRange):
    if created_range == "all":
        return None

    now = datetime.now(timezone.utc)
    if created_range == "24h":
        start = now - timedelta(hours=24)
    elif created_range == "7d":
        start = now - timedelta(days=7)
    else:
        start = now - timedelta(days=30)
    return PageAsset.created_at >= start


@router.get("/api/pages", response_model=ApiResponse[PageListResponse])
def list_pages(
    request: Request,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: Optional[str] = Query(default=None, max_length=100),
    scope: Literal["all", "mine", "unassigned"] = Query(default="all"),
    submitter: Optional[str] = Query(default=None, max_length=200),
    user_email: Optional[str] = Query(default=None, max_length=256),
    user_id: Optional[str] = Query(default=None, max_length=128),
    created_range: CreatedRange = CreatedRangeQuery,
) -> ApiResponse[PageListResponse]:
    filters = []
    if isinstance(scope, QueryParam):
        scope = "all"
    if isinstance(created_range, QueryParam):
        created_range = "all"
    if isinstance(submitter, QueryParam):
        submitter = None
    if isinstance(user_email, QueryParam):
        user_email = None
    if isinstance(user_id, QueryParam):
        user_id = None
    allowlist = parse_email_list(get_submitter_allowlist_value(db))
    actor = get_request_actor(request, db)
    access = discovery_filter(actor, mine=scope == "mine")
    filters.append(access)
    audit_admin_read(db, actor)
    unassigned_filter = page_unassigned_filter(allowlist)
    submitter_filter_value = submitter.strip().lower() if submitter else ""
    identity_filter = page_identity_filter(
        user_email=user_email.strip() if user_email else None,
        user_id=user_id.strip() if user_id else None,
    )

    if scope == "mine":
        actor = get_request_actor(request, db)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )
        filters.append(page_owner_filter(actor.email, actor.user_id))
        if unassigned_filter is not None:
            filters.append(not_(unassigned_filter))
    elif scope == "unassigned":
        if unassigned_filter is None:
            filters.append(PageAsset.id.is_(None))
        else:
            filters.append(unassigned_filter)
    elif identity_filter is not None:
        filters.append(identity_filter)
    elif submitter_filter_value:
        filters.append(func.lower(PageAsset.submitter) == submitter_filter_value)
        filters.append(legacy_submitter_filter(allowlist))

    search_filter = build_page_search_filter(q)
    if search_filter is not None:
        filters.append(search_filter)

    time_filter = created_range_filter(created_range)
    if time_filter is not None:
        filters.append(time_filter)

    total_stmt = select(func.count(PageAsset.id))
    list_stmt = select(PageAsset)
    if filters:
        total_stmt = total_stmt.where(*filters)
        list_stmt = list_stmt.where(*filters)

    total = db.scalar(total_stmt) or 0
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    pages = db.scalars(
        list_stmt.order_by(desc(PageAsset.created_at), PageAsset.owner, PageAsset.slug)
        .offset(offset)
        .limit(page_size)
    ).all()
    legacy_submitters = [
        row[0]
        for row in db.execute(
            select(PageAsset.submitter)
            .where(legacy_submitter_filter(allowlist), access)
            .group_by(PageAsset.submitter)
            .order_by(func.lower(PageAsset.submitter))
        ).all()
    ]
    identity_filters = [
        PageIdentityFilterResponse(
            user_id=row_user_id,
            user_email=row_user_email,
            count=count,
        )
        for row_user_id, row_user_email, count in db.execute(
            select(PageAsset.user_id, PageAsset.user_email, func.count(PageAsset.id))
            .where(
                access,
                and_(
                    PageAsset.user_email.is_not(None),
                    PageAsset.user_email != "",
                    func.lower(PageAsset.user_email).like("%@feedmob.com"),
                ),
            )
            .group_by(PageAsset.user_id, PageAsset.user_email)
            .order_by(func.lower(PageAsset.user_email), PageAsset.user_id)
        ).all()
        if is_assigned_page_identity(row_user_email)
    ]

    return ApiResponse(
        data=PageListResponse(
            items=[
                to_page_asset_response(page_asset, allowlist=allowlist, db=db, actor=actor)
                for page_asset in pages
            ],
            pagination=PaginationResponse(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1 and total_pages > 0,
            ),
            legacy_submitters=legacy_submitters,
            identity_filters=identity_filters,
        )
    )


@router.get("/api/pages/stats", response_model=ApiResponse[PageStatsResponse])
def get_page_stats(request: Request, db: DbSession) -> ApiResponse[PageStatsResponse]:
    actor = get_request_actor(request, db)
    access = discovery_filter(actor)
    audit_admin_read(db, actor)
    total_pages = db.scalar(select(func.count(PageAsset.id)).where(access)) or 0
    total_owners = db.scalar(select(func.count(distinct(PageAsset.owner))).where(access)) or 0
    total_submitters = (
        db.scalar(select(func.count(distinct(PageAsset.submitter))).where(access)) or 0
    )
    latest_created_at = db.scalar(select(func.max(PageAsset.created_at)).where(access))

    owner_rows = db.execute(
        select(PageAsset.owner, func.count(PageAsset.id))
        .where(access)
        .group_by(PageAsset.owner)
        .order_by(desc(func.count(PageAsset.id)), PageAsset.owner)
        .limit(10)
    ).all()
    submitter_rows = db.execute(
        select(PageAsset.submitter, func.count(PageAsset.id))
        .where(access)
        .group_by(PageAsset.submitter)
        .order_by(desc(func.count(PageAsset.id)), PageAsset.submitter)
        .limit(10)
    ).all()

    return ApiResponse(
        data=PageStatsResponse(
            total_pages=total_pages,
            total_owners=total_owners,
            total_submitters=total_submitters,
            latest_created_at=latest_created_at,
            top_owners=[
                CountByOwnerResponse(owner=owner, count=count) for owner, count in owner_rows
            ],
            top_submitters=[
                CountBySubmitterResponse(submitter=submitter, count=count)
                for submitter, count in submitter_rows
            ],
        )
    )


@router.get("/api/pages/{owner}/{slug}", response_model=ApiResponse[PageDetailResponse])
def get_page(
    owner: str, slug: str, request: Request, db: DbSession
) -> ApiResponse[PageDetailResponse]:
    page = db.scalar(select(PageAsset).where(PageAsset.owner == owner, PageAsset.slug == slug))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    allowlist = parse_email_list(get_submitter_allowlist_value(db))
    actor = get_request_actor(request, db)
    require_view(db, actor, page)
    return ApiResponse(
        data=to_page_detail_response(page, allowlist=allowlist, db=db, actor=actor)
    )


@router.post("/api/pages/{page_id}/claim", response_model=ApiResponse[PageDetailResponse])
def claim_unassigned_page(
    page_id: str,
    request: Request,
    db: DbSession,
) -> ApiResponse[PageDetailResponse]:
    actor = get_request_actor(request, db)
    if actor is None or actor.source == "admin_token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified user email is required to claim pages.",
        )

    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    require_view(db, actor, page)

    allowlist = parse_email_list(get_submitter_allowlist_value(db))
    if not is_unassigned_page(
        page.submitter,
        page.user_id,
        page.user_email,
        allowlist=allowlist,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Page is already assigned.",
        )

    audit_claim(db, actor, page)
    try:
        page = claim_page(
            db,
            page_id,
            submitter=actor.email,
            user_id=actor.user_id,
            user_email=actor.email,
        )
    except PageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ApiResponse(
        msg="page claimed",
        data=to_page_detail_response(page, allowlist=allowlist, db=db, actor=actor),
    )


@router.put("/api/pages/{page_id}", response_model=ApiResponse[PageDetailResponse])
def update_page(
    page_id: str,
    payload: PageUpdateRequest,
    request: Request,
    db: DbSession,
) -> ApiResponse[PageDetailResponse]:
    actor = get_request_actor(request, db)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    page = db.scalar(select(PageAsset).where(PageAsset.id == page_id))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    require_view(db, actor, page)
    sharing_fields = any(
        getattr(payload, field) is not None for field in ("visibility", "share_with", "listed")
    )
    if sharing_fields or page.visibility != "org":
        require_owner(db, actor, page)

    allowlist = parse_email_list(get_submitter_allowlist_value(db))
    is_unassigned = is_unassigned_page(
        page.submitter,
        page.user_id,
        page.user_email,
        allowlist=allowlist,
    )
    if not actor_can_manage_page(
        actor,
        page.submitter,
        page.user_id,
        page.user_email,
        allowlist=allowlist,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update pages you own or unassigned pages.",
        )

    try:
        claim_identity = is_unassigned and actor.source != "admin_token"
        content_fields = any(
            getattr(payload, field) is not None
            for field in ("html", "title", "description", "data_sources")
        )
        if not content_fields and not sharing_fields:
            raise NoFieldsToUpdateError("At least one field must be provided.")
        reject_disabled_sql_data_sources(payload.data_sources)
        if content_fields and claim_identity:
            audit_claim(db, actor, page)
        if content_fields:
            page = update_html_page(
                db,
                page_id,
                html=payload.html,
                title=payload.title,
                description=payload.description,
                data_sources=payload.data_sources,
                submitter=actor.email if claim_identity else None,
                user_id=actor.user_id if claim_identity else None,
                user_email=actor.email if claim_identity else None,
                commit=False,
            )
        if sharing_fields:
            set_sharing(db, actor, page, payload)
        db.commit()
    except PageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NoFieldsToUpdateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(
        msg="page updated",
        data=to_page_detail_response(page, allowlist=allowlist, db=db, actor=actor),
    )


@router.delete("/api/pages/{page_id}", response_model=ApiResponse[dict])
def delete_page_endpoint(
    page_id: str,
    request: Request,
    db: DbSession,
) -> ApiResponse[dict]:
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
            detail="You can only delete pages you own or unassigned pages.",
        )

    try:
        page = delete_page(db, page_id)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApiResponse(msg="page deleted", data={"id": str(page.id)})


@router.get("/p/{owner}/{slug}", response_class=Response)
def render_page(owner: str, slug: str, request: Request, db: DbSession) -> Response:
    page = db.scalar(select(PageAsset).where(PageAsset.owner == owner, PageAsset.slug == slug))
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    actor = get_request_actor(request, db)
    require_view(db, actor, page)
    html = page.html
    source_html = page.html
    if page.data_sources:
        try:
            html = render_template(page.html, page.data_sources, db)
        except DataSourceError as exc:
            return Response(
                content=f"<pre>Data source error: {exc}</pre>",
                media_type="text/html; charset=utf-8",
                status_code=500,
            )
    html = attach_page_datasets(html, page, db, actor)
    html = inject_copy_source_toolbar(html, source_html=source_html)
    # H2: 防 XSS — 用户 HTML 在同源 www.html.living 下若不隔离，可窃取 feedmob 其他服务的 cookie。
    # CSP sandbox 不允许 same-origin（脚本仍可执行，但跨源访问被剥夺）。
    # 同时禁止被其他站点 iframe 嵌入，避免 clickjacking。
    headers = {
        "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups allow-modals",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)
