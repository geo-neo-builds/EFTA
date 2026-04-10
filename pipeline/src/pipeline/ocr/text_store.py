"""Utilities for reading OCR/transcription results from GCS."""

from __future__ import annotations

import json
import logging

from google.cloud import storage

from pipeline.config import config

logger = logging.getLogger(__name__)


class TextStore:
    """Read and manage extracted text stored in GCS."""

    def __init__(self, storage_client: storage.Client | None = None):
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    def get_text(self, document_id: str) -> dict | None:
        """Load the OCR/transcription result for a document.

        Returns the parsed JSON dict, or None if not found.
        """
        # Try OCR result first
        for filename in ("ocr_result.json", "transcription.json"):
            path = f"text/{document_id}/{filename}"
            blob = self._bucket.blob(path)
            if blob.exists():
                content = blob.download_as_text()
                return json.loads(content)
        return None

    def get_full_text(self, document_id: str) -> str:
        """Get just the full text content for a document."""
        data = self.get_text(document_id)
        if not data:
            return ""
        return data.get("full_text", "")

    def get_page_texts(self, document_id: str) -> list[dict]:
        """Get page-by-page text for a document."""
        data = self.get_text(document_id)
        if not data:
            return []
        return data.get("pages", [])
