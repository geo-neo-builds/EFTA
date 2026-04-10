"""Entity resolution — deduplicates people and locations across documents."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Event, Location, Person
from pipeline.extraction.schema import (
    ExtractedEvent,
    ExtractedLocation,
    ExtractedPerson,
    ExtractionResult,
)
from pipeline.privacy.victim_tracker import VictimTracker

logger = logging.getLogger(__name__)


class EntityResolver:
    """Resolves extracted entities against existing database records.

    Handles deduplication of people, locations, and victim identity mapping.
    Converts raw LLM extraction output into database-ready records.
    """

    def __init__(
        self,
        victim_tracker: VictimTracker,
        firestore_client: FirestoreClient | None = None,
    ):
        self.db = firestore_client or FirestoreClient()
        self._victim_tracker = victim_tracker

    def resolve_and_store(
        self,
        extraction: ExtractionResult,
        document_id: str,
    ) -> list[Event]:
        """Resolve all entities and store results in Firestore.

        Returns the list of created Event records.
        """
        # Resolve people
        person_map = {}  # extracted name → Person.id
        for person in extraction.people:
            resolved = self._resolve_person(person, document_id)
            person_map[person.name.lower()] = resolved.id

        # Resolve locations
        location_map = {}  # extracted name → Location.id
        for loc in extraction.locations:
            resolved = self._resolve_location(loc)
            location_map[loc.name.lower()] = resolved.id

        # Resolve victims
        victim_map = {}  # placeholder → victim_id
        for victim in extraction.victims:
            victim_id = self._victim_tracker.get_or_create_victim_id(
                identifying_info=victim.identifying_info,
                document_id=document_id,
            )
            victim_map[victim.placeholder.lower()] = victim_id

        # Create events
        events = []
        for i, extracted_event in enumerate(extraction.events):
            event = self._create_event(
                extracted_event,
                document_id=document_id,
                event_index=i,
                person_map=person_map,
                location_map=location_map,
                victim_map=victim_map,
            )
            self.db.upsert_event(event)
            events.append(event)

        # Update person event counts
        for person_id in set(person_map.values()):
            person = self.db.get_person(person_id)
            if person:
                event_count = len([
                    e for e in events if person_id in e.people_ids
                ])
                person.event_count = (person.event_count or 0) + event_count
                self.db.upsert_person(person)

        logger.info(
            "Resolved and stored %d events, %d people, %d locations, %d victims for doc %s",
            len(events),
            len(person_map),
            len(location_map),
            len(victim_map),
            document_id,
        )
        return events

    def _resolve_person(self, extracted: ExtractedPerson, document_id: str) -> Person:
        """Find or create a person record."""
        normalized_name = self._normalize_name(extracted.name)

        # Try to find existing person
        existing = self.db.find_person_by_name(normalized_name)
        if existing:
            # Update with new document reference
            if document_id not in existing.document_ids:
                existing.document_ids.append(document_id)
                existing.updated_at = datetime.now(timezone.utc)
                self.db.upsert_person(existing)
            return existing

        # Create new person
        person_id = hashlib.md5(normalized_name.encode()).hexdigest()[:16]
        person = Person(
            id=person_id,
            full_name=normalized_name,
            role=extracted.role,
            description=extracted.description,
            document_ids=[document_id],
        )
        self.db.upsert_person(person)
        return person

    def _resolve_location(self, extracted: ExtractedLocation) -> Location:
        """Find or create a location record."""
        normalized_name = extracted.name.strip()

        existing = self.db.find_location_by_name(normalized_name)
        if existing:
            return existing

        location_id = hashlib.md5(normalized_name.lower().encode()).hexdigest()[:16]
        location = Location(
            id=location_id,
            name=normalized_name,
            city=extracted.city or None,
            state=extracted.state or None,
            country=extracted.country or None,
        )
        self.db.upsert_location(location)
        return location

    def _create_event(
        self,
        extracted: ExtractedEvent,
        document_id: str,
        event_index: int,
        person_map: dict[str, str],
        location_map: dict[str, str],
        victim_map: dict[str, str],
    ) -> Event:
        """Convert an extracted event into a database Event record."""
        event_id = f"{document_id}_evt_{event_index:04d}"

        # Map people names to IDs
        people_ids = []
        for person in extracted.people:
            pid = person_map.get(person.name.lower())
            if pid:
                people_ids.append(pid)

        # Map victim placeholders to IDs
        victim_ids = []
        for victim in extracted.victims:
            vid = victim_map.get(victim.placeholder.lower())
            if vid:
                victim_ids.append(vid)

        # Resolve location
        location_id = None
        location_name = None
        location_city = None
        location_state = None
        location_country = None
        if extracted.location:
            location_name = extracted.location.name
            location_city = extracted.location.city or None
            location_state = extracted.location.state or None
            location_country = extracted.location.country or None
            lid = location_map.get(extracted.location.name.lower())
            if lid:
                location_id = lid

        # Parse dates
        date_start = self._parse_date(extracted.date_start)
        date_end = self._parse_date(extracted.date_end)

        # Map motive strings to enum values
        motive_categories = [m for m in extracted.motive_categories if m]

        now = datetime.now(timezone.utc)
        return Event(
            id=event_id,
            document_id=document_id,
            document_page=extracted.page_number,
            what_category=extracted.what_category,
            what_subcategory=extracted.what_subcategory,
            what_description=extracted.what_description,
            location_name=location_name,
            location_city=location_city,
            location_state=location_state,
            location_country=location_country,
            location_id=location_id,
            date_start=date_start,
            date_end=date_end,
            date_precision=extracted.date_precision,
            date_raw_text=extracted.date_raw_text,
            people_ids=people_ids,
            victim_ids=victim_ids,
            motive_categories=motive_categories,
            motive_description=extracted.motive_description or None,
            confidence_score=extracted.confidence,
            raw_text_excerpt=extracted.source_text[:500],
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a person's name for deduplication."""
        name = name.strip()
        name = " ".join(name.split())  # collapse whitespace
        # Title case
        name = " ".join(
            part.capitalize() if part.lower() not in ("de", "von", "van", "la", "el")
            else part.lower()
            for part in name.split()
        )
        return name

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse a date string in various formats."""
        if not date_str:
            return None

        date_str = date_str.strip()
        formats = [
            "%Y-%m-%d",
            "%Y-%m",
            "%Y",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%B %d, %Y",
            "%B %Y",
            "%b %d, %Y",
            "%b %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Try to extract a year at minimum
        year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
        if year_match:
            try:
                return datetime(int(year_match.group()), 1, 1, tzinfo=timezone.utc)
            except ValueError:
                pass

        return None
