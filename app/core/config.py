"""Application configuration. All secrets come from the environment."""

from __future__ import annotations
from urllib.parse import quote_plus
from functools import lru_cache

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
    EMBEDDING_MODEL: str = "models/text-embedding-004"
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
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url(self) -> str:
        # Credentials must be percent-encoded: an '@' or ':' in the password
        # otherwise terminates the userinfo section early and the rest of the
        # password gets parsed as the hostname.
        return (
            f"postgresql+psycopg://{quote_plus(self.POSTGRES_USER)}:"
            f"{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod"}

    

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
