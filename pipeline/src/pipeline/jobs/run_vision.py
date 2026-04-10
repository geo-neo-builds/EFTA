"""Entrypoint for the Gemini Vision processing job.

Used for evidence photographs and other image-heavy documents where the
content is visual rather than textual. Sends each page to Gemini Vision
and stores structured results in Firestore + GCS.

Usage:
    python -m pipeline.jobs.run_vision           # process all DOWNLOADED docs
    python -m pipeline.jobs.run_vision 50        # only process first 50 docs
"""

from __future__ import annotations

import logging
import sys

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import ProcessingStatus
from pipeline.vision.processor import VisionProcessor
from pipeline.vision.resolver import VisionResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting Gemini Vision pipeline...")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    db = FirestoreClient()
    processor = VisionProcessor()
    resolver = VisionResolver(firestore_client=db)

    # Get documents that need vision processing.
    # Start with DOWNLOADED docs (haven't been touched yet) — vision is the
    # primary processor for image-heavy data sets like Data Set 1.
    documents = db.list_documents(status=ProcessingStatus.DOWNLOADED, limit=limit)
    logger.info("Found %d documents to process", len(documents))

    success_count = 0
    error_count = 0

    for doc in documents:
        try:
            # Mark as processing
            doc.processing_status = ProcessingStatus.VISION_PROCESSING
            db.upsert_document(doc)

            # Run vision analysis
            text_path, results = processor.process_and_store(doc.gcs_path, doc.id)

            # Apply results to the Document
            doc.gcs_vision_path = text_path
            doc, elements = resolver.apply_to_document(doc, results)

            # Persist Document + ImageElements
            doc.processing_status = ProcessingStatus.VISION_COMPLETE
            doc.error_message = None
            db.upsert_document(doc)
            resolver.store_elements(elements)

            success_count += 1
            logger.info(
                "Processed: %s — type=%s, room=%s, elements=%d, exhibit_marker=%s%s",
                doc.filename,
                doc.document_type.value if doc.document_type else "?",
                doc.room_type.value if doc.room_type else "?",
                len(elements),
                doc.is_exhibit_marker,
                f", label={doc.exhibit_label}" if doc.exhibit_label else "",
            )

        except Exception as e:
            error_count += 1
            doc.processing_status = ProcessingStatus.VISION_FAILED
            doc.error_message = str(e)[:500]
            db.upsert_document(doc)
            logger.exception("Failed to process: %s", doc.filename)

    logger.info(
        "Vision pipeline complete. Success: %d, Errors: %d",
        success_count,
        error_count,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Vision pipeline failed")
        sys.exit(1)
