"""End-to-end smoke test of the local (zero-cost) pipeline.

Pulls a small sample of PDFs from a DOJ data set listing page, runs the
full download → pypdf → chunk → embed → SQLite path, and then runs a
keyword search and a semantic search against the freshly built DB so we
can eyeball the output before scaling up.

Usage:
    python -m pipeline.jobs.test_local_pipeline              # 5 docs from Set 8
    python -m pipeline.jobs.test_local_pipeline 11 8         # 8 docs from Set 11
"""

from __future__ import annotations

import logging
import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pipeline.embeddings.chunker import chunk_document
from pipeline.embeddings.local_embedder import LocalEmbedder
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import DocumentRecord, SQLiteStore
from pipeline.scraper.doj_scraper import DOJ_BASE_URL, HEADERS
from pipeline.text_extraction.pdf_text_extractor import PDFTextExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def fetch_sample_urls(http: httpx.Client, ds_num: int, n: int) -> list[str]:
    listing_url = f"{DOJ_BASE_URL}/epstein/doj-disclosures/data-set-{ds_num}-files"
    resp = http.get(listing_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("a", href=True):
        full = urljoin(listing_url, link["href"])
        if urlparse(full).path.lower().endswith(".pdf"):
            urls.append(full)
    urls = list(dict.fromkeys(urls))
    return urls[:n]


def main():
    args = sys.argv[1:]
    ds_num = int(args[0]) if args else 8
    n_docs = int(args[1]) if len(args) > 1 else 5

    paths = load_paths()
    paths.ensure()
    logger.info("Using DB at %s", paths.db_file)

    http = httpx.Client(
        headers=HEADERS,
        cookies={"justiceGovAgeVerified": "true"},
        follow_redirects=True,
        timeout=120.0,
    )
    extractor = PDFTextExtractor()
    embedder = LocalEmbedder()
    store = SQLiteStore(paths.db_file)

    urls = fetch_sample_urls(http, ds_num, n_docs)
    logger.info("Fetched %d sample URLs from Data Set %d", len(urls), ds_num)

    all_chunks = []
    for i, url in enumerate(urls, 1):
        filename = url.split("/")[-1].split("?")[0]
        doc_id = filename.removesuffix(".pdf")
        logger.info("[%d/%d] %s", i, len(urls), filename)

        resp = http.get(url)
        resp.raise_for_status()
        result = extractor.extract_from_bytes(resp.content)
        if result.error or not result.has_text_layer:
            logger.warning("  skipping: %s", result.error or "no text layer")
            continue

        pages = [(p.page_number, p.text) for p in result.pages if p.text.strip()]
        doc_chunks = chunk_document(doc_id, pages)
        logger.info("  %d pages → %d chunks", len(pages), len(doc_chunks))

        store.upsert_document(
            DocumentRecord(
                doc_id=doc_id,
                data_set=ds_num,
                filename=filename,
                source_url=url,
                page_count=result.page_count,
                total_chars=result.total_chars,
            ),
            pages,
        )
        all_chunks.extend(doc_chunks)

    if not all_chunks:
        logger.error("No chunks produced — aborting.")
        return

    logger.info("Embedding %d chunks...", len(all_chunks))
    batch = embedder.embed([c.text for c in all_chunks], show_progress=True)
    store.insert_chunks(all_chunks, batch.vectors)

    logger.info("DB stats: %s", store.stats())

    # ---- demo searches ----
    print("\n" + "=" * 70)
    print("  KEYWORD SEARCH DEMO")
    print("=" * 70)
    kq = "Epstein"
    print(f"\n  query: {kq!r}")
    for row in store.keyword_search(kq, limit=5):
        print(f"    [{row['doc_id']} p.{row['page_number']}] {row['snippet']}")

    print("\n" + "=" * 70)
    print("  SEMANTIC SEARCH DEMO")
    print("=" * 70)
    sq = "flight log of a private plane"
    print(f"\n  query: {sq!r}")
    qvec = embedder.embed([sq]).vectors[0]
    for row in store.semantic_search(qvec, limit=5):
        preview = row["text"][:120].replace("\n", " ")
        print(f"    [{row['doc_id']} p.{row['page_number']}] dist={row['distance']:.3f}")
        print(f"      {preview}…")

    store.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
