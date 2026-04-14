"""Download + pypdf-extract every document in a DOJ data set, locally.

Writes per-document JSON to `<SSD>/EFTA/text/<prefix>/<doc_id>.json` with
full per-page text + metadata. The raw PDF is discarded after extraction
(the DOJ URL is preserved in the JSON so users can retrieve the original).

Resumable: any doc whose JSON already exists is skipped. Kill the job
and restart at will.

URL discovery is cached to `<SSD>/EFTA/staging/urls-set-<N>.txt` so
subsequent runs skip the slow listing-page crawl.

Usage:
    python -m pipeline.jobs.local_ingest 8                 # full Set 8
    python -m pipeline.jobs.local_ingest 8 --limit 50      # first 50 docs only
    python -m pipeline.jobs.local_ingest 8 --workers 8     # 8 parallel downloads
    python -m pipeline.jobs.local_ingest 8 --refresh-urls  # re-crawl listings
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pipeline.config import config  # noqa: F401 — ensures .env is loaded
from pipeline.local_storage.paths import load_paths
from pipeline.scraper.doj_scraper import DOJ_BASE_URL, HEADERS
from pipeline.text_extraction.pdf_text_extractor import PDFTextExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


LISTING_DELAY_S = 3.0  # polite delay between paginated listing pages
LISTING_MAX_RETRIES = 6  # on 403, retry with exponential backoff


def _fetch_listing(http: httpx.Client, url: str) -> httpx.Response | None:
    """Fetch a listing page with exponential backoff on 403 rate-limit."""
    delay = 4.0
    for attempt in range(LISTING_MAX_RETRIES):
        try:
            resp = http.get(url)
        except Exception as e:
            logger.warning("listing fetch error: %s (retry in %.1fs)", e, delay)
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 200:
            return resp
        if resp.status_code == 403:
            if attempt < LISTING_MAX_RETRIES - 1:
                logger.info(
                    "403 on %s (attempt %d/%d), backing off %.1fs",
                    url, attempt + 1, LISTING_MAX_RETRIES, delay,
                )
                time.sleep(delay)
                delay *= 2
                continue
            return resp
        return resp
    return None


def discover_urls(http: httpx.Client, ds_num: int) -> list[str]:
    """Walk the paginated listing pages and return every PDF URL."""
    base = f"{DOJ_BASE_URL}/epstein/doj-disclosures/data-set-{ds_num}-files"
    urls: list[str] = []
    seen: set[str] = set()
    page = 0
    empty_streak = 0

    while True:
        listing = f"{base}?page={page}"
        resp = _fetch_listing(http, listing)
        if resp is None or resp.status_code != 200:
            logger.warning(
                "listing page %d → HTTP %s — stopping",
                page, resp.status_code if resp else "error",
            )
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        new_on_page = 0
        for link in soup.find_all("a", href=True):
            full = urljoin(listing, link["href"])
            if not urlparse(full).path.lower().endswith(".pdf"):
                continue
            if full in seen:
                continue
            seen.add(full)
            urls.append(full)
            new_on_page += 1

        logger.info("page %d: %d new PDF URLs (total=%d)", page, new_on_page, len(urls))

        if new_on_page == 0:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0

        page += 1
        time.sleep(LISTING_DELAY_S)

    return urls


def load_or_discover_urls(
    http: httpx.Client, ds_num: int, cache_file: Path, refresh: bool
) -> list[str]:
    if cache_file.exists() and not refresh:
        urls = [ln.strip() for ln in cache_file.read_text().splitlines() if ln.strip()]
        logger.info("Loaded %d cached URLs from %s", len(urls), cache_file.name)
        return urls
    logger.info("Crawling listing pages for Data Set %d ...", ds_num)
    urls = discover_urls(http, ds_num)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("\n".join(urls))
    logger.info("Cached %d URLs to %s", len(urls), cache_file.name)
    return urls


def text_json_path(text_root: Path, doc_id: str) -> Path:
    # 2-char prefix directory (~hundreds of dirs, ~thousands of files each)
    return text_root / doc_id[:8] / f"{doc_id}.json"


def pdf_mirror_path(tc_root: Path, ds_num: int, doc_id: str) -> Path:
    return tc_root / f"set-{ds_num}" / doc_id[:8] / f"{doc_id}.pdf"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def process_one(
    url: str,
    ds_num: int,
    text_root: Path,
    extractor: PDFTextExtractor,
    tc_root: Path | None = None,
    timeout: float = 120.0,
) -> tuple[str, str, int]:
    """Download + extract + (optionally) mirror one file. Returns (status, doc_id, chars)."""
    filename = url.split("/")[-1].split("?")[0]
    doc_id = filename.removesuffix(".pdf")
    out_path = text_json_path(text_root, doc_id)
    pdf_path = pdf_mirror_path(tc_root, ds_num, doc_id) if tc_root else None

    json_done = out_path.exists()
    pdf_done = pdf_path.exists() if pdf_path is not None else True
    if json_done and pdf_done:
        return ("skip", doc_id, 0)

    # Each thread gets its own httpx client so connections don't collide.
    with httpx.Client(
        headers=HEADERS,
        cookies={"justiceGovAgeVerified": "true"},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except Exception as e:
            return ("download_fail", doc_id, 0)
        content = resp.content

    if pdf_path is not None and not pdf_done:
        try:
            _atomic_write_bytes(pdf_path, content)
        except OSError as e:
            # AFP flakiness shouldn't kill the whole run — log and continue.
            logger.warning("mirror write failed for %s: %s", doc_id, e)

    if json_done:
        # Text JSON already present (prior run). We only needed the PDF.
        return ("mirror_only", doc_id, 0)

    result = extractor.extract_from_bytes(content)
    if result.error and not result.pages:
        # Record the failure so we don't retry forever; store a stub JSON.
        record = {
            "doc_id": doc_id,
            "filename": filename,
            "source_url": url,
            "data_set": ds_num,
            "page_count": result.page_count,
            "total_chars": 0,
            "is_encrypted": result.is_encrypted,
            "has_text_layer": False,
            "needs_ocr": True,
            "error": result.error,
            "pages": [],
        }
        _atomic_write_json(out_path, record)
        return ("extract_fail", doc_id, 0)

    record = {
        "doc_id": doc_id,
        "filename": filename,
        "source_url": url,
        "data_set": ds_num,
        "page_count": result.page_count,
        "total_chars": result.total_chars,
        "is_encrypted": result.is_encrypted,
        "has_text_layer": result.has_text_layer,
        "needs_ocr": result.needs_ocr,
        "error": result.error,
        "pages": [
            {"page_number": p.page_number, "text": p.text, "char_count": p.char_count}
            for p in result.pages
        ],
    }
    _atomic_write_json(out_path, record)
    return ("ok", doc_id, result.total_chars)


def _atomic_write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False))
    tmp.replace(path)





def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_set", type=int, help="DOJ data set number, e.g. 8")
    parser.add_argument("--limit", type=int, default=None, help="cap total docs processed")
    parser.add_argument("--workers", type=int, default=4, help="parallel download workers")
    parser.add_argument("--refresh-urls", action="store_true", help="re-crawl listing pages")
    args = parser.parse_args()

    paths = load_paths()
    paths.ensure()
    text_root = paths.text / f"set-{args.data_set}"
    text_root.mkdir(parents=True, exist_ok=True)
    url_cache = paths.staging / f"urls-set-{args.data_set}.txt"

    tc_root = paths.time_capsule_root
    if tc_root is not None:
        if not tc_root.exists():
            logger.warning(
                "EFTA_TIME_CAPSULE_ROOT=%s does not exist (mount offline?). "
                "PDFs will NOT be mirrored this run.", tc_root,
            )
            tc_root = None
        else:
            (tc_root / f"set-{args.data_set}").mkdir(parents=True, exist_ok=True)
            logger.info("PDF mirror → %s", tc_root / f"set-{args.data_set}")
    else:
        logger.info("No EFTA_TIME_CAPSULE_ROOT set — raw PDFs will be discarded.")

    logger.info("Text archive → %s", text_root)

    http = httpx.Client(
        headers=HEADERS,
        cookies={"justiceGovAgeVerified": "true"},
        follow_redirects=True,
        timeout=60.0,
    )

    urls = load_or_discover_urls(http, args.data_set, url_cache, args.refresh_urls)
    if args.limit:
        urls = urls[: args.limit]
    logger.info("Processing %d URLs with %d workers ...", len(urls), args.workers)

    extractor = PDFTextExtractor()

    counts = {"ok": 0, "skip": 0, "mirror_only": 0, "download_fail": 0, "extract_fail": 0}
    total_chars = 0
    t0 = time.time()
    last_print = t0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(process_one, url, args.data_set, text_root, extractor, tc_root)
            for url in urls
        ]
        for i, fut in enumerate(as_completed(futures), 1):
            status, doc_id, chars = fut.result()
            counts[status] = counts.get(status, 0) + 1
            total_chars += chars
            now = time.time()
            if now - last_print > 5.0 or i == len(futures):
                rate = i / max(now - t0, 1e-3)
                logger.info(
                    "[%d/%d] ok=%d mirror=%d skip=%d dl_fail=%d ex_fail=%d | %.1f docs/s",
                    i, len(futures), counts["ok"], counts["mirror_only"],
                    counts["skip"], counts["download_fail"], counts["extract_fail"],
                    rate,
                )
                last_print = now

    elapsed = time.time() - t0
    print("\n" + "=" * 60)
    print(f"  Ingest of Data Set {args.data_set} complete")
    print(f"  Elapsed:        {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print(f"  ok:             {counts['ok']}")
    print(f"  mirror-only:    {counts['mirror_only']}")
    print(f"  skipped:        {counts['skip']}")
    print(f"  download fail:  {counts['download_fail']}")
    print(f"  extract fail:   {counts['extract_fail']}")
    print(f"  total chars:    {total_chars:,}")
    print(f"  archive dir:    {text_root}")
    print("=" * 60)


if __name__ == "__main__":
    main()
