"""Scraper for Epstein files shared via Dropbox.

Note: Dropbox shared folders require specific API handling.
This scraper uses the Dropbox shared link API to list and download files.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx

from pipeline.db.models import SourceType
from pipeline.scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# The shared Dropbox folder URL
DROPBOX_SHARED_URL = (
    "https://www.dropbox.com/scl/fo/98fthv8otekjk28lcrnc5/"
    "AF07gtPUpLFjFg9IUVvxIjQ/Prod%2001_%2020250822"
    "?dl=0&rlkey=m7p8e9omml96fgxl13kr2nuyt&subfolder_nav_tracking=1"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


class DropboxScraper(BaseScraper):
    """Scrapes documents from the shared Dropbox folder.

    Dropbox shared folder access without an API token is limited.
    For bulk download, we convert the shared link to a direct download link.
    For listing folder contents, we may need Dropbox API access.
    """

    def __init__(self, dropbox_url: str = DROPBOX_SHARED_URL, **kwargs):
        super().__init__(**kwargs)
        self._dropbox_url = dropbox_url
        self._http = httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=120.0,
        )

    @property
    def source_type(self) -> SourceType:
        return SourceType.DROPBOX

    def discover_documents(self) -> list[dict]:
        """Discover documents in the shared Dropbox folder.

        For a shared folder without API access, we attempt to parse the page.
        For production use, consider using the Dropbox API with an access token.
        """
        logger.info("Fetching Dropbox shared folder listing...")

        # Convert to direct download/listing URL
        # Dropbox shared links can be converted by changing dl=0 to dl=1
        # But for folder listing, we need to parse the HTML or use the API
        try:
            resp = self._http.get(self._dropbox_url)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Failed to fetch Dropbox folder listing")
            return []

        # Dropbox renders folder contents via JavaScript, so HTML parsing
        # has limited effectiveness. For now, log what we can find and
        # recommend using the Dropbox API for production.
        #
        # TODO: Implement Dropbox API integration for reliable folder listing.
        # See: https://www.dropbox.com/developers/documentation/http/documentation
        # Endpoint: /2/sharing/get_shared_link_metadata
        # Endpoint: /2/files/list_folder

        logger.warning(
            "Dropbox folder scraping requires API access for reliable results. "
            "Consider setting up a Dropbox API token. "
            "For now, manually download files and place them in the pipeline."
        )

        return []

    def _download(self, url: str) -> bytes | None:
        """Download a file from Dropbox.

        Converts shared links to direct download links.
        """
        # Convert dl=0 to dl=1 for direct download
        download_url = url.replace("dl=0", "dl=1")
        try:
            resp = self._http.get(download_url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError:
            logger.exception("Download failed: %s", url)
            return None
