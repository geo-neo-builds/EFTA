"""Entrypoint for the LLM extraction Cloud Run Job.

Processes documents that have status "ocr_complete" — runs Gemini
to extract structured events, people, locations, and victims.
"""

import logging
import sys
from datetime import datetime, timezone

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import ProcessingStatus
from pipeline.extraction.entity_resolver import EntityResolver
from pipeline.extraction.llm_extractor import LLMExtractor
from pipeline.ocr.text_store import TextStore
from pipeline.privacy.redactor import Redactor
from pipeline.privacy.victim_tracker import VictimTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting LLM extraction pipeline...")

    db = FirestoreClient()
    text_store = TextStore()
    extractor = LLMExtractor()
    victim_tracker = VictimTracker(firestore_client=db)
    resolver = EntityResolver(victim_tracker=victim_tracker, firestore_client=db)
    redactor = Redactor(victim_tracker=victim_tracker, firestore_client=db)

    # Get all documents ready for extraction
    documents = db.list_documents(status=ProcessingStatus.OCR_COMPLETE, limit=500)
    logger.info("Found %d documents to extract", len(documents))

    success_count = 0
    error_count = 0

    for doc in documents:
        try:
            # Update status
            doc.processing_status = ProcessingStatus.ANALYSIS_PROCESSING
            db.upsert_document(doc)

            # Load the OCR/transcription text
            pages = text_store.get_page_texts(doc.id)
            if not pages:
                logger.warning("No text found for document %s, skipping", doc.id)
                doc.processing_status = ProcessingStatus.ANALYSIS_FAILED
                doc.error_message = "No OCR text found"
                db.upsert_document(doc)
                error_count += 1
                continue

            logger.info("Extracting from %s (%d pages)", doc.filename, len(pages))

            # Run LLM extraction
            extraction = extractor.extract_from_document(pages)

            if not extraction.events and not extraction.people:
                logger.info("No events extracted from %s", doc.filename)

            # Resolve entities and store in Firestore
            events = resolver.resolve_and_store(extraction, document_id=doc.id)

            # Run redaction check on all created events
            leak_count = 0
            for event in events:
                leaks = redactor.check_event(event.model_dump())
                if leaks:
                    leak_count += 1
                    logger.warning(
                        "PRIVACY LEAK in event %s: %s — applying redaction",
                        event.id,
                        leaks,
                    )
                    # Redact the leaking fields
                    event.what_description = redactor.redact_text(event.what_description)
                    event.raw_text_excerpt = redactor.redact_text(event.raw_text_excerpt)
                    if event.motive_description:
                        event.motive_description = redactor.redact_text(event.motive_description)
                    db.upsert_event(event)

            if leak_count:
                logger.warning("Redacted %d events for document %s", leak_count, doc.id)

            # Update document status
            doc.processing_status = ProcessingStatus.ANALYZED
            doc.analysis_completed_at = datetime.now(timezone.utc)
            doc.error_message = None
            db.upsert_document(doc)

            success_count += 1
            logger.info(
                "Extracted %d events from %s", len(events), doc.filename
            )

        except Exception as e:
            error_count += 1
            doc.processing_status = ProcessingStatus.ANALYSIS_FAILED
            doc.error_message = str(e)[:500]
            db.upsert_document(doc)
            logger.exception("Failed to extract from: %s", doc.filename)

    logger.info(
        "Extraction complete. Success: %d, Errors: %d",
        success_count,
        error_count,
    )

    # Run a full privacy audit at the end
    logger.info("Running privacy audit...")
    findings = redactor.audit_all_events()
    if findings:
        logger.warning("Privacy audit found %d potential leaks!", len(findings))
        for f in findings:
            logger.warning("  Event %s: %s", f["event_id"], f["leaks"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Extraction pipeline failed")
        sys.exit(1)
