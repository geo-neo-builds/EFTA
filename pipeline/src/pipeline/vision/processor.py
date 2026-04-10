"""Gemini Vision processor for image-based document analysis.

Used for evidence photographs (e.g., FBI raid photos) where the actual
content is visual rather than textual. Sends images directly to Gemini
2.5 Flash for structured analysis.
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types
from google.cloud import storage
from pdf2image import convert_from_bytes
from PIL import Image

from pipeline.config import config
from pipeline.vision.prompts import VISION_EXTRACTION_PROMPT, VISION_SYSTEM_PROMPT
from pipeline.vision.schema import VisionResult

logger = logging.getLogger(__name__)

# Resolution for PDF rendering — 150 DPI is a good balance for vision quality vs cost
PDF_RENDER_DPI = 150

# Cap on image dimensions sent to Gemini (it will resize automatically anyway)
MAX_IMAGE_DIMENSION = 1568


class VisionProcessor:
    """Analyzes documents as images using Gemini Vision."""

    def __init__(self, storage_client: storage.Client | None = None):
        self._client = genai.Client(
            vertexai=True,
            project=config.gcp_project_id,
            location=config.gcp_region,
        )
        self._model = config.gemini_model
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    def process_document(self, gcs_path: str) -> list[VisionResult]:
        """Analyze each page of a document and return one VisionResult per page.

        Args:
            gcs_path: Path within the GCS bucket (e.g., "originals/doj/file.pdf")

        Returns:
            A list of VisionResult, one per page.
        """
        logger.info("Vision processing: %s", gcs_path)

        # Download from GCS
        blob = self._bucket.blob(gcs_path)
        content = blob.download_as_bytes()

        # Convert to images
        suffix = Path(gcs_path).suffix.lower()
        if suffix == ".pdf":
            images = convert_from_bytes(content, dpi=PDF_RENDER_DPI)
        elif suffix in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif"):
            images = [Image.open(io.BytesIO(content))]
        else:
            raise ValueError(f"Unsupported file type for vision: {suffix}")

        logger.info("  %d page(s) to analyze", len(images))

        results = []
        for i, image in enumerate(images):
            try:
                result = self._analyze_image(image, page_number=i + 1)
                results.append(result)
            except Exception:
                logger.exception("Failed to analyze page %d", i + 1)
                # Append an empty result so page numbers stay aligned
                results.append(VisionResult())

        return results

    def process_and_store(
        self, gcs_path: str, document_id: str
    ) -> tuple[str, list[VisionResult]]:
        """Analyze a document and store the vision results in GCS.

        Returns:
            A tuple of (gcs path of vision results JSON, list of per-page VisionResults)
        """
        results = self.process_document(gcs_path)

        # Store as JSON in GCS, parallel to ocr_result.json
        output_path = f"text/{document_id}/vision_result.json"
        output_blob = self._bucket.blob(output_path)
        output_blob.upload_from_string(
            json.dumps(
                {
                    "page_count": len(results),
                    "pages": [r.model_dump() for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            content_type="application/json",
        )

        logger.info(
            "Vision results stored at gs://%s/%s",
            config.gcs_bucket_name, output_path,
        )
        return output_path, results

    def _analyze_image(self, image: Image.Image, page_number: int) -> VisionResult:
        """Send a single image to Gemini Vision and parse the structured response."""
        # Resize if too large (Gemini has token limits per image)
        image = self._resize_if_needed(image)

        # Convert to bytes for the API
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        image_bytes = buf.getvalue()

        # Build the request with the image as inline data
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                VISION_EXTRACTION_PROMPT,
            ],
            config=types.GenerateContentConfig(
                system_instruction=VISION_SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )

        # Parse JSON response
        try:
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            return VisionResult(**data)
        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "Failed to parse vision response for page %d: %s",
                page_number, (response.text or "")[:500],
            )
            return VisionResult()

    @staticmethod
    def _resize_if_needed(image: Image.Image) -> Image.Image:
        """Resize image so its longest side is at most MAX_IMAGE_DIMENSION."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        w, h = image.size
        longest = max(w, h)
        if longest <= MAX_IMAGE_DIMENSION:
            return image
        scale = MAX_IMAGE_DIMENSION / longest
        new_size = (int(w * scale), int(h * scale))
        return image.resize(new_size, Image.Resampling.LANCZOS)
