import io
import json
import os

os.environ.setdefault("R2_ACCOUNT_ID", "test-r2-account")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test-r2-access-key")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test-r2-secret-key")
os.environ.setdefault("R2_BUCKET_NAME", "test-r2-bucket")
os.environ.setdefault("R2_PUBLIC_URL", "https://assets.example.test")

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.config import settings
from app.database import Base, get_db
from app.main import create_app
from app.models import PageAsset, PageDataset
from app.services import datasets as dataset_service

CSV_BODY = (
    "campaign,country,spend,installs\n"
    "brand-search,US,1200.50,340\n"
    "brand-search,JP,980,210\n"
    "retargeting,US,150,42\n"
    "retargeting,DE,,0\n"
)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, key, body, content_type=None):
        self.objects[key] = body

    def get_object(self, key):
        if key not in self.objects:
            from app.services.storage import StorageObjectNotFoundError

            raise StorageObjectNotFoundError(key)
        return self.objects[key]

    def delete_object(self, key):
        self.objects.pop(key, None)

    def public_url(self, key):
        return f"https://assets.example.test/{key}"


@pytest.fixture(autouse=True)
def clear_cache():
    dataset_service.clear_dataset_cache()
    yield
    dataset_service.clear_dataset_cache()


def make_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        with session_factory() as session:
            yield session

    storage = FakeStorage()
    monkeypatch.setattr("app.main.create_tables", lambda: None)
    monkeypatch.setattr("app.database.SessionLocal", session_factory)
    monkeypatch.setattr(settings, "api_token", "admin-token")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://pages.example.test")
    monkeypatch.setattr("app.services.storage.put_object", storage.put_object)
    monkeypatch.setattr("app.services.storage.get_object", storage.get_object)
    monkeypatch.setattr("app.services.storage.delete_object", storage.delete_object)
    monkeypatch.setattr("app.services.storage.public_url", storage.public_url)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), session_factory, storage


def seed_page(session_factory, *, owner="reports", slug="weekly") -> str:
    with session_factory() as db:
        page = PageAsset(
            owner=owner,
            slug=slug,
            title="Weekly",
            submitter="alice@feedmob.com",
            description="Weekly report",
            html="<html><head><title>Weekly</title></head><body><h1>Weekly</h1></body></html>",
            user_id="alice-sub",
            user_email="alice@feedmob.com",
        )
        db.add(page)
        db.commit()
        return page.id


def upload_csv(client, page_id, *, name="spend", body=CSV_BODY, filename="spend.csv"):
    return client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": (filename, io.BytesIO(body.encode()), "text/csv")},
        data={"name": name},
    )


def test_upload_csv_dataset_registers_metadata(monkeypatch) -> None:
    client, session_factory, storage = make_client(monkeypatch)
    page_id = seed_page(session_factory)

    response = upload_csv(client, page_id)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["name"] == "spend"
    assert data["format"] == "csv"
    assert data["row_count"] == 4
    assert data["columns"] == ["campaign", "country", "spend", "installs"]
    assert data["data_url"] == "https://pages.example.test/p/reports/weekly/data/spend"
    assert len(storage.objects) == 1


def test_upload_rejects_unsupported_extension(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)

    response = client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported dataset file type" in response.json()["detail"]


def test_reupload_same_name_replaces_object(monkeypatch) -> None:
    client, session_factory, storage = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    response = upload_csv(
        client,
        page_id,
        body="campaign,country,spend,installs\nnew,US,1,1\n",
    )

    assert response.status_code == 201
    assert response.json()["data"]["row_count"] == 1
    assert len(storage.objects) == 1
    with session_factory() as db:
        assert len(list(db.scalars(select(PageDataset)))) == 1


