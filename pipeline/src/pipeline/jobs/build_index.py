"""Build the chunk + embedding index from text JSONs already on disk.

Reads every `<SSD>/EFTA/text/set-<N>/.../<doc_id>.json` produced by
`local_ingest`, chunks each page, embeds them (Gemini API or local BGE),
and writes documents/pages/chunks/embeddings to the SQLite DB.

Resumable: docs already present in `chunks` are skipped.

Usage:
    python -m pipeline.jobs.build_index 8
    python -m pipeline.jobs.build_index 8 --limit 100
    python -m pipeline.jobs.build_index all
    python -m pipeline.jobs.build_index all --reset   # re-embed with new model
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from pipeline.config import config
from pipeline.embeddings import get_embedder
from pipeline.embeddings.chunker import chunk_document
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import DocumentRecord, SQLiteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


EMBED_BATCH = 100  # texts per API call (Gemini optimal; also fine for local)


def iter_text_jsons(text_root: Path, set_filter: str):
    if set_filter == "all":
        for set_dir in sorted(text_root.glob("set-*")):
            yield from set_dir.rglob("*.json")
    else:
        set_dir = text_root / f"set-{set_filter}"
        if not set_dir.exists():
            raise SystemExit(f"text dir not found: {set_dir}")
        yield from set_dir.rglob("*.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_set", help="data set number, e.g. 8, or 'all'")
    parser.add_argument("--limit", type=int, default=None, help="cap docs processed")
    parser.add_argument("--reset", action="store_true",
                        help="drop all chunks/vectors and re-index from scratch")
    args = parser.parse_args()

    paths = load_paths()
    paths.ensure()
    store = SQLiteStore(paths.db_file, embed_dim=config.embed_dim)

    if args.reset:
        store.reset_chunks()

    already_indexed = store.existing_doc_ids("SELECT DISTINCT doc_id FROM chunks")
    logger.info("%d docs already indexed", len(already_indexed))

    embedder = get_embedder()
    logger.info("Embedder: %s (dim=%d)", config.embed_backend, config.embed_dim)

    buf_chunks = []
    buf_doc_ranges: list[tuple[str, int, int]] = []
    processed = 0
    skipped = 0
    total_chunks = 0
    t0 = time.time()
    last_log = t0

    def flush():
        nonlocal buf_chunks, buf_doc_ranges
        if not buf_chunks:
            return
        texts = [c.text for c in buf_chunks]
        batch = embedder.embed(texts, batch_size=EMBED_BATCH, show_progress=False)
        vectors = batch.vectors
        for (doc_id, start, end) in buf_doc_ranges:
            store.insert_chunks(buf_chunks[start:end], vectors[start:end])
        buf_chunks = []
        buf_doc_ranges = []

    for tf in iter_text_jsons(paths.text, args.data_set):
        if args.limit and processed >= args.limit:
            break

        try:
            record = json.loads(tf.read_text())
        except Exception as e:
            logger.warning("Bad JSON %s: %s", tf.name, e)
            continue

        doc_id = record["doc_id"]
        if doc_id in already_indexed:
            skipped += 1
            continue
        if not record.get("has_text_layer") or not record.get("pages"):
            continue

        pages = [(p["page_number"], p["text"]) for p in record["pages"] if p.get("text")]
        store.upsert_document(
            DocumentRecord(
                doc_id=doc_id,
                data_set=int(record["data_set"]),
                filename=record["filename"],
                source_url=record["source_url"],
                page_count=int(record["page_count"]),
                total_chars=int(record["total_chars"]),
            ),
            pages,
        )

        chunks = chunk_document(doc_id, pages)
        if not chunks:
            continue

        start = len(buf_chunks)
        buf_chunks.extend(chunks)
        buf_doc_ranges.append((doc_id, start, len(buf_chunks)))
        processed += 1
        total_chunks += len(chunks)

        if len(buf_chunks) >= 2000:
            flush()

        now = time.time()
        if now - last_log >= 10.0:
            rate = processed / max(now - t0, 1e-3)
            logger.info(
                "[%d docs, %d chunks, %d skipped] %.1f docs/s | elapsed=%.1fs",
                processed, total_chunks, skipped, rate, now - t0,
            )
            last_log = now

    flush()
    elapsed = time.time() - t0
    logger.info("Done. %d docs, %d chunks indexed in %.1fs (%.1f docs/s). stats=%s",
                processed, total_chunks, elapsed, processed / max(elapsed, 1e-3),
                store.stats())
    store.close()


if __name__ == "__main__":
    main()
