"""Embedding pipeline (fastembed / BAAI/bge-small-en-v1.5).

WHY this model + runtime (the cost/latency/quality tradeoff for a portfolio):

- Quality: bge-small-en-v1.5 is one of the strongest *small* retrieval models
  on MTEB (competitive with models many times its size) and is trained with a
  query/passage asymmetry that suits QA retrieval.
- Cost: it runs locally, so there is **zero per-embedding API cost** — the right
  call for a portfolio project that may re-embed often while iterating.
- Latency/footprint: 384 dimensions keeps pgvector rows small and distance
  math cheap; via **fastembed** it runs on onnxruntime (already in the image
  from faster-whisper) instead of pulling in ~1 GB of PyTorch. On CPU it embeds
  a small filing corpus in well under a second.

bge asymmetry matters: passages are embedded as-is, but queries must be
embedded with a search instruction prefix. fastembed exposes ``query_embed``
for exactly this, so we keep the two paths distinct.

The model is cached (``@lru_cache``) and downloaded once into the mounted HF
cache volume.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings


@lru_cache(maxsize=2)
def _load_model(model_name: str, cache_dir: str):
    """Load (and cache) the fastembed TextEmbedding model.

    Local import so the heavy fastembed/onnx import cost is only paid when
    embedding actually runs, not on every ``import retrieval``.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name, cache_dir=cache_dir)


class Embedder:
    """Thin wrapper turning text into vectors with the right query/passage path."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = _load_model(
            self._settings.embedding_model, self._settings.embedding_cache_dir
        )

    @property
    def dim(self) -> int:
        return self._settings.embedding_dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages (stored chunks/segments)."""
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query (applies bge's query instruction prefix)."""
        # query_embed yields one vector per query; we pass exactly one.
        return next(iter(self._model.query_embed([text]))).tolist()
