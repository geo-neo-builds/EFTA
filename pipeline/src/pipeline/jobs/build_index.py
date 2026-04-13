"""Build the chunk + embedding index from text JSONs already on disk.

Reads every `<SSD>/EFTA/text/set-<N>/.../<doc_id>.json` produced by
`local_ingest`, chunks each page, runs them through BGE-small locally,
and writes documents/pages/chunks/embeddings to the SQLite DB.

Resumable: docs already present in `chunks` are skipped.

Usage:
    python -m pipeline.jobs.build_index 8
    python -m pipeline.jobs.build_index 8 --limit 100
    python -m pipeline.jobs.build_index all        # process every set-* dir
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from pipeline.embeddings.chunker import chunk_document
from pipeline.embeddings.local_embedder import LocalEmbedder
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import DocumentRecord, SQLiteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# How many chunks we embed per model.encode() call. Bigger batches are
# more efficient on MPS/CUDA up to a point; 128 is a safe default on
# Apple Silicon.
EMBED_BATCH = 128


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
    args = parser.parse_args()

    paths = load_paths()
    paths.ensure()
    store = SQLiteStore(paths.db_file)

    already_indexed = store.existing_doc_ids("SELECT DISTINCT doc_id FROM chunks")
    logger.info("%d docs already indexed", len(already_indexed))

    text_files = list(iter_text_jsons(paths.text, args.data_set))
    logger.info("Found %d text JSONs to consider", len(text_files))

    embedder = LocalEmbedder()

    # Accumulate chunks across documents so we can amortize model calls
    # by embedding in large batches rather than one doc at a time.
    buf_chunks = []
    buf_doc_ranges: list[tuple[str, int, int]] = []  # (doc_id, start, end) in buf_chunks
    processed = 0
    t0 = time.time()

    def flush():
        nonlocal buf_chunks, buf_doc_ranges
        if not buf_chunks:
            return
        texts = [c.text for c in buf_chunks]
        batch = embedder.embed(texts, batch_size=EMBED_BATCH, show_progress=False)
        vectors = batch.vectors
        for (doc_id, start, end) in buf_doc_ranges:
            chunks_slice = buf_chunks[start:end]
            vec_slice = vectors[start:end]
            store.insert_chunks(chunks_slice, vec_slice)
        buf_chunks = []
        buf_doc_ranges = []

    for tf in text_files:
        if args.limit and processed >= args.limit:
            break

        try:
            record = json.loads(tf.read_text())
        except Exception as e:
            logger.warning("Bad JSON %s: %s", tf.name, e)
            continue

        doc_id = record["doc_id"]
        if doc_id in already_indexed:
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

        if len(buf_chunks) >= 512:
            flush()
            logger.info(
                "[%d] flushed | elapsed=%.1fs", processed, time.time() - t0,
            )

    flush()
    logger.info("Done. %d docs indexed in %.1fs. stats=%s",
                processed, time.time() - t0, store.stats())
    store.close()


if __name__ == "__main__":
    main()
