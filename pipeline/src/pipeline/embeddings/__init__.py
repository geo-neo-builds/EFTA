"""Text embeddings + chunking for EFTA.

Supports two backends:
  - "gemini": Gemini API (gemini-embedding-001) — fast, requires API key
  - "local":  BGE-small via sentence-transformers — free, slow on CPU/MPS
"""

from __future__ import annotations

from pipeline.embeddings.local_embedder import EmbeddingBatch  # noqa: F401


def get_embedder(backend: str | None = None, eager: bool = False):
    """Factory that returns the configured embedder."""
    if backend is None:
        from pipeline.config import config
        backend = config.embed_backend

    if backend == "gemini":
        from pipeline.embeddings.gemini_embedder import GeminiEmbedder
        return GeminiEmbedder()
    else:
        from pipeline.embeddings.local_embedder import LocalEmbedder
        return LocalEmbedder(eager=eager)
