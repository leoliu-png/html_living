import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth_context import RequestActor
from app.database import Base
from app.models import PageAsset
from app.schemas.sharing import ShareWith, SharingUpdate
from app.services.sharing import get_sharing, set_sharing
from app.services.sharing_migration import migrate_page_sharing


@pytest.mark.skipif(
    not os.environ.get("SHARING_TEST_DATABASE_URL"), reason="Requires local PostgreSQL"
)
def test_postgres_migration_preserves_existing_pages_and_is_idempotent():
    engine = create_engine(os.environ["SHARING_TEST_DATABASE_URL"])
    schema = "sharing_test_" + uuid4().hex
    with engine.connect() as connection:
        # Everything, including schema creation, is rolled back after the check.
        with connection.begin() as transaction:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE page_assets (id TEXT PRIMARY KEY, html TEXT)"))
            connection.execute(text("INSERT INTO page_assets VALUES ('legacy', 'unchanged')"))
            migrate_page_sharing(connection)
            migrate_page_sharing(connection)
            assert connection.execute(
                text("SELECT html, visibility, listed FROM page_assets")
            ).one() == ("unchanged", "org", True)
            connection.execute(text("UPDATE page_assets SET visibility='private', listed=false"))
            migrate_page_sharing(connection)
            assert connection.execute(text("SELECT visibility, listed FROM page_assets")).one() == (
                "private",
                False,
            )
            transaction.rollback()
    engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("SHARING_TEST_DATABASE_URL"), reason="Requires local PostgreSQL"
)
def test_concurrent_grant_replacements_never_union_their_permissions():
    engine = create_engine(os.environ["SHARING_TEST_DATABASE_URL"])
    schema = "sharing_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    factory = sessionmaker(bind=scoped)
    try:
        Base.metadata.create_all(scoped)
        with factory() as db:
            page = PageAsset(
                owner="test",
                slug="test",
                html="test",
                description="test",
                submitter="owner@feedmob.com",
                user_email="owner@feedmob.com",
            )
            db.add(page)
            db.commit()
            page_id = page.id
        barrier = Barrier(2)
        actor = RequestActor(email="owner@feedmob.com", user_id=None, name=None, source="session")

        def replace(email):
            with factory() as db:
                page = db.get(PageAsset, page_id)
                barrier.wait(timeout=10)
                set_sharing(
                    db,
                    actor,
                    page,
                    SharingUpdate(visibility="restricted", share_with=ShareWith(users=[email])),
                )
                sleep(0.1)  # Keep one writer uncommitted while the other attempts replacement.
                db.commit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(replace, ["alice@feedmob.com", "bob@feedmob.com"]))
        with factory() as db:
            users = get_sharing(db, db.get(PageAsset, page_id)).share_with.users
            assert users in [["alice@feedmob.com"], ["bob@feedmob.com"]]
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
