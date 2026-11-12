"""Typed application settings."""

from functools import lru_cache
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SCOUT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Revvix Scout"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://localhost/revvix_scout"
    default_workspace_id: UUID = Field(default=UUID("00000000-0000-4000-8000-000000000001"))
    default_icp_id: UUID = Field(default=UUID("00000000-0000-4000-8000-000000000101"))
    default_icp_version_id: UUID = Field(default=UUID("00000000-0000-4000-8000-000000000102"))
    max_import_bytes: int = 2_000_000
    max_import_rows: int = 5_000


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
