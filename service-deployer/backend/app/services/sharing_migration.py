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
