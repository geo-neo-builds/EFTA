"""Document AI OCR processor for PDF and image documents."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.api_core.client_options import ClientOptions
from google.cloud import documentai, storage

from pipeline.config import config

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Extracts text from PDFs/images using Google Document AI."""

    def __init__(
        self,
        storage_client: storage.Client | None = None,
    ):
        opts = ClientOptions(
            api_endpoint=f"{config.document_ai_location}-documentai.googleapis.com"
        )
        self._docai = documentai.DocumentProcessorServiceClient(client_options=opts)
        self._processor_name = self._docai.processor_path(
            config.gcp_project_id,
            config.document_ai_location,
            config.document_ai_processor_id,
        )
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    def process_document(self, gcs_path: str) -> OCRResult:
        """Process a document from GCS and return extracted text.

        Args:
            gcs_path: Path within the GCS bucket (e.g., "originals/doj/file.pdf")

        Returns:
            OCRResult with extracted text and metadata.
        """
        logger.info("Processing document: %s", gcs_path)

        # Download from GCS
        blob = self._bucket.blob(gcs_path)
        content = blob.download_as_bytes()

        # Determine MIME type
        mime_type = self._get_mime_type(gcs_path)

        # Process with Document AI
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
        request = documentai.ProcessRequest(
            name=self._processor_name,
            raw_document=raw_document,
        )

        result = self._docai.process_document(request=request)
        document = result.document

        # Extract page-by-page text
        pages = []
        for i, page in enumerate(document.pages):
            page_text = self._extract_page_text(document.text, page)
            pages.append(PageText(
                page_number=i + 1,
                text=page_text,
                width=page.dimension.width if page.dimension else 0,
                height=page.dimension.height if page.dimension else 0,
                has_handwriting=self._detect_handwriting(page),
            ))

        ocr_result = OCRResult(
            full_text=document.text,
            pages=pages,
            page_count=len(pages),
        )

        logger.info(
            "OCR complete: %d pages, %d chars, handwriting on %d pages",
            ocr_result.page_count,
            len(ocr_result.full_text),
            sum(1 for p in pages if p.has_handwriting),
        )
        return ocr_result

    def process_and_store(self, gcs_path: str, document_id: str) -> str:
        """Process a document and store the OCR results in GCS.

        Returns:
            The GCS path where OCR results are stored.
        """
        result = self.process_document(gcs_path)

        # Store results as JSON in GCS
        output_path = f"text/{document_id}/ocr_result.json"
        output_blob = self._bucket.blob(output_path)
        output_blob.upload_from_string(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            content_type="application/json",
        )

        logger.info("OCR results stored at gs://%s/%s", config.gcs_bucket_name, output_path)
        return output_path

    @staticmethod
    def _get_mime_type(path: str) -> str:
        suffix = Path(path).suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        return mime_types.get(suffix, "application/pdf")

    @staticmethod
    def _extract_page_text(full_text: str, page: documentai.Document.Page) -> str:
        """Extract text for a specific page using layout text anchors."""
        if not page.layout or not page.layout.text_anchor:
            return ""
        segments = page.layout.text_anchor.text_segments
        if not segments:
            return ""
        text_parts = []
        for segment in segments:
            start = int(segment.start_index) if segment.start_index else 0
            end = int(segment.end_index)
            text_parts.append(full_text[start:end])
        return "".join(text_parts)

    @staticmethod
    def _detect_handwriting(page: documentai.Document.Page) -> bool:
        """Check if a page contains handwritten text based on detected languages."""
        # Document AI marks handwritten text via detected languages
        # and the visual element type. Check for handwriting indicators.
        for block in page.blocks:
            for lang in block.detected_languages:
                # Document AI sometimes uses confidence + language hints
                # for handwriting detection
                pass
        # A more reliable approach: check if paragraphs have low confidence
        # (handwriting typically has lower OCR confidence)
        confidences = []
        for para in page.paragraphs:
            if para.layout and para.layout.confidence:
                confidences.append(para.layout.confidence)
        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            # Handwritten text typically has confidence < 0.85
            return avg_confidence < 0.85
        return False


class PageText:
    """OCR result for a single page."""

    def __init__(
        self,
        page_number: int,
        text: str,
        width: float = 0,
        height: float = 0,
        has_handwriting: bool = False,
    ):
        self.page_number = page_number
        self.text = text
        self.width = width
        self.height = height
        self.has_handwriting = has_handwriting

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "width": self.width,
            "height": self.height,
            "has_handwriting": self.has_handwriting,
        }


class OCRResult:
    """Complete OCR result for a document."""

    def __init__(self, full_text: str, pages: list[PageText], page_count: int):
        self.full_text = full_text
        self.pages = pages
        self.page_count = page_count

    def to_dict(self) -> dict:
        return {
            "full_text": self.full_text,
            "pages": [p.to_dict() for p in self.pages],
            "page_count": self.page_count,
        }
