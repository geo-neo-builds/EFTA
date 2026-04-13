"""Run spaCy + regex entity extraction over the text JSON archive.

Reads every `<SSD>/EFTA/text/set-<N>/.../<doc_id>.json` and writes
extracted entities to SQLite. Resumable: skips docs that already have
entity rows.

Usage:
    python -m pipeline.jobs.extract_entities 8
    python -m pipeline.jobs.extract_entities 8 --limit 50
    python -m pipeline.jobs.extract_entities all
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from pipeline.entities.extractor import EntityExtractor
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import SQLiteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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

    already_done = store.existing_doc_ids("SELECT DISTINCT doc_id FROM entities")
    logger.info("%d docs already have entities", len(already_done))

    text_files = list(iter_text_jsons(paths.text, args.data_set))
    logger.info("Found %d text JSONs", len(text_files))

    extractor = EntityExtractor()
    processed = 0
    total_entities = 0
    t0 = time.time()

    for tf in text_files:
        if args.limit and processed >= args.limit:
            break
        try:
            record = json.loads(tf.read_text())
        except Exception as e:
            logger.warning("Bad JSON %s: %s", tf.name, e)
            continue

        doc_id = record["doc_id"]
        if doc_id in already_done:
            continue
        if not record.get("pages"):
            continue

        pages = [(p["page_number"], p["text"]) for p in record["pages"] if p.get("text")]
        entities = extractor.extract_document(pages)

        rows = [
            (e.page_number, e.entity_type, e.value, e.normalized_value,
             e.char_start, e.char_end)
            for e in entities
        ]
        store.replace_entities(doc_id, rows)

        processed += 1
        total_entities += len(rows)
        if processed % 25 == 0 or processed == 1:
            logger.info(
                "[%d] %s → %d entities (total=%d, elapsed=%.1fs)",
                processed, doc_id, len(rows), total_entities, time.time() - t0,
            )

    logger.info("Done. %d docs, %d entities in %.1fs. stats=%s",
                processed, total_entities, time.time() - t0, store.stats())
    store.close()


if __name__ == "__main__":
    main()
