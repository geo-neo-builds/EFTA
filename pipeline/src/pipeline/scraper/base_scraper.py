"""Base scraper with common functionality."""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from google.cloud import storage

from pipeline.config import config
from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Document, ProcessingStatus, SourceType

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for document scrapers."""

    def __init__(
        self,
        firestore_client: FirestoreClient | None = None,
        storage_client: storage.Client | None = None,
    ):
        self.db = firestore_client or FirestoreClient()
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        ...

    @abstractmethod
    def discover_documents(self) -> list[dict]:
        """Return list of dicts with keys: url, filename, title."""
        ...

    def run(self) -> list[Document]:
        """Discover and download new/updated documents."""
        discovered = self.discover_documents()
        logger.info("Discovered %d documents from %s", len(discovered), self.source_type.value)

        results = []
        for doc_info in discovered:
            try:
                doc = self._process_document(doc_info)
                if doc:
                    results.append(doc)
            except Exception:
                logger.exception("Failed to process document: %s", doc_info.get("url"))

        logger.info("Processed %d new/updated documents", len(results))
        return results

    def _process_document(self, doc_info: dict) -> Document | None:
        url = doc_info["url"]
        filename = doc_info["filename"]

        # Check if we already have this document
        existing = self.db.get_document_by_url(url)

        # Download the file
        content = self._download(url)
        if content is None:
            logger.warning("Failed to download: %s", url)
            return None

        file_hash = hashlib.sha256(content).hexdigest()

        # Skip if unchanged
        if existing and existing.file_hash == file_hash:
            logger.debug("Unchanged: %s", filename)
            # Update last_checked_at
            existing.last_checked_at = datetime.now(timezone.utc)
            self.db.upsert_document(existing)
            return None

        # Upload to GCS
        gcs_path = f"originals/{self.source_type.value}/{filename}"
        blob = self._bucket.blob(gcs_path)
        blob.upload_from_string(content, content_type="application/pdf")
        logger.info("Uploaded to gs://%s/%s", config.gcs_bucket_name, gcs_path)

        now = datetime.now(timezone.utc)

        if existing:
            # Document changed (e.g., unredacted version released)
            existing.file_hash = file_hash
            existing.gcs_path = gcs_path
            existing.processing_status = ProcessingStatus.DOWNLOADED
            existing.version = existing.version + 1
            existing.last_checked_at = now
            existing.error_message = None
            self.db.upsert_document(existing)
            logger.info("Updated document (v%d): %s", existing.version, filename)
            return existing
        else:
            # New document
            doc_id = hashlib.md5(url.encode()).hexdigest()[:16]
            doc = Document(
                id=doc_id,
                source_url=url,
                source_type=self.source_type,
                filename=filename,
                gcs_path=gcs_path,
                download_date=now,
                file_hash=file_hash,
                processing_status=ProcessingStatus.DOWNLOADED,
                last_checked_at=now,
            )
            self.db.upsert_document(doc)
            logger.info("New document: %s", filename)
            return doc

    @abstractmethod
    def _download(self, url: str) -> bytes | None:
        """Download file content from URL."""
        ...
