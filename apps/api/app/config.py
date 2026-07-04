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

    # --- Ingestion: source directories --------------------------------------
    # Where the ingestion layer looks for local sample inputs. Defaults are
    # repo-relative (host dev); docker-compose overrides them to the mounted
    # /data path. Kept as plain str (not Path) so env overrides stay trivial.
    filings_dir: str = "data/filings"
    transcripts_dir: str = "data/transcripts"

    # --- Ingestion: text chunking -------------------------------------------
    # Character-based windows over extracted filing text. Small and overlapping
    # so later retrieval keeps sentences that straddle a boundary. Deliberately
    # simple for now — token-aware/semantic chunking is a retrieval-phase
    # concern, not an ingestion one.
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # --- Ingestion: ASR (faster-whisper) ------------------------------------
    # "tiny" keeps local dev + CI fast and CPU-friendly; swap to a larger model
    # (or the Whisper API, per CLAUDE.md) in prod. int8 on CPU is the fastest
    # compute type that faster-whisper supports without a GPU.
    whisper_model: str = "tiny"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # None => let Whisper auto-detect the spoken language.
    whisper_language: str | None = None

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
