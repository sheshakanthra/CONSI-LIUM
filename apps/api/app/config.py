"""Application configuration.

WHY pydantic-settings: the project rule (CLAUDE.md) forbids hardcoded keys and
mandates config via .env + pydantic-settings. Centralising settings in one
typed object means every module reads the same validated values, and a missing
or malformed env var fails loudly at startup instead of silently at request
time.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / .env file."""

    # WHY a single DATABASE_URL rather than discrete host/port/user fields:
    # docker-compose and prod both inject one connection string, and async
    # SQLAlchemy consumes it directly. Keeping it as one value avoids drift
    # between the two representations.
    database_url: str = "postgresql+asyncpg://consilium:consilium@localhost:5432/consilium"

    # Free-form service metadata, surfaced by the health check so we can tell
    # which build is running behind a load balancer.
    app_name: str = "consilium-api"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    WHY cache: settings are immutable for the process lifetime, so we parse the
    environment once. lru_cache also makes this trivial to override in tests
    (call get_settings.cache_clear()).
    """
    return Settings()
