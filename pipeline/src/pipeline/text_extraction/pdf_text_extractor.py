"""Free PDF text extraction using pypdf.

For PDFs that have a native text layer (e.g., emails saved as PDF, native
text-based legal documents), this extracts the text directly with no API
costs. For scans (image-only PDFs), it returns very little text and the
caller can route the document to OCR instead.

Cost: $0 per file (no API calls).

Usage:
    extractor = PDFTextExtractor()
    result = extractor.extract_from_bytes(pdf_bytes)
    if result.has_text_layer:
        # We got real text — no OCR needed
        text = result.full_text
    else:
        # Scanned PDF — needs OCR or vision pipeline
        ...
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import pypdf

logger = logging.getLogger(__name__)

# A PDF page with fewer than this many characters of extractable text is
# considered "essentially empty" — usually a scan with no text layer.
MIN_CHARS_FOR_TEXT_LAYER = 50


@dataclass
class PageText:
    page_number: int
    text: str
    char_count: int

    @property
    def has_text(self) -> bool:
        return self.char_count >= MIN_CHARS_FOR_TEXT_LAYER


@dataclass
class TextExtractionResult:
    """Result of attempting free text extraction on a PDF."""
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    full_text: str = ""
    total_chars: int = 0
    pages_with_text: int = 0
    pages_without_text: int = 0
    error: str | None = None
    is_encrypted: bool = False

    @property
    def has_text_layer(self) -> bool:
        """True if at least half the pages have meaningful text."""
        if self.page_count == 0:
            return False
        return self.pages_with_text >= (self.page_count / 2)

    @property
    def needs_ocr(self) -> bool:
        """True if free extraction couldn't find enough text."""
        return self.error is not None or not self.has_text_layer

    @property
    def avg_chars_per_page(self) -> float:
        if self.page_count == 0:
            return 0.0
        return self.total_chars / self.page_count

    def to_dict(self) -> dict:
        return {
            "page_count": self.page_count,
            "total_chars": self.total_chars,
            "avg_chars_per_page": round(self.avg_chars_per_page, 1),
            "pages_with_text": self.pages_with_text,
            "pages_without_text": self.pages_without_text,
            "has_text_layer": self.has_text_layer,
            "needs_ocr": self.needs_ocr,
            "is_encrypted": self.is_encrypted,
            "error": self.error,
            "pages": [
                {
                    "page_number": p.page_number,
                    "text": p.text,
                    "char_count": p.char_count,
                }
                for p in self.pages
            ],
        }


class PDFTextExtractor:
    """Extracts text from PDFs that have a native text layer (no OCR)."""

    def extract_from_bytes(self, content: bytes) -> TextExtractionResult:
        """Try to extract text from a PDF byte stream.

        Returns a TextExtractionResult that always has page_count and
        an `error` field if anything went wrong. Even on partial failures
        we return what we got — the caller can decide whether to fall
        back to OCR.
        """
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
        except Exception as e:
            return TextExtractionResult(
                page_count=0,
                error=f"Failed to open PDF: {e}",
            )

        result = TextExtractionResult(page_count=len(reader.pages))

        # Handle encrypted PDFs
        if reader.is_encrypted:
            result.is_encrypted = True
            try:
                # Try empty password first (many "encrypted" PDFs have no password)
                reader.decrypt("")
            except Exception:
                result.error = "PDF is encrypted and could not be decrypted"
                return result

        for i, page in enumerate(reader.pages):
            page_number = i + 1
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.debug("Failed to extract page %d: %s", page_number, e)
                text = ""

            char_count = len(text.strip())
            page_text = PageText(
                page_number=page_number,
                text=text,
                char_count=char_count,
            )
            result.pages.append(page_text)
            result.total_chars += char_count
            if page_text.has_text:
                result.pages_with_text += 1
            else:
                result.pages_without_text += 1

        result.full_text = "\n\n".join(p.text for p in result.pages if p.text)
        return result
