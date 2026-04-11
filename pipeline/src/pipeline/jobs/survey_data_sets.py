"""Survey Data Sets 2-12: sample a few files from each, analyze with vision.

For each data set, this script:
  1. Fetches the listing page (page=0) and extracts document URLs
  2. Estimates the total file count from the pagination
  3. Picks N random files
  4. Downloads each, gets the page count, converts page 1 to an image
  5. Sends the image to Gemini Vision with the existing extraction prompt
  6. Prints a summary per data set

This gives us a fast picture of what's in each data set so we can plan the
right pipeline strategy (vision vs OCR vs hybrid) and the right extractors.

Cost: ~$0.06 total (5 files × 11 data sets × ~$0.001 each).

Usage:
    python -m pipeline.jobs.survey_data_sets
    python -m pipeline.jobs.survey_data_sets 3            # only data set 3
    python -m pipeline.jobs.survey_data_sets 3 5          # only set 3, 5 samples
"""

from __future__ import annotations

import io
import logging
import random
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pdf2image import convert_from_bytes, pdfinfo_from_bytes

from pipeline.scraper.doj_scraper import DOCUMENT_EXTENSIONS, DOJ_BASE_URL, HEADERS
from pipeline.vision.processor import VisionProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
# Quiet noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("pipeline.vision.processor").setLevel(logging.WARNING)

DEFAULT_SAMPLES = 5
DATA_SETS_TO_SURVEY = list(range(2, 13))  # 2 through 12


def main():
    args = sys.argv[1:]
    if args:
        target_sets = [int(args[0])]
        samples = int(args[1]) if len(args) > 1 else DEFAULT_SAMPLES
    else:
        target_sets = DATA_SETS_TO_SURVEY
        samples = DEFAULT_SAMPLES

    # HTTP client with the age-verification cookie
    http_client = httpx.Client(
        headers=HEADERS,
        cookies={"justiceGovAgeVerified": "true"},
        follow_redirects=True,
        timeout=120.0,
    )

    # Vision processor (uses Gemini 2.5 Flash)
    vision = VisionProcessor()

    print(f"\n{'#' * 70}")
    print(f"  EFTA DATA SET SURVEY")
    print(f"  Sets: {target_sets}")
    print(f"  Samples per set: {samples}")
    print(f"{'#' * 70}\n")

    summary_table = []

    for ds_num in target_sets:
        result = survey_data_set(ds_num, http_client, vision, samples)
        if result:
            summary_table.append(result)

    # Final summary
    print(f"\n\n{'#' * 70}")
    print(f"  SUMMARY")
    print(f"{'#' * 70}\n")
    print(f"{'Data Set':<10} {'Est Files':<12} {'Pages/File (avg)':<20} {'Common Type':<30}")
    print("-" * 72)
    for row in summary_table:
        print(
            f"{row['data_set']:<10} ~{row['estimated_files']:<11} "
            f"{row['avg_pages']:<20} {row['common_type']:<30}"
        )


def survey_data_set(
    ds_num: int,
    http: httpx.Client,
    vision: VisionProcessor,
    num_samples: int,
) -> dict | None:
    """Survey one data set and return a summary dict."""
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

    # Extract document URLs from this page
    file_urls = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        full_url = urljoin(listing_url, href)
        path_lower = urlparse(full_url).path.lower()
        if any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS):
            file_urls.append(full_url)
    file_urls = list(dict.fromkeys(file_urls))

    # Find total page count from pagination
    last_page = 0
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if text in ("last", "»"):
            m = re.search(r"page=(\d+)", a["href"])
            if m:
                last_page = int(m.group(1))
                break

    files_on_page0 = len(file_urls)
    total_pages = last_page + 1
    est_total = files_on_page0 * total_pages

    print(f"  Files on page 0: {files_on_page0}")
    print(f"  Total listing pages: {total_pages}")
    print(f"  Estimated total files: ~{est_total:,}")

    if not file_urls:
        return None

    # Sample some files (randomly)
    sampled = random.sample(file_urls, min(num_samples, len(file_urls)))

    page_counts = []
    types_seen = []

    for i, file_url in enumerate(sampled):
        filename = file_url.split("/")[-1].split("?")[0]
        try:
            filename = httpx.URL(file_url).path.split("/")[-1]
        except Exception:
            pass

        print(f"\n  Sample {i + 1}/{len(sampled)}: {filename}")

        try:
            file_resp = http.get(file_url)
            file_resp.raise_for_status()
            content = file_resp.content
            print(f"    Size: {len(content):,} bytes")

            if not filename.lower().endswith(".pdf"):
                print(f"    (Not a PDF — skipping content analysis)")
                continue

            # Get page count
            try:
                info = pdfinfo_from_bytes(content)
                pages = info.get("Pages", 1)
            except Exception as e:
                pages = 1
                print(f"    ⚠ pdfinfo failed: {e}")

            page_counts.append(pages)
            print(f"    Pages: {pages}")

            # Render page 1 for analysis
            images = convert_from_bytes(
                content, dpi=100, first_page=1, last_page=1
            )
            if not images:
                print("    ⚠ Could not render page 1")
                continue

            # Analyze with vision
            result = vision._analyze_image(images[0], page_number=1)
            types_seen.append(result.document_type)

            print(f"    Type: {result.document_type} (conf {result.document_type_confidence:.2f})")
            if result.room_type and result.room_type != "unknown":
                print(f"    Room: {result.room_type}")
            print(f"    Summary: {result.document_summary[:240]}")
            if result.is_evidence_card:
                print(f"    📇 Evidence card — location: {result.fbi_metadata.location_label}")
            if result.is_exhibit_marker:
                print(f"    🔖 Exhibit marker: {result.exhibit_label}")
            if result.element_categories:
                print(f"    Elements: {', '.join(result.element_categories[:8])}")
            if result.redactions_present:
                print(f"    ⬛ Has redactions")
            if result.visible_text:
                preview = " | ".join(result.visible_text[:5])
                print(f"    Visible text: {preview[:200]}")

        except Exception as e:
            print(f"    ❌ Error: {e}")

    avg_pages = round(sum(page_counts) / len(page_counts), 1) if page_counts else 0
    common_type = max(set(types_seen), key=types_seen.count) if types_seen else "unknown"

    return {
        "data_set": ds_num,
        "estimated_files": est_total,
        "avg_pages": avg_pages,
        "common_type": common_type,
    }


if __name__ == "__main__":
    main()
