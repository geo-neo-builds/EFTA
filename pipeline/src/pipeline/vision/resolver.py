"""Resolves Gemini Vision results into Firestore-ready records."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import (
    Document,
    DocumentType,
    ElementCategory,
    ImageElement,
    RoomType,
)
from pipeline.vision.schema import VisionResult

logger = logging.getLogger(__name__)


class VisionResolver:
    """Applies a VisionResult to a Document and creates ImageElement records."""

    def __init__(self, firestore_client: FirestoreClient | None = None):
        self.db = firestore_client or FirestoreClient()

    def apply_to_document(
        self,
        doc: Document,
        results: list[VisionResult],
    ) -> tuple[Document, list[ImageElement]]:
        """Update a Document with vision-derived fields and create elements.

        Args:
            doc: The Document to update (caller is responsible for saving)
            results: One VisionResult per page of the document

        Returns:
            (updated Document, list of ImageElement records to store)
        """
        if not results:
            return doc, []

        # For now, treat single-page documents as the common case (most evidence
        # photos are 1 page). For multi-page docs, we use the first page for
        # document-level fields and aggregate elements from all pages.
        primary = results[0]

        # ---- Document type ----
        doc.document_type = self._map_document_type(primary.document_type)
        doc.document_type_confidence = primary.document_type_confidence
        doc.document_summary = primary.document_summary
        doc.vision_summary = primary.document_summary

        # ---- Setting ----
        doc.indoor = primary.indoor
        doc.room_type = self._map_room_type(primary.room_type)

        # ---- FBI evidence card / exhibit marker detection ----
        doc.is_evidence_card = primary.is_evidence_card or primary.fbi_metadata.is_fbi_evidence_card
        doc.is_exhibit_marker = primary.is_exhibit_marker or bool(primary.fbi_metadata.room_marker)
        doc.exhibit_label = (
            primary.exhibit_label or primary.fbi_metadata.room_marker
        )

        # FBI card metadata
        doc.photo_date = primary.fbi_metadata.date
        doc.photo_case_id = primary.fbi_metadata.case_id
        doc.photo_location_address = primary.fbi_metadata.location_label

        # ---- Aggregate elements across all pages ----
        all_elements: list[ImageElement] = []
        all_categories: set[ElementCategory] = set()

        for page_idx, page_result in enumerate(results):
            page_num = page_idx + 1
            for ext_el in page_result.elements:
                category = self._map_element_category(ext_el.category)
                all_categories.add(category)

                element_id = self._make_element_id(doc.id, page_num, ext_el)
                element = ImageElement(
                    id=element_id,
                    document_id=doc.id,
                    page_number=page_num,
                    category=category,
                    description=ext_el.description,
                    notable=ext_el.notable,
                    title=ext_el.title,
                    creator=ext_el.creator,
                    quantity=ext_el.quantity,
                    confidence=ext_el.confidence,
                )
                all_elements.append(element)

        doc.element_categories = sorted(all_categories, key=lambda c: c.value)

        # ---- People ----
        doc.people_count = max(
            (r.people_visible.count + r.people_visible.redacted_count for r in results),
            default=0,
        )
        # Add PEOPLE category if any people are visible
        if doc.people_count > 0 and ElementCategory.PEOPLE not in doc.element_categories:
            doc.element_categories.append(ElementCategory.PEOPLE)

        # ---- Redactions ----
        doc.has_redactions = any(r.redactions_present for r in results)

        # ---- Status timestamp ----
        doc.vision_completed_at = datetime.now(timezone.utc)

        return doc, all_elements

    def store_elements(self, elements: list[ImageElement]) -> None:
        """Persist a batch of ImageElements to Firestore."""
        for element in elements:
            self.db.upsert_image_element(element)

    @staticmethod
    def _map_document_type(value: str) -> DocumentType:
        if not value:
            return DocumentType.OTHER
        try:
            return DocumentType(value.lower())
        except ValueError:
            return DocumentType.OTHER

    @staticmethod
    def _map_room_type(value: str | None) -> RoomType | None:
        if not value:
            return None
        try:
            return RoomType(value.lower())
        except ValueError:
            return RoomType.UNKNOWN

    @staticmethod
    def _map_element_category(value: str) -> ElementCategory:
        if not value:
            return ElementCategory.OTHER
        try:
            return ElementCategory(value.lower())
        except ValueError:
            return ElementCategory.OTHER

    @staticmethod
    def _make_element_id(document_id: str, page_num: int, element) -> str:
        """Stable id for an element, derived from doc id + page + content."""
        seed = f"{document_id}|{page_num}|{element.category}|{element.description[:80]}"
        return hashlib.md5(seed.encode()).hexdigest()[:16]
