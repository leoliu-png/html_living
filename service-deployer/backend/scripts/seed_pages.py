from __future__ import annotations

from app.database import SessionLocal, create_tables
from app.services.pages import (
    PublishHtmlPageInput,
    SlugConflictError,
    SubmissionContext,
    publish_html_page,
)

BASE_SEED_PAGES = [
    PublishHtmlPageInput(
        owner="leo",
        slug="welcome",
        title="Welcome Page",
        submitter="leo@feedmob.com",
        description="Seed page for console development.",
        html="<!doctype html><html><body><h1>Welcome</h1><p>Console seed page.</p></body></html>",
    ),
    PublishHtmlPageInput(
        owner="ken",
        slug="demo-report",
        title="Demo Report",
        submitter="ken@feedmob.com",
        description="Sample internal report page.",
        html=(
            "<!doctype html><html><body><h1>Demo Report</h1>"
            "<p>PostgreSQL is connected.</p></body></html>"
        ),
    ),
]


def build_bulk_seed_pages() -> list[PublishHtmlPageInput]:
    owners = [
        ("leo", "leo@feedmob.com"),
        ("ken", "ken@feedmob.com"),
        ("esther", "esther@feedmob.com"),
        ("jason", "jason@feedmob.com"),
        ("alyssa", "alyssa@feedmob.com"),
        ("bran", "bran@feedmob.com"),
        ("vicky", "vicky@feedmob.com"),
        ("ops", "ops@feedmob.com"),
    ]
    page_types = [
        "campaign-preview",
        "weekly-report",
        "creative-board",
        "landing-demo",
        "data-snapshot",
        "qa-checklist",
        "budget-overview",
        "partner-brief",
        "release-notes",
        "market-watch",
        "audience-map",
        "asset-gallery",
        "sales-deck",
        "ops-runbook",
        "experiment-log",
    ]
    pages: list[PublishHtmlPageInput] = []

    for owner_index, (owner, submitter) in enumerate(owners, start=1):
        for page_index, page_type in enumerate(page_types, start=1):
            slug = f"{page_type}-{page_index:02d}"
            title = f"{owner.title()} {page_type.replace('-', ' ').title()}"
            pages.append(
                PublishHtmlPageInput(
                    owner=owner,
                    slug=slug,
                    title=title,
                    submitter=submitter,
                    description=(
                        f"Seed page {page_index} for {owner}. "
                        "Used for console scrolling and statistics QA."
                    ),
                    html=(
                        "<!doctype html><html><body>"
                        f"<h1>{title}</h1>"
                        f"<p>Owner #{owner_index}, sample page #{page_index}.</p>"
                        "</body></html>"
                    ),
                )
            )

    return pages


def seed_pages() -> list[PublishHtmlPageInput]:
    return BASE_SEED_PAGES + build_bulk_seed_pages()


def main() -> None:
    create_tables()
    with SessionLocal() as db:
        for page in seed_pages():
            try:
                publish_html_page(
                    db,
                    page,
                    SubmissionContext(
                        submit_ip="127.0.0.1",
                        submit_user_agent="backend-seed",
                        submit_device="Seed Script",
                    ),
                )
                print(f"seeded /p/{page.owner}/{page.slug}")
            except SlugConflictError:
                print(f"skipped existing /p/{page.owner}/{page.slug}")


if __name__ == "__main__":
    main()
