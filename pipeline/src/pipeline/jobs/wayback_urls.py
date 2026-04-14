"""Discover Set-N PDF URLs from archive.org's Wayback Machine.

When DOJ's Akamai CDN flags our IP and blocks paginated listing crawls
(see CLAUDE.md), we fall back to reading archived snapshots from
web.archive.org. The snapshots are HTML of the same listing pages, so
we just extract `EFTA{8digits}.pdf` filenames from each one and
synthesize the real DOJ file URLs.

The cached URL list lives in the same place the normal ingest expects:
`<SSD>/EFTA/staging/urls-set-<N>.txt`. Once this job finishes, the
existing `local_ingest` job can download + extract from DOJ directly
(which, per CLAUDE.md, is NOT rate-limited).

Usage:
    python -m pipeline.jobs.wayback_urls 8              # all 221 pages
    python -m pipeline.jobs.wayback_urls 8 --start 0 --end 20
    python -m pipeline.jobs.wayback_urls 8 --max-pages 250

Pages with no Wayback snapshot are logged and skipped; the job prints
coverage stats at the end so we know how many we missed.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from urllib.parse import quote, urlencode

import httpx

from pipeline.local_storage.paths import load_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


DOJ_FILE_URL_PATTERN = (
    "https://www.justice.gov/epstein/files/DataSet%20{ds}/{fname}"
)
EFTA_RE = re.compile(r"EFTA\d{8}\.pdf")

# Between CDX lookups + snapshot fetches. Wayback tolerates quite a lot
# but being polite keeps us off their radar.
REQUEST_DELAY_S = 0.6


def _get_with_retry(
    http: httpx.Client, url: str, *, params: dict | None = None,
    timeout: float = 45.0, max_attempts: int = 3, context: str = "",
) -> httpx.Response | None:
    backoff = 3.0
    for attempt in range(1, max_attempts + 1):
        try:
            resp = http.get(url, params=params, timeout=timeout)
        except Exception as e:
            if attempt < max_attempts:
                logger.info("%s: %s (retry %d/%d in %.1fs)",
                            context, e, attempt, max_attempts, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.warning("%s: %s (giving up after %d attempts)",
                           context, e, max_attempts)
            return None
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 502, 503, 504):
            if attempt < max_attempts:
                logger.info("%s: HTTP %d (retry %d/%d in %.1fs)",
                            context, resp.status_code, attempt, max_attempts, backoff)
                time.sleep(backoff)
                backoff *= 2
                continue
        logger.warning("%s: HTTP %d", context, resp.status_code)
        return None
    return None


def latest_snapshot_timestamp(http: httpx.Client, ds_num: int, page: int) -> str | None:
    listing = f"www.justice.gov/epstein/doj-disclosures/data-set-{ds_num}-files?page={page}"
    resp = _get_with_retry(
        http,
        "https://web.archive.org/cdx/search/cdx",
        params={"url": listing, "output": "json", "limit": "-1",
                "filter": "statuscode:200"},
        timeout=45.0,
        context=f"cdx page {page}",
    )
    if resp is None:
        return None
    try:
        rows = json.loads(resp.text)
    except Exception:
        return None
    if len(rows) < 2:
        return None
    return rows[-1][1]


def fetch_snapshot_html(http: httpx.Client, timestamp: str, ds_num: int, page: int) -> str | None:
    listing = f"https://www.justice.gov/epstein/doj-disclosures/data-set-{ds_num}-files?page={page}"
    url = f"https://web.archive.org/web/{timestamp}id_/{listing}"
    resp = _get_with_retry(
        http, url, timeout=60.0, context=f"snapshot page {page}",
    )
    return resp.text if resp is not None else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_set", type=int, help="DOJ data set number, e.g. 8")
    parser.add_argument("--start", type=int, default=0, help="first page index (default 0)")
    parser.add_argument("--end", type=int, default=None, help="last page index inclusive")
    parser.add_argument("--max-pages", type=int, default=250,
                        help="safety cap if --end is not given")
    args = parser.parse_args()

    paths = load_paths()
    paths.ensure()
    cache_file = paths.staging / f"urls-set-{args.data_set}.txt"

    existing = set()
    if cache_file.exists():
        for ln in cache_file.read_text().splitlines():
            ln = ln.strip()
            if ln:
                existing.add(ln)
    logger.info("Existing cached URLs: %d", len(existing))

    # HTTP client with a real-looking UA; Wayback tolerates bots but a real UA
    # occasionally gets cached faster.
    http = httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip, deflate",
        },
        http2=False,
        follow_redirects=True,
    )

    all_urls: set[str] = set(existing)
    pages_with_content = 0
    pages_missing = []
    end = args.end if args.end is not None else args.start + args.max_pages - 1

    logger.info("Scanning Wayback for pages %d..%d of Set %d",
                args.start, end, args.data_set)

    for page in range(args.start, end + 1):
        ts = latest_snapshot_timestamp(http, args.data_set, page)
        if ts is None:
            pages_missing.append(page)
            logger.info("page %d: no snapshot", page)
            time.sleep(REQUEST_DELAY_S)
            continue

        time.sleep(REQUEST_DELAY_S)
        html = fetch_snapshot_html(http, ts, args.data_set, page)
        if not html:
            pages_missing.append(page)
            time.sleep(REQUEST_DELAY_S)
            continue

        filenames = sorted(set(EFTA_RE.findall(html)))
        new_count = 0
        for fname in filenames:
            url = DOJ_FILE_URL_PATTERN.format(ds=args.data_set, fname=fname)
            if url not in all_urls:
                all_urls.add(url)
                new_count += 1

        if filenames:
            pages_with_content += 1
            logger.info("page %d: %d files (+%d new, snapshot %s)",
                        page, len(filenames), new_count, ts)
            # Stop condition: if a page returned 0 filenames AND we've
            # seen content before, we've probably walked past the end.
        else:
            logger.info("page %d: 0 filenames in snapshot", page)
            if pages_with_content > 0:
                # Walked off the end.
                logger.info("likely past the last page (no filenames); stopping")
                break

        time.sleep(REQUEST_DELAY_S)

    # Write out atomically.
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    tmp.write_text("\n".join(sorted(all_urls)))
    tmp.replace(cache_file)

    print("\n" + "=" * 60)
    print(f"  Wayback URL discovery, Data Set {args.data_set}")
    print(f"  Pages with content: {pages_with_content}")
    print(f"  Pages missing:      {len(pages_missing)}")
    print(f"  Total URLs known:   {len(all_urls)}")
    print(f"  New this run:       {len(all_urls) - len(existing)}")
    print(f"  Cache file:         {cache_file}")
    if pages_missing:
        sample = pages_missing[:20]
        more = f" (+{len(pages_missing) - 20} more)" if len(pages_missing) > 20 else ""
        print(f"  Missing pages: {sample}{more}")
    print("=" * 60)


if __name__ == "__main__":
    main()
