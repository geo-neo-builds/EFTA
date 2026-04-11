"""Probe text extraction success on the giant data sets.

For each specified data set:
  1. Fetch the listing page (page=0) and grab N sample file URLs
  2. Download each sample
  3. Try free text extraction (pypdf, no API calls)
  4. Report stats: success rate, avg chars per page, files needing OCR

This tells us — without spending any money on OCR — what fraction of
the giant data sets we can process for free.

Usage:
    python -m pipeline.jobs.probe_text_extraction              # default: data sets 8-11, 20 samples each
    python -m pipeline.jobs.probe_text_extraction 9 50         # only data set 9, 50 samples
    python -m pipeline.jobs.probe_text_extraction 8,9,10,11    # specific sets
"""

from __future__ import annotations

import logging
import random
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pipeline.scraper.doj_scraper import DOJ_BASE_URL, HEADERS
from pipeline.text_extraction.pdf_text_extractor import PDFTextExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pypdf").setLevel(logging.ERROR)

DEFAULT_DATA_SETS = [8, 9, 10, 11]
DEFAULT_SAMPLES = 20


def main():
    args = sys.argv[1:]
    if args:
        # Parse data set numbers
        if "," in args[0]:
            target_sets = [int(x) for x in args[0].split(",")]
        else:
            target_sets = [int(args[0])]
        samples = int(args[1]) if len(args) > 1 else DEFAULT_SAMPLES
    else:
        target_sets = DEFAULT_DATA_SETS
        samples = DEFAULT_SAMPLES

    http_client = httpx.Client(
        headers=HEADERS,
        cookies={"justiceGovAgeVerified": "true"},
        follow_redirects=True,
        timeout=120.0,
    )

    extractor = PDFTextExtractor()

    print(f"\n{'#' * 70}")
    print(f"  TEXT EXTRACTION PROBE")
    print(f"  Sets: {target_sets}")
    print(f"  Samples per set: {samples}")
    print(f"{'#' * 70}\n")

    overall_results: list[dict] = []

    for ds_num in target_sets:
        result = probe_data_set(ds_num, http_client, extractor, samples)
        if result:
            overall_results.append(result)

    print_summary(overall_results)


