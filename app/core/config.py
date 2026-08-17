"""Application configuration. All secrets come from the environment."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- application ---
    APP_NAME: str = "Bodhi Hub VCS 5.0"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    # Comma-separated. In production the frontend is served by this app, so the
    # browser is same-origin and this list is normally empty.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Directory holding the built frontend. Mounted only when it exists, so a
    # developer running `uvicorn` without building the UI is unaffected.
    STATIC_DIR: str = "frontend/dist"

    # Architecture.md specifies S3-compatible object storage. Local disk for
    # now, behind services.ingestion.storage_root so swapping it is one change.
    UPLOAD_DIR: str = "uploads"

    # "local" or "s3". Local is the default so a developer needs no cloud
    # credentials; production should use s3 per Architecture.md, because the
    # application volume is not replicated and does not survive a container
    # being replaced.
    STORAGE_BACKEND: str = "local"
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""   # set for MinIO, R2, Backblaze; blank for AWS
    S3_REGION: str = ""

    # --- database ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "bodhi_vcs5"

    # --- auth ---
    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"
    MAX_FAILED_LOGINS: int = 5

    # --- LLM ---
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-flash-latest"
    EMBEDDING_MODEL: str = "gemini-embedding-001"
    # gemini-embedding-001 returns 3072 by default and supports truncation.
    # 768 is requested instead: report_chunks.embedding is sized to this, and
    # for a corpus of a few hundred documents the larger vector costs four
    # times the storage and index time for no retrieval quality anyone would
    # notice. Changing this requires a migration to resize the column.
    EMBEDDING_DIM: int = 768

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_placeholder_secret(cls, v: str) -> str:
        if v.lower() in {"changeme", "secret", "your-secret-key"}:
            raise ValueError("SECRET_KEY is a placeholder. Generate one with: "
                             "python -c 'import secrets; print(secrets.token_urlsafe(48))'")
        return v

    @property
    def database_url(self) -> str:
        # Credentials must be percent-encoded. An '@' or ':' in the password
        # otherwise terminates the userinfo section early and the remainder is
        # parsed as the hostname, which surfaces as a DNS failure
        # ("nodename nor servname provided") rather than an auth error.
        return (
            f"postgresql+psycopg://{quote_plus(self.POSTGRES_USER)}:"
            f"{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
