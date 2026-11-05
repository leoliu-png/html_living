from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://service_deployer:service_deployer"
        "@localhost:5432/service_deployer"
    )
    public_base_url: str = "http://127.0.0.1:8000"
    api_token: str = ""
    # Legacy SQL templates execute with the application's database privileges.
    # Disabled by default because they can bypass page-level access controls.
    allow_legacy_sql_data_sources: bool = False

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_domain: str = ""  # restrict login to this email domain (e.g. "feedmob.com")

    # Session
    session_secret: str = "change-me-in-production"

    # JWT — shared secret with MCP Server for validating MCP-issued tokens
    jwt_secret: str = ""

    # Admin emails (comma-separated) — can delete any page
    admin_emails: str = ""

    # Optional submitter allowlist for identifying legacy/unclaimed pages.
    # When empty, no page is treated as unassigned by allowlist rules.
    submitter_allowlist: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
