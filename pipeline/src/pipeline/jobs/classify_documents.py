"""Classify documents by type using rule-based pattern matching.

Reads text JSONs and assigns a doc_type based on content patterns
(email headers, court doc markers, evidence logs, etc.). Stores the
result in the documents table. Resumable: skips docs that already
have a doc_type set.

Usage:
    python -m pipeline.jobs.classify_documents all
    python -m pipeline.jobs.classify_documents 8 --limit 100
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

from pipeline.config import config  # noqa: F401 — ensures .env is loaded
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import SQLiteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Patterns checked in order; first match wins.
RULES: list[tuple[str, re.Pattern | None, list[str]]] = [
    # (doc_type, compiled_regex_or_None, list_of_substring_markers)
    ("email", None, ["From:", "To:", "Subject:"]),
    ("calendar_event", None, ["Event:", "Start Date:", "End Date:", "Organizer:"]),
    ("evidence_log", re.compile(r"FD-\d{3,4}|Evidence\s+Item:|Evidence\s+Type:", re.I), []),
    ("court_order", None, ["ORDER", "IT IS HEREBY ORDERED", "SO ORDERED"]),
    ("court_filing", re.compile(
        r"MOTION|COMPLAINT|INDICTMENT|MEMORANDUM OF LAW|UNITED STATES DISTRICT COURT|"
        r"Case\s+No\.|Docket\s+No\.|CRIMINAL COMPLAINT", re.I
    ), []),
    ("transcript", re.compile(r"\bQ\.\s|A\.\s|THE WITNESS|THE COURT|DIRECT EXAMINATION|CROSS.EXAMINATION", re.I), []),
    ("travel_request", None, ["Travel Request", "travel approval"]),
    ("witness_form", re.compile(r"Fact Witness|Witness Travel|Victim.Witness Unit", re.I), []),
    ("police_report", re.compile(r"POLICE|INCIDENT REPORT|REPORT NO|CASE NUMBER|PALM BEACH", re.I), []),
    ("financial", re.compile(r"INVOICE|RECEIPT|WIRE TRANSFER|BANK STATEMENT|ACCOUNT\s+NO", re.I), []),
    ("fbi_report", re.compile(r"FD-302|FBI\s+REPORT|FEDERAL BUREAU OF INVESTIGATION", re.I), []),
    ("memo", re.compile(r"^MEMORANDUM|^MEMO\b|^TO:\s|^FROM:\s|^RE:\s", re.I | re.M), []),
    ("letter", re.compile(r"^Dear\s|Sincerely|Yours truly|Respectfully", re.I | re.M), []),
]


def classify(text: str) -> str:
    """Return the document type based on the first 2000 chars of text."""
    sample = text[:2000]
    for doc_type, regex, substrings in RULES:
        if substrings:
            # All substrings must be present (AND logic)
            if all(s.lower() in sample.lower() for s in substrings):
                return doc_type
        if regex and regex.search(sample):
            return doc_type
    return "other"


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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    paths = load_paths()
    store = SQLiteStore(paths.db_file, embed_dim=config.embed_dim)

    # Ensure doc_type column exists
    try:
        store.conn.execute("ALTER TABLE documents ADD COLUMN doc_type TEXT DEFAULT NULL")
        logger.info("Added doc_type column to documents table")
    except Exception:
        pass  # Column already exists

    # Get docs that already have a type
    already = {r[0] for r in store.conn.execute(
        "SELECT doc_id FROM documents WHERE doc_type IS NOT NULL"
    )}
    logger.info("%d docs already classified", len(already))

    processed = 0
    counts: dict[str, int] = {}
    t0 = time.time()
    last_log = t0

    for tf in iter_text_jsons(paths.text, args.data_set):
        if args.limit and processed >= args.limit:
            break

        try:
            record = json.loads(tf.read_text())
        except Exception:
            continue

        doc_id = record["doc_id"]
        if doc_id in already:
            continue
        if not record.get("pages"):
            continue

        full_text = " ".join(p["text"] for p in record["pages"] if p.get("text"))
        if not full_text.strip():
            continue

        doc_type = classify(full_text)
        store.conn.execute(
            "UPDATE documents SET doc_type = ? WHERE doc_id = ?",
            (doc_type, doc_id),
        )
        counts[doc_type] = counts.get(doc_type, 0) + 1
        processed += 1

        now = time.time()
        if now - last_log >= 10.0:
            rate = processed / max(now - t0, 1e-3)
            logger.info("[%d classified] %.1f docs/s | %s", processed, rate, dict(counts))
            last_log = now

    elapsed = time.time() - t0
    logger.info("Done. %d docs classified in %.1fs. Breakdown: %s",
                processed, elapsed, dict(counts))
    store.close()


if __name__ == "__main__":
    main()
