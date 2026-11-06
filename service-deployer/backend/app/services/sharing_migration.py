from sqlalchemy import text


def migrate_page_sharing(connection):
    """Additive PostgreSQL migration; existing pages retain organization access."""
    connection.execute(
        text(
            "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS "
            "visibility VARCHAR(16) NOT NULL DEFAULT 'org'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE page_assets ADD COLUMN IF NOT EXISTS listed BOOLEAN NOT NULL DEFAULT TRUE"
        )
    )


# Columns legacy SQL templates may read. `data_token` is deliberately excluded.
LEGACY_SQL_PAGE_COLUMNS = (
    "id, owner, slug, title, submitter, description, html, submit_ip, submit_device, "
    "submit_user_agent, data_sources, user_id, user_email, created_at, updated_at"
)


def create_legacy_sql_views(connection):
    """Schema read by the sandboxed legacy SQL role: only org + listed pages.

    Views run with the privileges of their owner (the application role), so the
    sandbox role needs USAGE on the schema and SELECT on the view, and nothing on
    `public`. PostgreSQL only; other engines skip it.
    """
    if connection.dialect.name != "postgresql":
        return
    source = connection.execute(text("SELECT quote_ident(current_schema())")).scalar_one()
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS legacy_sql"))
    connection.execute(
        text(
            "CREATE OR REPLACE VIEW legacy_sql.page_assets AS "
            f"SELECT {LEGACY_SQL_PAGE_COLUMNS} FROM {source}.page_assets "
            "WHERE visibility = 'org' AND listed"
        )
    )
