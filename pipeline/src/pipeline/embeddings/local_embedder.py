"""Local text embeddings via sentence-transformers. Zero cost.

Default model: BAAI/bge-small-en-v1.5 (384 dims, 512-token context).
~130 MB, fast on Apple Silicon, strong on retrieval benchmarks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384  # for DEFAULT_MODEL; update if you switch


@dataclass
class EmbeddingBatch:
    vectors: np.ndarray  # (N, EMBED_DIM) float32, L2-normalized
    model_name: str

    def __len__(self) -> int:
        return self.vectors.shape[0]


class LocalEmbedder:
    """Wraps sentence-transformers with the defaults we want.

    Lazy-loads the model on first use so importing this module doesn't
    download hundreds of MB until we actually embed something.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None):
        self.model_name = model_name
        self.device = device  # None → auto (mps/cuda/cpu)
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers not installed. Run: "
                "pip install -e '.[local]'"
            ) from e
        logger.info("Loading embedding model %s ...", self.model_name)
        self._model = SentenceTransformer(self.model_name, device=self.device)
        logger.info("Model ready (device=%s).", self._model.device)

    def embed(
        self,
        texts: list[str],
        batch_size: int = 64,
        show_progress: bool = False,
    ) -> EmbeddingBatch:
        self._ensure_loaded()
        vectors = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)
        return EmbeddingBatch(vectors=vectors, model_name=self.model_name)