def probe_data_set(
    ds_num: int,
    http: httpx.Client,
    extractor: PDFTextExtractor,
    num_samples: int,
) -> dict | None:
    print(f"\n{'=' * 70}")
    print(f"  DATA SET {ds_num}")
    print(f"{'=' * 70}")

    listing_url = f"{DOJ_BASE_URL}/epstein/doj-disclosures/data-set-{ds_num}-files"
    try:
        resp = http.get(listing_url)
        if resp.status_code != 200:
            print(f"  ❌ Listing returned {resp.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ Failed to fetch listing: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract PDF URLs from this page
    file_urls = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        full_url = urljoin(listing_url, href)
        if urlparse(full_url).path.lower().endswith(".pdf"):
            file_urls.append(full_url)
    file_urls = list(dict.fromkeys(file_urls))

    if not file_urls:
        print("  ❌ No PDF files found on page 0")
        return None

    print(f"  Files on page 0: {len(file_urls)}")
    sampled = random.sample(file_urls, min(num_samples, len(file_urls)))
    print(f"  Sampling {len(sampled)} files...\n")

    successes = []
    failures = []
    needs_ocr = []
    encrypted = []

    for i, url in enumerate(sampled):
        filename = url.split("/")[-1].split("?")[0]
        print(f"  [{i + 1}/{len(sampled)}] {filename}", end=" ", flush=True)

        try:
            file_resp = http.get(url)
            file_resp.raise_for_status()
            content = file_resp.content
        except Exception as e:
            print(f"❌ download failed: {e}")
            failures.append({"file": filename, "error": f"download: {e}"})
            continue

        result = extractor.extract_from_bytes(content)

        if result.error:
            print(f"❌ {result.error}")
            failures.append({
                "file": filename,
                "size_bytes": len(content),
                "error": result.error,
                "is_encrypted": result.is_encrypted,
            })
            continue

        record = {
            "file": filename,
            "size_bytes": len(content),
            "page_count": result.page_count,
            "total_chars": result.total_chars,
            "avg_chars_per_page": round(result.avg_chars_per_page, 1),
            "pages_with_text": result.pages_with_text,
            "pages_without_text": result.pages_without_text,
            "has_text_layer": result.has_text_layer,
            "needs_ocr": result.needs_ocr,
        }

        if result.is_encrypted:
            print(f"🔒 encrypted, {result.page_count}p")
            encrypted.append(record)
        elif result.has_text_layer:
            print(
                f"✅ {result.page_count}p, {result.total_chars:,} chars "
                f"({result.avg_chars_per_page:.0f}/page)"
            )
            successes.append(record)
        else:
            print(
                f"⚠ needs OCR — {result.page_count}p, only {result.total_chars} chars"
            )
            needs_ocr.append(record)

    n_total = len(sampled)
    n_success = len(successes)
    n_needs_ocr = len(needs_ocr)
    n_failures = len(failures)
    n_encrypted = len(encrypted)

    success_rate = n_success / n_total if n_total else 0

    print(f"\n  Summary:")
    print(f"    Free extraction worked: {n_success}/{n_total} ({success_rate:.0%})")
    print(f"    Needs OCR (scans):      {n_needs_ocr}/{n_total}")
    print(f"    Encrypted:              {n_encrypted}/{n_total}")
    print(f"    Failed to open:         {n_failures}/{n_total}")

    if successes:
        avg_chars = sum(s["avg_chars_per_page"] for s in successes) / len(successes)
        avg_pages = sum(s["page_count"] for s in successes) / len(successes)
        print(f"    Avg pages/file (text):    {avg_pages:.1f}")
        print(f"    Avg chars/page (text):    {avg_chars:.0f}")

    if failures or encrypted:
        print(f"\n  Files needing alternate processing:")
        for f in failures:
            print(f"    ❌ {f['file']}: {f['error']}")
        for e in encrypted:
            print(f"    🔒 {e['file']}: encrypted ({e['page_count']} pages)")

    return {
        "data_set": ds_num,
        "samples": n_total,
        "success_count": n_success,
        "needs_ocr_count": n_needs_ocr,
        "encrypted_count": n_encrypted,
        "failure_count": n_failures,
        "success_rate": success_rate,
        "successes": successes,
        "needs_ocr": needs_ocr,
        "failures": failures,
        "encrypted": encrypted,
    }


def print_summary(results: list[dict]):
    if not results:
        return

    print(f"\n\n{'#' * 70}")
    print(f"  PROBE SUMMARY")
    print(f"{'#' * 70}\n")
    print(
        f"{'Set':<6} {'Samples':<10} {'Free Text':<14} {'Need OCR':<11} "
        f"{'Encrypted':<11} {'Failed':<8}"
    )
    print("-" * 65)
    for r in results:
        print(
            f"{r['data_set']:<6} {r['samples']:<10} "
            f"{r['success_count']:<3} ({r['success_rate']:.0%})        "
            f"{r['needs_ocr_count']:<11} {r['encrypted_count']:<11} {r['failure_count']:<8}"
        )

    print(f"\n{'#' * 70}")
    print(f"  ESTIMATED COST SAVINGS")
    print(f"{'#' * 70}\n")

    # Rough cost projections assuming our earlier estimates of total file counts
    estimates = {8: 10829, 9: 533750, 10: 278450, 11: 277450}
    for r in results:
        ds = r["data_set"]
        total = estimates.get(ds, 0)
        if not total:
            continue
        free_count = int(total * r["success_rate"])
        ocr_count = total - free_count

        # Get avg pages/file from our successes (or assume default)
        if r["successes"]:
            avg_pages = sum(s["page_count"] for s in r["successes"]) / len(r["successes"])
        else:
            avg_pages = 8

        ocr_pages = int(ocr_count * avg_pages)
        ocr_cost = (ocr_pages / 1000) * 1.50  # $1.50 per 1000 pages

        # LLM cost on the free-extracted ones (we still need LLM extraction)
        free_pages = int(free_count * avg_pages)
        llm_input_tokens = free_pages * 500  # ~500 tok/page
        llm_output_tokens = free_pages * 200
        llm_cost = (llm_input_tokens / 1_000_000) * 0.30 + (llm_output_tokens / 1_000_000) * 2.50

        print(f"  Data Set {ds} (~{total:,} files):")
        print(f"    Free text extraction:  {free_count:,} files (no cost)")
        print(f"    Needs OCR:             {ocr_count:,} files (~${ocr_cost:,.2f})")
        print(f"    LLM extraction:        {free_count + ocr_count:,} files (~${llm_cost:,.2f})")
        print(f"    Total:                 ~${ocr_cost + llm_cost:,.2f}")
        print()


if __name__ == "__main__":
    main()
