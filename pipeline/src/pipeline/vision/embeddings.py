"""Multimodal embeddings for visual similarity search.

Uses Vertex AI's multimodalembedding@001 model to generate a 1408-dimensional
vector for each image. These vectors are stored in Firestore and can be used
to find visually similar photos across the entire dataset (e.g. "find every
photo containing this artwork, even if it's photographed from different angles").

Cost: ~$0.0002 per image (~$0.63 for all 3,158 photos in Data Set 1).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import vertexai
from google.cloud import storage
from pdf2image import convert_from_bytes
from PIL import Image as PILImage
from vertexai.vision_models import Image as VertexImage
from vertexai.vision_models import MultiModalEmbeddingModel

from pipeline.config import config

logger = logging.getLogger(__name__)

# Vertex AI multimodal embedding model
EMBEDDING_MODEL_NAME = "multimodalembedding@001"

# Output dimension — 1408 is the default and best for similarity search.
# Other options are 128, 256, 512 (smaller = faster but less accurate).
EMBEDDING_DIMENSION = 1408

# Image will be downscaled before sending to the API to keep payloads small
EMBEDDING_INPUT_SIZE = 800

# DPI for converting PDF pages to images for embedding
PDF_RENDER_DPI = 100


class EmbeddingProcessor:
    """Generates multimodal embeddings for evidence photos."""

    def __init__(self, storage_client: storage.Client | None = None):
        vertexai.init(
            project=config.gcp_project_id,
            location=config.gcp_region,
        )
        self._model = MultiModalEmbeddingModel.from_pretrained(EMBEDDING_MODEL_NAME)
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    def embed_document(self, gcs_path: str) -> list[float] | None:
        """Generate an embedding for the first page of a document.

        For multi-page documents we only embed the first page since the
        primary use case (visual similarity for evidence photos) treats
        each PDF as a single image.

        Returns:
            A list of 1408 floats, or None on failure.
        """
        logger.info("Embedding: %s", gcs_path)

        # Download from GCS
        blob = self._bucket.blob(gcs_path)
        content = blob.download_as_bytes()

        # Convert to image
        suffix = Path(gcs_path).suffix.lower()
        if suffix == ".pdf":
            images = convert_from_bytes(content, dpi=PDF_RENDER_DPI, first_page=1, last_page=1)
            if not images:
                logger.warning("PDF rendered no pages: %s", gcs_path)
                return None
            pil_image = images[0]
        elif suffix in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"):
            pil_image = PILImage.open(io.BytesIO(content))
        else:
            logger.warning("Unsupported file type for embedding: %s", suffix)
            return None

        # Resize to keep API payload small
        pil_image = self._prepare_image(pil_image)

        # Convert PIL image to PNG bytes for the Vertex AI Image
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG", optimize=True)
        image_bytes = buf.getvalue()

        try:
            vertex_image = VertexImage(image_bytes=image_bytes)
            embeddings = self._model.get_embeddings(
                image=vertex_image,
                dimension=EMBEDDING_DIMENSION,
            )
            return list(embeddings.image_embedding)
        except Exception:
            logger.exception("Embedding API call failed for %s", gcs_path)
            return None

    @staticmethod
    def _prepare_image(image: PILImage.Image) -> PILImage.Image:
        """Convert to RGB and resize so longest side <= EMBEDDING_INPUT_SIZE."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        w, h = image.size
        longest = max(w, h)
        if longest > EMBEDDING_INPUT_SIZE:
            scale = EMBEDDING_INPUT_SIZE / longest
            new_size = (int(w * scale), int(h * scale))
            image = image.resize(new_size, PILImage.Resampling.LANCZOS)
        return image
