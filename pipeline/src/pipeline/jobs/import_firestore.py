"""Pull Set 1 image analysis data from Firestore into local SQLite.

Imports properties, exhibits, documents (with vision metadata), and
image_elements so that photo data is searchable alongside text docs.

Usage:
    python -m pipeline.jobs.import_firestore
    python -m pipeline.jobs.import_firestore --limit 100
"""

from __future__ import annotations

import argparse
import logging
import time

from pipeline.config import config
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import SQLiteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_firestore_client():
    from google.cloud import firestore
    return firestore.Client(
        project=config.gcp_project_id,
        database=config.firestore_database,
    )


def import_properties(db: firestore.Client, store: SQLiteStore) -> int:
    """Import all properties."""
    count = 0
    for doc in db.collection("properties").stream():
        d = doc.to_dict()
        store.conn.execute(
            """INSERT OR REPLACE INTO properties
               (property_id, name, nickname, address, city, state, country,
                photo_count, exhibit_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.id,
                d.get("name", ""),
                d.get("nickname"),
                d.get("address"),
                d.get("city"),
                d.get("state"),
                d.get("country"),
                d.get("photo_count", 0),
                d.get("exhibit_count", 0),
            ),
        )
        count += 1
    logger.info("Imported %d properties", count)
    return count


def import_exhibits(db: firestore.Client, store: SQLiteStore) -> int:
    """Import all exhibits."""
    count = 0
    for doc in db.collection("exhibits").stream():
        d = doc.to_dict()
        store.conn.execute(
            """INSERT OR REPLACE INTO exhibits
               (exhibit_id, label, property_id, room_type, photo_count,
                location_address, case_id, photo_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.id,
                d.get("label", ""),
                d.get("property_id"),
                d.get("room_type"),
                d.get("photo_count", 0),
                d.get("location_address"),
                d.get("case_id"),
                d.get("photo_date"),
            ),
        )
        count += 1
    logger.info("Imported %d exhibits", count)
    return count


def import_documents(db: firestore.Client, store: SQLiteStore,
                     limit: int | None = None) -> int:
    """Import Set 1 vision-complete documents into the documents table.

    Adds vision-specific fields (room_type, document_summary, etc.) and
    creates chunks from the vision summary so they're searchable via FTS.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    # Check what's already imported
    existing = {
        r[0] for r in store.conn.execute(
            "SELECT doc_id FROM documents WHERE data_set = 1"
        )
    }

    count = 0
    element_count = 0
    t0 = time.time()
    batch_size = 500
    last_doc = None

    while True:
        query = (
            db.collection("documents")
            .where(filter=FieldFilter("processing_status", "==", "vision_complete"))
            .order_by("__name__")
            .limit(batch_size)
        )
        if last_doc:
            query = query.start_after(last_doc)

        batch = list(query.get())
        if not batch:
            break

        for doc in batch:
            d = doc.to_dict()
            doc_id = doc.id
            if doc_id in existing:
                continue

            # Build searchable text from vision analysis
            summary = d.get("document_summary") or d.get("vision_summary") or ""
            element_cats = d.get("element_categories", [])
            room = d.get("room_type", "unknown")
            people_count = d.get("people_count", 0)

            search_text_parts = [summary]
            if element_cats:
                search_text_parts.append("Elements: " + ", ".join(element_cats))
            if room and room != "unknown":
                search_text_parts.append(f"Room: {room}")
            if people_count:
                search_text_parts.append(f"People visible: {people_count}")
            address = d.get("photo_location_address", "")
            if address:
                search_text_parts.append(f"Location: {address}")

            search_text = "\n".join(search_text_parts)

            store.conn.execute(
                """INSERT OR REPLACE INTO documents
                   (doc_id, data_set, filename, source_url, page_count,
                    total_chars, doc_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, 1, d.get("filename", f"{doc_id}.pdf"),
                 d.get("source_url", ""), d.get("page_count", 1),
                 len(search_text), "photograph"),
            )
            store.conn.execute(
                """INSERT OR REPLACE INTO pages
                   (doc_id, page_number, text, char_count)
                   VALUES (?, ?, ?, ?)""",
                (doc_id, 1, search_text, len(search_text)),
            )
            store.conn.execute(
                """INSERT OR REPLACE INTO chunks
                   (doc_id, page_number, sub_chunk_index, text, char_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (doc_id, 1, 0, search_text, len(search_text)),
            )
            cid = store.conn.last_insert_rowid()
            store.conn.execute(
                "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                (cid, search_text),
            )

            # Import image elements for this document
            for elem_doc in db.collection("image_elements").where(
                filter=FieldFilter("document_id", "==", doc_id)
            ).get():
                ed = elem_doc.to_dict()
                store.conn.execute(
                    """INSERT OR REPLACE INTO image_elements
                       (element_id, doc_id, category, description, notable,
                        title, creator, quantity, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (elem_doc.id, doc_id, ed.get("category", "other"),
                     ed.get("description"), 1 if ed.get("notable") else 0,
                     ed.get("title"), ed.get("creator"),
                     ed.get("quantity", 1), ed.get("confidence")),
                )
                element_count += 1

            count += 1
            if limit and count >= limit:
                break
            if count % 50 == 0:
                elapsed = time.time() - t0
                logger.info(
                    "[%d docs, %d elements] %.1f docs/s | elapsed=%.1fs",
                    count, element_count, count / max(elapsed, 0.001), elapsed,
                )

        last_doc = batch[-1]
        if limit and count >= limit:
            break
        if len(batch) < batch_size:
            break

    logger.info(
        "Imported %d documents and %d image elements from Firestore",
        count, element_count,
    )
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="cap documents imported")
    args = parser.parse_args()

    paths = load_paths()
    paths.ensure()
    store = SQLiteStore(paths.db_file, embed_dim=config.embed_dim)

    db = get_firestore_client()
    logger.info("Connected to Firestore (project=%s)", config.gcp_project_id)

    import_properties(db, store)
    import_exhibits(db, store)
    import_documents(db, store, limit=args.limit)

    logger.info("Done. DB stats: %s", store.stats())
    store.close()


if __name__ == "__main__":
    main()
