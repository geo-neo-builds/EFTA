"""Scraper for DOJ Epstein disclosures at justice.gov/epstein/doj-disclosures."""

from __future__ import annotations

import logging
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pipeline.db.models import SourceType
from pipeline.scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

DOJ_BASE_URL = "https://www.justice.gov"
DOJ_DISCLOSURES_URL = f"{DOJ_BASE_URL}/epstein/doj-disclosures"

# File extensions we want to download as documents
DOCUMENT_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx", ".wav", ".mp3", ".mp4")

# All known file extensions (documents + media) to exclude from sub-page crawling
FILE_EXTENSIONS = DOCUMENT_EXTENSIONS + (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".zip")

# Mimic a real browser to avoid 403
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class DOJScraper(BaseScraper):
    """Scrapes documents from the DOJ Epstein disclosures page."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # The DOJ site requires a "justiceGovAgeVerified" cookie to access files.
        # This cookie is normally set by JavaScript when clicking "Yes" on the
        # age verification page.
        self._http = httpx.Client(
            headers=HEADERS,
            cookies={"justiceGovAgeVerified": "true"},
            follow_redirects=True,
            timeout=60.0,
        )
        logger.info("Age verification cookie set: justiceGovAgeVerified=true")

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOJ

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Strip fragments (#...) from URLs so we don't visit the same page twice."""
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()

    def discover_documents(self) -> list[dict]:
        """Parse the DOJ disclosures page and find all PDF links."""
        documents = []
        urls_to_check = [DOJ_DISCLOSURES_URL]
        visited = set()

        while urls_to_check:
            url = self._normalize_url(urls_to_check.pop(0))
            if url in visited:
                continue
            visited.add(url)

            logger.info("Fetching page: %s", url)
            try:
                resp = self._http.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.warning("403 Forbidden (rate limited): %s", url)
                else:
                    logger.exception("Failed to fetch: %s", url)
                continue
            except httpx.HTTPError:
                logger.exception("Failed to fetch: %s", url)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find all links on the page
            for link in soup.find_all("a", href=True):
                href = link["href"]
                full_url = self._normalize_url(urljoin(url, href))

                # Collect document links
                if self._is_document_link(full_url):
                    filename = self._extract_filename(full_url)
                    title = link.get_text(strip=True) or filename
                    documents.append({
                        "url": full_url,
                        "filename": filename,
                        "title": title,
                    })

                # Follow sub-pages within the epstein section
                elif self._is_epstein_subpage(full_url) and full_url not in visited:
                    urls_to_check.append(full_url)

            # Be polite - don't hammer the server
            time.sleep(1)

        # Deduplicate by URL
        seen_urls = set()
        unique_docs = []
        for doc in documents:
            if doc["url"] not in seen_urls:
                seen_urls.add(doc["url"])
                unique_docs.append(doc)

        logger.info("Found %d unique documents", len(unique_docs))
        return unique_docs

    def _download(self, url: str) -> bytes | None:
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError:
            logger.exception("Download failed: %s", url)
            return None

    @staticmethod
    def _is_document_link(url: str) -> bool:
        """Check if URL points to a downloadable document."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        return any(path_lower.endswith(ext) for ext in DOCUMENT_EXTENSIONS)

    @staticmethod
    def _is_epstein_subpage(url: str) -> bool:
        """Check if URL is a sub-page within the DOJ Epstein section."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        return (
            parsed.netloc in ("www.justice.gov", "justice.gov")
            and "/epstein" in parsed.path
            and not any(path_lower.endswith(ext) for ext in FILE_EXTENSIONS)
            and "/age-verify" not in parsed.path
        )

    @staticmethod
    def _extract_filename(url: str) -> str:
        """Extract filename from URL path."""
        parsed = urlparse(url)
        path = parsed.path
        # Get the last segment of the path
        filename = path.split("/")[-1]
        if not filename:
            filename = "unknown_document"
        return filename
