"""Sequential scraper for DOJ Epstein data sets.

The DOJ Epstein files use a predictable naming pattern (EFTA00000001.pdf,
EFTA00000002.pdf, ...) within each data set. This is far more reliable than
crawling the paginated listing pages, which are aggressively rate-limited.

Usage:
    scraper = SequentialDOJScraper(data_set=1, start=1, end=3158)
    scraper.run()
"""

from __future__ import annotations

import logging
import time

import httpx

from pipeline.db.models import SourceType
from pipeline.scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

DOJ_BASE_URL = "https://www.justice.gov"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Known sizes of each data set (last EFTA file number).
# Update as we discover them via binary search.
DATA_SET_RANGES = {
    1: 3158,
    # 2: TBD
    # 3: TBD
    # ...
}


class SequentialDOJScraper(BaseScraper):
    """Downloads files from a DOJ data set using sequential numeric IDs.

    Bypasses paginated listing pages (which are rate-limited) by directly
    requesting predictable file URLs.
    """

    def __init__(
        self,
        data_set: int,
        start: int = 1,
        end: int | None = None,
        delay_seconds: float = 0.3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._data_set = data_set
        self._start = start
        self._end = end or DATA_SET_RANGES.get(data_set)
        if self._end is None:
            raise ValueError(
                f"Unknown range for data set {data_set}. Pass `end=` explicitly."
            )
        self._delay = delay_seconds
        self._http = httpx.Client(
            headers=HEADERS,
            cookies={"justiceGovAgeVerified": "true"},
            follow_redirects=True,
            timeout=120.0,
        )
        logger.info(
            "Sequential scraper for Data Set %d, files %d-%d (%d total)",
            data_set, self._start, self._end, self._end - self._start + 1,
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOJ

    def discover_documents(self) -> list[dict]:
        """Generate file URLs based on sequential ID pattern."""
        documents = []
        for n in range(self._start, self._end + 1):
            filename = f"EFTA{n:08d}.pdf"
            # URL-encode the space in "DataSet 1"
            url = (
                f"{DOJ_BASE_URL}/epstein/files/DataSet%20{self._data_set}/{filename}"
            )
            documents.append({
                "url": url,
                "filename": filename,
                "title": filename,
            })
        logger.info("Generated %d sequential URLs for Data Set %d",
                    len(documents), self._data_set)
        return documents

    def _download(self, url: str) -> bytes | None:
        """Download a file with retry on rate-limit errors."""
        for attempt in range(3):
            try:
                resp = self._http.get(url)
                if resp.status_code == 200:
                    # Verify it's actually a PDF
                    if resp.content[:4] == b"%PDF":
                        # Brief delay between successful downloads
                        time.sleep(self._delay)
                        return resp.content
                    logger.warning("Not a PDF: %s (got %r)", url, resp.content[:20])
                    return None
                if resp.status_code == 404:
                    logger.warning("404 Not Found: %s", url)
                    return None
                if resp.status_code == 403:
                    delay = 2 ** (attempt + 1)
                    logger.warning("403 on %s (attempt %d), backing off %ds",
                                   url, attempt + 1, delay)
                    time.sleep(delay)
                    continue
                logger.warning("Unexpected status %d: %s", resp.status_code, url)
                return None
            except httpx.HTTPError as e:
                logger.warning("HTTP error on %s: %s", url, e)
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return None
        return None
