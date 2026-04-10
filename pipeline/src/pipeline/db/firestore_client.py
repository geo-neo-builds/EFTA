"""Firestore CRUD operations for all collections."""

from __future__ import annotations

from typing import Optional

from google.cloud import firestore

from pipeline.config import config
from pipeline.db.models import (
    Document,
    Event,
    Exhibit,
    ImageElement,
    Location,
    Person,
    ProcessingStatus,
    Property,
    Victim,
    VictimIdentityMapping,
)


class FirestoreClient:
    """Client for all Firestore operations."""

    def __init__(self, db: firestore.Client | None = None):
        self._db = db or firestore.Client(
            project=config.gcp_project_id,
            database=config.firestore_database,
        )

    # ---- Documents ----

    def get_document(self, doc_id: str) -> Document | None:
        ref = self._db.collection("documents").document(doc_id)
        snap = ref.get()
        if not snap.exists:
            return None
        return Document(**snap.to_dict())

    def get_document_by_url(self, source_url: str) -> Document | None:
        query = (
            self._db.collection("documents")
            .where("source_url", "==", source_url)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None
        return Document(**docs[0].to_dict())

    def upsert_document(self, doc: Document) -> None:
        ref = self._db.collection("documents").document(doc.id)
        ref.set(doc.model_dump(), merge=True)

    def list_documents(
        self,
        status: ProcessingStatus | None = None,
        document_type: str | None = None,
        has_handwriting: bool | None = None,
        is_audio: bool | None = None,
        is_image: bool | None = None,
        limit: int = 100,
    ) -> list[Document]:
        query = self._db.collection("documents")
        if status:
            query = query.where("processing_status", "==", status.value)
        if document_type:
            query = query.where("document_type", "==", document_type)
        if has_handwriting is not None:
            query = query.where("has_handwriting", "==", has_handwriting)
        if is_audio is not None:
            query = query.where("is_audio", "==", is_audio)
        if is_image is not None:
            query = query.where("is_image", "==", is_image)
        query = query.limit(limit)
        return [Document(**snap.to_dict()) for snap in query.stream()]

    # ---- Events ----

    def upsert_event(self, event: Event) -> None:
        ref = self._db.collection("events").document(event.id)
        ref.set(event.model_dump(), merge=True)

    def get_events_for_document(self, document_id: str) -> list[Event]:
        query = self._db.collection("events").where("document_id", "==", document_id)
        return [Event(**snap.to_dict()) for snap in query.stream()]

    def query_events(
        self,
        what_category: str | None = None,
        location_id: str | None = None,
        person_id: str | None = None,
        motive: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Event]:
        query = self._db.collection("events")
        if what_category:
            query = query.where("what_category", "==", what_category)
        if location_id:
            query = query.where("location_id", "==", location_id)
        if person_id:
            query = query.where("people_ids", "array_contains", person_id)
        if motive:
            query = query.where("motive_categories", "array_contains", motive)
        query = query.limit(limit).offset(offset)
        return [Event(**snap.to_dict()) for snap in query.stream()]

    # ---- People ----

    def upsert_person(self, person: Person) -> None:
        ref = self._db.collection("people").document(person.id)
        ref.set(person.model_dump(), merge=True)

    def get_person(self, person_id: str) -> Person | None:
        snap = self._db.collection("people").document(person_id).get()
        if not snap.exists:
            return None
        return Person(**snap.to_dict())

    def find_person_by_name(self, name: str) -> Person | None:
        query = (
            self._db.collection("people")
            .where("full_name", "==", name)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None
        return Person(**docs[0].to_dict())

    def list_people(self, role: str | None = None, limit: int = 100) -> list[Person]:
        query = self._db.collection("people")
        if role:
            query = query.where("role", "==", role)
        query = query.limit(limit)
        return [Person(**snap.to_dict()) for snap in query.stream()]

    # ---- Locations ----

    def upsert_location(self, location: Location) -> None:
        ref = self._db.collection("locations").document(location.id)
        ref.set(location.model_dump(), merge=True)

    def get_location(self, location_id: str) -> Location | None:
        snap = self._db.collection("locations").document(location_id).get()
        if not snap.exists:
            return None
        return Location(**snap.to_dict())

    def find_location_by_name(self, name: str) -> Location | None:
        query = (
            self._db.collection("locations")
            .where("name", "==", name)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None
        return Location(**docs[0].to_dict())

    # ---- Victims ----

    def upsert_victim(self, victim: Victim) -> None:
        ref = self._db.collection("victims").document(victim.id)
        ref.set(victim.model_dump(), merge=True)

    def get_next_victim_id(self) -> str:
        query = (
            self._db.collection("victims")
            .order_by("id", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return "victim_00001"
        last_id = docs[0].to_dict()["id"]
        num = int(last_id.split("_")[1]) + 1
        return f"victim_{num:05d}"

    # ---- Victim Identity Mapping (PRIVATE) ----

    def upsert_victim_mapping(self, mapping: VictimIdentityMapping) -> None:
        ref = self._db.collection("victim_identity_mapping").document(mapping.id)
        ref.set(mapping.model_dump(), merge=True)

    def get_all_victim_mappings(self) -> list[VictimIdentityMapping]:
        return [
            VictimIdentityMapping(**snap.to_dict())
            for snap in self._db.collection("victim_identity_mapping").stream()
        ]

    # ---- Properties ----

    def upsert_property(self, prop: Property) -> None:
        ref = self._db.collection("properties").document(prop.id)
        ref.set(prop.model_dump(), merge=True)

    def get_property(self, property_id: str) -> Property | None:
        snap = self._db.collection("properties").document(property_id).get()
        if not snap.exists:
            return None
        return Property(**snap.to_dict())

    def list_properties(self, limit: int = 100) -> list[Property]:
        query = self._db.collection("properties").limit(limit)
        return [Property(**snap.to_dict()) for snap in query.stream()]

    def find_property_by_address(self, address: str) -> Property | None:
        query = (
            self._db.collection("properties")
            .where("address", "==", address)
            .limit(1)
        )
        docs = list(query.stream())
        if not docs:
            return None
        return Property(**docs[0].to_dict())

    def get_exhibits_for_property(self, property_id: str) -> list[Exhibit]:
        query = (
            self._db.collection("exhibits")
            .where("property_id", "==", property_id)
        )
        return [Exhibit(**snap.to_dict()) for snap in query.stream()]

    def get_documents_for_property(self, property_id: str) -> list[Document]:
        query = (
            self._db.collection("documents")
            .where("property_id", "==", property_id)
        )
        return [Document(**snap.to_dict()) for snap in query.stream()]

    # ---- Exhibits ----

    def upsert_exhibit(self, exhibit: Exhibit) -> None:
        ref = self._db.collection("exhibits").document(exhibit.id)
        ref.set(exhibit.model_dump(), merge=True)

    def get_exhibit(self, exhibit_id: str) -> Exhibit | None:
        snap = self._db.collection("exhibits").document(exhibit_id).get()
        if not snap.exists:
            return None
        return Exhibit(**snap.to_dict())

    def list_exhibits(self, limit: int = 200) -> list[Exhibit]:
        query = self._db.collection("exhibits").limit(limit)
        return [Exhibit(**snap.to_dict()) for snap in query.stream()]

    def get_documents_for_exhibit(self, exhibit_id: str) -> list[Document]:
        query = (
            self._db.collection("documents")
            .where("exhibit_id", "==", exhibit_id)
        )
        return [Document(**snap.to_dict()) for snap in query.stream()]

    # ---- Image Elements ----

    def upsert_image_element(self, element: ImageElement) -> None:
        ref = self._db.collection("image_elements").document(element.id)
        ref.set(element.model_dump(), merge=True)

    def get_elements_for_document(self, document_id: str) -> list[ImageElement]:
        query = (
            self._db.collection("image_elements")
            .where("document_id", "==", document_id)
        )
        return [ImageElement(**snap.to_dict()) for snap in query.stream()]

    def query_image_elements(
        self,
        category: str | None = None,
        document_id: str | None = None,
        notable_only: bool = False,
        limit: int = 100,
    ) -> list[ImageElement]:
        query = self._db.collection("image_elements")
        if category:
            query = query.where("category", "==", category)
        if document_id:
            query = query.where("document_id", "==", document_id)
        if notable_only:
            query = query.where("notable", "==", True)
        query = query.limit(limit)
        return [ImageElement(**snap.to_dict()) for snap in query.stream()]
