"""Entrypoint for the OCR/transcription Cloud Run Job.

Processes documents that have status "downloaded" — runs OCR on PDFs
and Speech-to-Text on audio files.
"""

import json
import logging
import sys

from google.cloud import pubsub_v1

from pipeline.config import config
from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import ProcessingStatus
from pipeline.ocr.audio_transcriber import AudioTranscriber
from pipeline.ocr.processor import OCRProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting OCR/transcription processor...")

    db = FirestoreClient()
    ocr = OCRProcessor()
    transcriber = AudioTranscriber()
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(config.gcp_project_id, config.pubsub_topic_ocr_complete)

    # Get all documents waiting for OCR
    documents = db.list_documents(status=ProcessingStatus.DOWNLOADED, limit=500)
    logger.info("Found %d documents to process", len(documents))

    success_count = 0
    error_count = 0

    for doc in documents:
        try:
            # Update status to processing
            doc.processing_status = ProcessingStatus.OCR_PROCESSING
            db.upsert_document(doc)

            # Route to appropriate processor
            if AudioTranscriber.is_audio_file(doc.gcs_path):
                logger.info("Transcribing audio: %s", doc.filename)
                text_path = transcriber.transcribe_and_store(doc.gcs_path, doc.id)
            else:
                logger.info("Running OCR: %s", doc.filename)
                text_path = ocr.process_and_store(doc.gcs_path, doc.id)

            # Update document status
            doc.processing_status = ProcessingStatus.OCR_COMPLETE
            doc.gcs_text_path = text_path
            doc.error_message = None
            db.upsert_document(doc)

            # Publish to Pub/Sub
            message = json.dumps({"document_id": doc.id}).encode("utf-8")
            publisher.publish(topic_path, message)

            success_count += 1
            logger.info("Processed: %s", doc.filename)

        except Exception as e:
            error_count += 1
            doc.processing_status = ProcessingStatus.OCR_FAILED
            doc.error_message = str(e)[:500]
            db.upsert_document(doc)
            logger.exception("Failed to process: %s", doc.filename)

    logger.info(
        "OCR/transcription complete. Success: %d, Errors: %d",
        success_count,
        error_count,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("OCR processor failed")
        sys.exit(1)
