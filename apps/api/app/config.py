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

    # Log level for the app's own loggers (the "consilium.*" namespace, which
    # includes the per-call [llm] cost/token line). Configured at startup in
    # app.main — without that config, INFO records are silently dropped.
    log_level: str = "INFO"

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

    # --- Retrieval: embeddings (Phase 2) ------------------------------------
    # BAAI/bge-small-en-v1.5 via fastembed (ONNX): 384-dim, CPU-friendly, free,
    # strong small-model retrieval quality. Dim must match the pgvector columns.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # Where fastembed caches downloaded ONNX weights (under the mounted HF cache
    # volume so it downloads once).
    embedding_cache_dir: str = "/root/.cache/huggingface/fastembed"

    # --- Retrieval: search + answering --------------------------------------
    retrieval_top_k: int = 5
    # Cosine-similarity floor (0..1) below which a vector hit is treated as
    # weak; feeds the confidence banding and "insufficient evidence" path.
    retrieval_min_similarity: float = 0.35
    # Reciprocal-rank-fusion constant for blending vector + keyword rankings.
    rrf_k: int = 60

    # --- Agents: LLM (Phase 3) ----------------------------------------------
    # Which provider the reasoning agents use, behind the shared llm_client seam.
    # Default "groq" (free developer tier) while Anthropic credits are unavailable;
    # switch to "anthropic" to use Claude via the same interface.
    llm_provider: str = "groq"

    # Anthropic (Claude) — paid. Optional so the app boots / tests run without it.
    anthropic_api_key: str | None = None
    # The Claude model used when llm_provider == "anthropic".
    agent_model: str = "claude-haiku-4-5"

    # Groq — free developer tier, OpenAI-compatible API.
    groq_api_key: str | None = None
    # Fast, current general-purpose production model (see docs/phase2 note).
    groq_model: str = "llama-3.3-70b-versatile"

    # Output cap for the small structured JSON the agents request (both providers).
    agent_max_tokens: int = 2048

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
