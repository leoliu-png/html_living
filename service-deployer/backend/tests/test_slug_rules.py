from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.pages import (
    AUTO_SLUG_LENGTH,
    InvalidSlugError,
    PublishHtmlPageInput,
    SubmissionContext,
    detect_device,
    generate_unique_slug,
    normalize_owner,
    normalize_slug,
    publish_html_page,
)


def test_normalize_slug_accepts_lowercase_numbers_and_hyphens() -> None:
    assert normalize_slug("demo-page-01") == "demo-page-01"


def test_normalize_slug_lowercases_input() -> None:
    assert normalize_slug("Demo-Page") == "demo-page"


def test_normalize_owner_lowercases_input() -> None:
    assert normalize_owner("Leo") == "leo"


def test_normalize_slug_rejects_leading_hyphen() -> None:
    try:
        normalize_slug("-demo")
    except InvalidSlugError:
        return
    raise AssertionError("Expected InvalidSlugError")


def test_normalize_slug_rejects_unsafe_characters() -> None:
    try:
        normalize_slug("demo/page")
    except InvalidSlugError:
        return
    raise AssertionError("Expected InvalidSlugError")


def test_generate_unique_slug_uses_expected_length() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        slug = generate_unique_slug(db, "leo")

    assert len(slug) == AUTO_SLUG_LENGTH


def test_detect_device_from_user_agent() -> None:
    assert detect_device("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)") == "macOS"
    assert detect_device("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "Windows"
    assert detect_device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "iPhone"


def test_publish_html_page_records_submission_context() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        page = publish_html_page(
            db,
            PublishHtmlPageInput(
                html="<html><body>Hello</body></html>",
                owner="Leo",
                submitter=" leo@feedmob.com ",
                description=" first internal page ",
                slug="demo-page",
                title="Demo",
            ),
            SubmissionContext(
                submit_ip="127.0.0.1",
                submit_user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            ),
        )

    assert page.owner == "leo"
    assert page.slug == "demo-page"
    assert page.submitter == "leo@feedmob.com"
    assert page.description == "first internal page"
    assert page.submit_ip == "127.0.0.1"
    assert page.submit_device == "macOS"
    assert page.submit_user_agent == "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