def test_dataset_query_filters_sorts_and_paginates(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    response = client.get(
        "/p/reports/weekly/data/spend?token=admin-token"
        "&where=country:eq:US&sort=spend&order=desc&limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["matched"] == 2
    assert payload["count"] == 1
    assert payload["rows"][0]["campaign"] == "brand-search"
    assert response.headers["access-control-allow-origin"] == "*"


def test_dataset_query_supports_numeric_and_text_operators(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    numeric = client.get(
        "/p/reports/weekly/data/spend?token=admin-token&where=spend:gte:500&format=rows"
    )
    contains = client.get(
        "/p/reports/weekly/data/spend?token=admin-token&where=campaign:contains:target&format=rows"
    )
    empty = client.get(
        "/p/reports/weekly/data/spend?token=admin-token&where=spend:empty&format=rows"
    )
    multi = client.get(
        "/p/reports/weekly/data/spend?token=admin-token"
        "&where=country:in:US,DE&where=installs:lt:100&format=rows"
    )

    assert [row["country"] for row in numeric.json()] == ["US", "JP"]
    assert len(contains.json()) == 2
    assert [row["country"] for row in empty.json()] == ["DE"]
    assert [row["campaign"] for row in multi.json()] == ["retargeting", "retargeting"]


def test_dataset_query_select_and_csv_output(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    response = client.get(
        "/p/reports/weekly/data/spend?token=admin-token&select=campaign,spend&format=csv&limit=2"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "campaign,spend"
    assert len(response.text.strip().splitlines()) == 3


def test_dataset_query_rejects_unknown_column(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    response = client.get("/p/reports/weekly/data/spend?token=admin-token&where=ghost:eq:1")

    assert response.status_code == 400
    assert "Unknown column" in response.json()["detail"]


def test_dataset_endpoint_accepts_page_data_token_without_session(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)
    with session_factory() as db:
        token = db.scalar(select(PageAsset.data_token).where(PageAsset.id == page_id))
    assert token

    allowed = client.get(f"/p/reports/weekly/data/spend?k={token}")
    denied = client.get("/p/reports/weekly/data/spend")
    wrong_token = client.get("/p/reports/weekly/data/spend?k=nope")

    assert allowed.status_code == 200
    assert denied.status_code == 401
    assert wrong_token.status_code == 401


def test_dataset_token_is_scoped_to_its_page(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    first_page = seed_page(session_factory)
    seed_page(session_factory, owner="reports", slug="monthly")
    upload_csv(client, first_page)
    with session_factory() as db:
        token = db.scalar(select(PageAsset.data_token).where(PageAsset.id == first_page))

    response = client.get(f"/p/reports/monthly/data/spend?k={token}")

    assert response.status_code == 401


def test_json_dataset_upload_and_query(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    body = json.dumps(
        [
            {"channel": "ios", "revenue": 120},
            {"channel": "android", "revenue": 80},
        ]
    )

    upload = client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": ("revenue.json", io.BytesIO(body.encode()), "application/json")},
    )
    query = client.get(
        "/p/reports/weekly/data/revenue?token=admin-token&where=revenue:gt:100&format=rows"
    )

    assert upload.status_code == 201
    assert upload.json()["data"]["name"] == "revenue"
    assert query.json() == [{"channel": "ios", "revenue": 120}]


def test_rendered_page_injects_page_data_runtime(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    upload_csv(client, page_id)

    response = client.get("/p/reports/weekly?token=admin-token")

    assert response.status_code == 200
    assert 'id="page-data-manifest"' in response.text
    assert "window.PageData" in response.text
    assert "/p/reports/weekly/data" in response.text
    with session_factory() as db:
        token = db.scalar(select(PageAsset.data_token).where(PageAsset.id == page_id))
    from bs4 import BeautifulSoup
    manifest = json.loads(BeautifulSoup(response.text, "html.parser").find(id="page-data-manifest").string)
    assert manifest["token"] != token
    assert client.get(f"/p/reports/weekly/data/spend?k={manifest['token']}").status_code == 200


def test_page_without_datasets_has_no_runtime(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    seed_page(session_factory)

    response = client.get("/p/reports/weekly?token=admin-token")

    assert response.status_code == 200
    assert "page-data-manifest" not in response.text


def test_list_and_delete_dataset(monkeypatch) -> None:
    client, session_factory, storage = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    dataset_id = upload_csv(client, page_id).json()["data"]["id"]

    listing = client.get(f"/api/pages/{page_id}/datasets?token=admin-token")
    deleted = client.delete(
        f"/api/pages/{page_id}/datasets/{dataset_id}?token=admin-token"
    )
    listing_after = client.get(f"/api/pages/{page_id}/datasets?token=admin-token")

    assert listing.status_code == 200
    assert len(listing.json()["data"]["items"]) == 1
    assert listing.json()["data"]["data_endpoint"] == (
        "https://pages.example.test/p/reports/weekly/data"
    )
    assert deleted.status_code == 200
    assert listing_after.json()["data"]["items"] == []
    assert storage.objects == {}


def test_dataset_management_requires_page_permission(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)

    response = client.post(
        f"/api/pages/{page_id}/datasets",
        files={"file": ("spend.csv", io.BytesIO(CSV_BODY.encode()), "text/csv")},
    )

    assert response.status_code == 401


def test_dataset_upload_forbidden_for_other_user(monkeypatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    from app.services.api_keys import create_api_key

    with session_factory() as db:
        _, api_key = create_api_key(
            db,
            user_email="bob@feedmob.com",
            user_id="bob-sub",
            name="Bob",
        )

    response = client.post(
        f"/api/pages/{page_id}/datasets?token={api_key}",
        files={"file": ("spend.csv", io.BytesIO(CSV_BODY.encode()), "text/csv")},
    )

    assert response.status_code == 403


def test_dataset_name_normalization_and_validation() -> None:
    assert dataset_service.normalize_dataset_name("Q3 Spend Report") == "q3-spend-report"
    assert dataset_service.dataset_name_from_filename("/tmp/Weekly Spend.csv") == "weekly-spend"
    with pytest.raises(dataset_service.DatasetError):
        dataset_service.normalize_dataset_name("---")


def test_oversized_upload_is_rejected_with_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matches the image upload endpoint, which also answers 413."""

    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    oversized = b"a,b\n" + b"1,2\n" * ((dataset_service.MAX_UPLOAD_BYTES // 4) + 10)

    response = client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": ("huge.csv", io.BytesIO(oversized), "text/csv")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_too_many_rows_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    monkeypatch.setattr(dataset_service, "MAX_ROWS", 5)
    body = "idx\n" + "".join(f"{i}\n" for i in range(6))

    response = client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": ("many.csv", io.BytesIO(body.encode()), "text/csv")},
    )

    assert response.status_code == 400
    assert "too many rows" in response.json()["detail"].lower()


def test_paging_covers_a_dataset_larger_than_one_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dashboard must be able to walk past DEFAULT_QUERY_LIMIT without losing rows."""

    client, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)
    monkeypatch.setattr(dataset_service, "DEFAULT_QUERY_LIMIT", 10)
    rows = 25
    body = "idx,bucket\n" + "".join(f"{i},b{i % 5}\n" for i in range(rows))
    upload = client.post(
        f"/api/pages/{page_id}/datasets?token=admin-token",
        files={"file": ("big.csv", io.BytesIO(body.encode()), "text/csv")},
        data={"name": "big"},
    )
    assert upload.status_code == 201

    token = client.get(
        f"/api/pages/{page_id}/datasets?token=admin-token"
    ).json()["data"]["data_token"]

    collected: list[dict] = []
    offset = 0
    while True:
        payload = client.get(
            "/p/reports/weekly/data/big",
            params={"k": token, "offset": offset},
        ).json()
        assert payload["total"] == rows
        collected.extend(payload["rows"])
        if not payload["rows"] or len(collected) >= payload["matched"]:
            break
        offset += payload["count"]

    assert [row["idx"] for row in collected] == [str(i) for i in range(rows)]

    clamped = client.get(
        "/p/reports/weekly/data/big",
        params={"k": token, "limit": 10**9},
    ).json()
    assert clamped["limit"] <= dataset_service.MAX_QUERY_ROWS


def test_dataset_cache_is_safe_under_concurrent_access() -> None:
    """Sync routes share one process, so the cache is hit from many threads.

    Without locking, populating the cache while another request evicts an entry
    raises "dictionary changed size during iteration" and the request 500s.
    """

    import threading

    dataset_service.clear_dataset_cache()
    parsed = dataset_service.ParsedDataset(
        format="csv", columns=["a"], rows=[{"a": str(i)} for i in range(50)]
    )
    errors: list[BaseException] = []
    stop = threading.Event()

    def put(index: int) -> None:
        try:
            while not stop.is_set():
                dataset_service._cache_put(f"key-{index % 5}", parsed)
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    def drop(index: int) -> None:
        try:
            while not stop.is_set():
                dataset_service._cache_drop(f"key-{index % 5}")
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=put, args=(i,)) for i in range(4)]
    threads += [threading.Thread(target=drop, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    stop.wait(0.4)
    stop.set()
    for thread in threads:
        thread.join(timeout=5)

    dataset_service.clear_dataset_cache()
    assert not errors, f"cache race: {errors[:1]}"


def test_data_token_is_created_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent first renders must not hand out a token that gets overwritten."""

    _, session_factory, _ = make_client(monkeypatch)
    page_id = seed_page(session_factory)

    with session_factory() as db:
        page = db.get(PageAsset, page_id)
        assert page.data_token is None
        first = dataset_service.ensure_page_data_token(db, page)
        assert first

    with session_factory() as db:
        page = db.get(PageAsset, page_id)
        # A second caller finds the stored token instead of minting a new one.
        assert dataset_service.ensure_page_data_token(db, page) == first

    with session_factory() as db:
        stored = db.get(PageAsset, page_id).data_token
    assert stored == first
