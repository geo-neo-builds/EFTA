"""Groups vision-processed photos into Property → Exhibit → Photo hierarchy.

How exhibits work in DOJ Data Set 1:

  - The FBI photographs evidence systematically: at the start of each
    documentation session, they hold up an evidence card showing the
    DATE / CASE ID / LOCATION (which property is being searched).
  - When entering each new room, they place a paper placard on the
    doorframe with a letter or code (e.g., "H", "JJ", "B-2"), and
    photograph that placard FIRST.
  - Then they photograph the contents of that room.
  - When they move to the next room, a new placard appears in the photos.
  - Multiple properties may appear in a single data set (e.g., NYC townhouse,
    Little St James, Zorro Ranch), each starting with its own evidence card.
  - Photos are numbered sequentially (EFTA00000001.pdf, EFTA00000002.pdf, ...)
    so the order is reliable.

This script:
  1. Lists all documents whose vision analysis is complete, sorted by filename
  2. Walks them in order, tracking the current Property and current Exhibit
  3. When it sees an evidence card, resolves the Property (creating it if new)
  4. When it sees an exhibit marker, starts a new Exhibit under the current Property
  5. Assigns property_id and exhibit_id to every subsequent photo
  6. Updates Property and Exhibit records with member counts and ids

Usage:
    python -m pipeline.jobs.group_exhibits
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import datetime, timezone

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Exhibit, ProcessingStatus, Property
from pipeline.vision.property_resolver import PropertyResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Grouping photos into properties and exhibits...")

    db = FirestoreClient()
    property_resolver = PropertyResolver(firestore_client=db)

    # Get all documents that have been vision-processed
    documents = db.list_documents(
        status=ProcessingStatus.VISION_COMPLETE,
        limit=10000,
    )
    if not documents:
        logger.info("No vision-complete documents found.")
        return

    # Sort by filename so we walk them in capture order
    documents.sort(key=lambda d: d.filename)
    logger.info("Walking %d documents in capture order", len(documents))

    current_property: Property | None = None
    current_exhibit: Exhibit | None = None
    last_evidence_card_data: dict = {}  # carries case_id/location/date forward

    property_count = 0
    exhibit_count = 0
    photos_assigned = 0
    photos_unassigned = 0
    properties_seen: dict[str, Property] = {}  # id -> Property to update at end

    for doc in documents:
        # If this photo is an evidence card, update the current property and metadata
        if doc.is_evidence_card:
            if doc.photo_case_id:
                last_evidence_card_data["case_id"] = doc.photo_case_id
            if doc.photo_location_address:
                last_evidence_card_data["location_address"] = doc.photo_location_address
            if doc.photo_date:
                last_evidence_card_data["photo_date"] = doc.photo_date

            # Resolve / create the Property for this address
            new_property = property_resolver.resolve(doc.photo_location_address)
            if new_property is not None:
                # If we're switching properties, save out the current exhibit
                if current_property is None or new_property.id != current_property.id:
                    if current_exhibit is not None:
                        _finalize_exhibit(db, current_exhibit)
                        current_exhibit = None
                    current_property = new_property
                    if current_property.id not in properties_seen:
                        properties_seen[current_property.id] = current_property
                        property_count += 1
                        logger.info(
                            "New property: %s (%s)",
                            current_property.nickname or current_property.name,
                            doc.photo_location_address,
                        )
                    # Track case ids and dates on the property
                    p = properties_seen[current_property.id]
                    if doc.photo_case_id and doc.photo_case_id not in p.case_ids:
                        p.case_ids.append(doc.photo_case_id)
                    if doc.photo_date and doc.photo_date not in p.raid_dates:
                        p.raid_dates.append(doc.photo_date)

        # If this photo is itself an exhibit marker, start a new exhibit
        if doc.is_exhibit_marker and doc.exhibit_label:
            if current_exhibit is not None:
                _finalize_exhibit(db, current_exhibit)

            exhibit_id = _make_exhibit_id(doc.exhibit_label, doc.id)
            current_exhibit = Exhibit(
                id=exhibit_id,
                label=doc.exhibit_label,
                property_id=current_property.id if current_property else None,
                starting_document_id=doc.id,
                document_ids=[],
                photo_count=0,
                room_type=doc.room_type,
                location_address=last_evidence_card_data.get("location_address"),
                case_id=last_evidence_card_data.get("case_id"),
                photo_date=last_evidence_card_data.get("photo_date"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            exhibit_count += 1
            logger.info(
                "New exhibit '%s' under %s starting at %s",
                doc.exhibit_label,
                current_property.nickname if current_property else "(no property)",
                doc.filename,
            )

        # Assign this document to the current property + exhibit
        if current_property is not None:
            doc.property_id = current_property.id
            p = properties_seen[current_property.id]
            if doc.id not in p.document_ids:
                p.document_ids.append(doc.id)
                p.photo_count = len(p.document_ids)

        if current_exhibit is not None:
            current_exhibit.document_ids.append(doc.id)
            current_exhibit.photo_count = len(current_exhibit.document_ids)
            doc.exhibit_id = current_exhibit.id

            p = properties_seen.get(current_property.id) if current_property else None
            if p is not None and current_exhibit.id not in p.exhibit_ids:
                p.exhibit_ids.append(current_exhibit.id)
                p.exhibit_count = len(p.exhibit_ids)

            db.upsert_document(doc)
            photos_assigned += 1
        elif current_property is not None:
            # No exhibit yet but we know the property
            db.upsert_document(doc)
            photos_assigned += 1
        else:
            photos_unassigned += 1

    # Finalize the last exhibit
    if current_exhibit is not None:
        _finalize_exhibit(db, current_exhibit)

    # Save updated property records
    for prop in properties_seen.values():
        prop.updated_at = datetime.now(timezone.utc)
        db.upsert_property(prop)

    logger.info(
        "Grouping complete. %d properties, %d exhibits created. "
        "%d photos assigned, %d unassigned",
        property_count, exhibit_count, photos_assigned, photos_unassigned,
    )


def _finalize_exhibit(db: FirestoreClient, exhibit: Exhibit) -> None:
    exhibit.updated_at = datetime.now(timezone.utc)
    db.upsert_exhibit(exhibit)
    logger.info("  Saved exhibit '%s' with %d photos", exhibit.label, exhibit.photo_count)


def _make_exhibit_id(label: str, starting_doc_id: str) -> str:
    """Stable id combining label + starting doc id (in case of duplicate labels)."""
    seed = f"{label}|{starting_doc_id}"
    return f"exhibit_{hashlib.md5(seed.encode()).hexdigest()[:12]}"


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Exhibit grouper failed")
        sys.exit(1)
