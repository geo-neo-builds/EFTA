"""Gemini text embeddings via Vertex AI (gemini-embedding-001).

Uses the google-genai SDK in Vertex AI mode, which bills to the GCP
project's billing account (where the $1,000 GenAI credit lives).
Requires `gcloud auth application-default login`.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from pipeline.embeddings.local_embedder import EmbeddingBatch

logger = logging.getLogger(__name__)

MODEL = "gemini-embedding-001"


class GeminiEmbedder:
    """Wraps the Gemini embedding API (via Vertex AI) with the same interface as LocalEmbedder."""

    def __init__(
        self,
        model: str = MODEL,
        output_dimensionality: int | None = None,
        project: str | None = None,
        location: str | None = None,
    ):
        from pipeline.config import config

        self.model = model
        self.output_dimensionality = output_dimensionality or config.embed_dim
        self._project = project or config.gcp_project_id
        self._location = location or config.gcp_region
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        from google import genai
        self._client = genai.Client(
            vertexai=True,
            project=self._project,
            location=self._location,
        )
        logger.info(
            "Gemini embedding client ready (model=%s, dim=%d, project=%s, location=%s)",
            self.model, self.output_dimensionality, self._project, self._location,
        )

    def embed(
        self,
        texts: list[str],
        batch_size: int = 100,
        show_progress: bool = False,
    ) -> EmbeddingBatch:
        self._ensure_client()

        all_vectors = []
        total = len(texts)

        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]
            vectors = self._embed_batch_with_retry(batch)
            all_vectors.append(vectors)

            if show_progress and (i + batch_size) % (batch_size * 10) == 0:
                logger.info("Embedded %d / %d chunks", min(i + batch_size, total), total)

            # Pace to stay under Vertex AI per-minute token quota.
            if i + batch_size < total:
                time.sleep(1.0)

        result = np.vstack(all_vectors).astype(np.float32)
        # Gemini returns normalized vectors, but enforce just in case.
        norms = np.linalg.norm(result, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        result = result / norms

        return EmbeddingBatch(vectors=result, model_name=self.model)

    def _embed_batch_with_retry(
        self, texts: list[str], max_attempts: int = 10
    ) -> np.ndarray:
        backoff = 5.0
        for attempt in range(1, max_attempts + 1):
            try:
                result = self._client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config={"output_dimensionality": self.output_dimensionality},
                )
                return np.array(
                    [e.values for e in result.embeddings], dtype=np.float32
                )
            except Exception as e:
                err_str = str(e)
                is_retryable = any(code in err_str for code in ("429", "503", "500", "RESOURCE_EXHAUSTED"))
                if is_retryable and attempt < max_attempts:
                    # Quota resets per-minute; wait long enough to clear it.
                    wait = min(backoff, 120.0)
                    logger.warning(
                        "Gemini embed attempt %d/%d: %s (retry in %.0fs)",
                        attempt, max_attempts, e, wait,
                    )
                    time.sleep(wait)
                    backoff = min(backoff * 2, 120.0)
                    continue
                raise
