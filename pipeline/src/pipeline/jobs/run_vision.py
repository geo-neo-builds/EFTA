"""Entrypoint for the Gemini Vision processing job.

Used for evidence photographs and other image-heavy documents where the
content is visual rather than textual. Sends each page to Gemini Vision
and stores structured results in Firestore + GCS.

Usage:
    python -m pipeline.jobs.run_vision                    # process up to 500 docs (default)
    python -m pipeline.jobs.run_vision 50                 # only first 50 docs
    python -m pipeline.jobs.run_vision 5000 10            # 5000 docs with 10 parallel workers
    python -m pipeline.jobs.run_vision all 5              # all docs with 5 parallel workers
"""

from __future__ import annotations

import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Document, ProcessingStatus
from pipeline.vision.embeddings import EmbeddingProcessor
from pipeline.vision.processor import VisionProcessor
from pipeline.vision.resolver import VisionResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Default parallelism — keeps us well below typical Vertex AI quota of 1000+ RPM
DEFAULT_WORKERS = 5

# Retry settings for transient errors (rate limits, timeouts)
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 5

# Counters protected by a lock for the worker threads
_lock = threading.Lock()
_progress = {"success": 0, "error": 0, "total": 0}


def main():
    args = sys.argv[1:]
    if args and args[0] == "all":
        limit = 100_000  # effectively unlimited
        workers = int(args[1]) if len(args) > 1 else DEFAULT_WORKERS
    else:
        limit = int(args[0]) if args else 500
        workers = int(args[1]) if len(args) > 1 else DEFAULT_WORKERS

    logger.info(
        "Starting Gemini Vision pipeline (limit=%d, workers=%d)",
        limit, workers,
    )

    db = FirestoreClient()
    processor = VisionProcessor()
    embedder = EmbeddingProcessor()
    resolver = VisionResolver(firestore_client=db)

    documents = db.list_documents(status=ProcessingStatus.DOWNLOADED, limit=limit)
    _progress["total"] = len(documents)
    logger.info("Found %d documents to process", len(documents))

    if not documents:
        logger.info("Nothing to do.")
        return

    # Run in parallel
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_process_one, doc, db, processor, embedder, resolver): doc
            for doc in documents
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                # Per-doc errors are already logged inside _process_one
                pass

    logger.info(
        "Vision pipeline complete. Success: %d, Errors: %d",
        _progress["success"],
        _progress["error"],
    )


def _process_one(
    doc: Document,
    db: FirestoreClient,
    processor: VisionProcessor,
    embedder: EmbeddingProcessor,
    resolver: VisionResolver,
) -> None:
    """Process a single document with retry on transient errors."""
    backoff = INITIAL_BACKOFF_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            # Mark as processing
            doc.processing_status = ProcessingStatus.VISION_PROCESSING
            db.upsert_document(doc)

            # Vision analysis
            text_path, results = processor.process_and_store(doc.gcs_path, doc.id)

            # Embedding generation
            embedding = embedder.embed_document(doc.gcs_path)
            if embedding is not None:
                doc.embedding = embedding

            # Resolve into Document fields and ImageElements
            doc.gcs_vision_path = text_path
            doc, elements = resolver.apply_to_document(doc, results)

            doc.processing_status = ProcessingStatus.VISION_COMPLETE
            doc.error_message = None
            db.upsert_document(doc)
            resolver.store_elements(elements)

            with _lock:
                _progress["success"] += 1
                done = _progress["success"] + _progress["error"]

            embedding_status = "ok" if doc.embedding else "skipped"
            logger.info(
                "[%d/%d] %s — type=%s, room=%s, elements=%d, marker=%s, emb=%s%s",
                done, _progress["total"],
                doc.filename,
                doc.document_type.value if doc.document_type else "?",
                doc.room_type.value if doc.room_type else "?",
                len(elements),
                doc.is_exhibit_marker,
                embedding_status,
                f", label={doc.exhibit_label}" if doc.exhibit_label else "",
            )
            return  # success

        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            is_rate_limit = (
                "429" in err_str
                or "rate limit" in err_str
                or "quota" in err_str
                or "resource exhausted" in err_str
            )

            if attempt < MAX_RETRIES - 1 and is_rate_limit:
                # Add jitter to avoid thundering herd
                wait = backoff + random.uniform(0, backoff)
                logger.warning(
                    "[%s] Rate limit (attempt %d/%d), backing off %.1fs: %s",
                    doc.filename, attempt + 1, MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
                backoff *= 2
                continue
            break  # non-retriable or out of retries

    # All retries exhausted — record failure
    with _lock:
        _progress["error"] += 1
        done = _progress["success"] + _progress["error"]
    doc.processing_status = ProcessingStatus.VISION_FAILED
    doc.error_message = str(last_error)[:500] if last_error else "unknown error"
    db.upsert_document(doc)
    logger.error(
        "[%d/%d] FAILED: %s — %s",
        done, _progress["total"], doc.filename, last_error,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Vision pipeline failed")
        sys.exit(1)
