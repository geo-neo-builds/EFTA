"""Pydantic models matching the Firestore schema."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Enums ---


class ProcessingStatus(str, Enum):
    DOWNLOADED = "downloaded"
    OCR_PROCESSING = "ocr_processing"
    OCR_COMPLETE = "ocr_complete"
    OCR_FAILED = "ocr_failed"
    ANALYSIS_PROCESSING = "analysis_processing"
    ANALYZED = "analyzed"
    ANALYSIS_FAILED = "analysis_failed"


class SourceType(str, Enum):
    DOJ = "doj"
    DROPBOX = "dropbox"
    OTHER = "other"


class EventCategory(str, Enum):
    CRIME = "crime"
    MEETING = "meeting"
    TRANSACTION = "transaction"
    TRAVEL = "travel"
    COMMUNICATION = "communication"
    OTHER = "other"


class DatePrecision(str, Enum):
    EXACT = "exact"
    MONTH = "month"
    YEAR = "year"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class PersonRole(str, Enum):
    PERPETRATOR = "perpetrator"
    ASSOCIATE = "associate"
    WITNESS = "witness"
    LAW_ENFORCEMENT = "law_enforcement"
    LEGAL = "legal"
    OTHER = "other"


class MotiveCategory(str, Enum):
    FINANCIAL_GAIN = "financial_gain"
    BUSINESS_CONNECTIONS = "business_connections"
    POLITICAL_GAIN = "political_gain"
    POLITICALLY_MOTIVATED = "politically_motivated"
    PHYSICAL_AROUSAL = "physical_arousal"
    COERCION = "coercion"
    BLACKMAIL = "blackmail"
    OTHER = "other"


# --- Document ---


class Document(BaseModel):
    id: str
    source_url: str
    source_type: SourceType
    filename: str
    gcs_path: str
    gcs_text_path: Optional[str] = None
    download_date: datetime
    file_hash: str
    page_count: int = 0
    processing_status: ProcessingStatus = ProcessingStatus.DOWNLOADED
    ocr_completed_at: Optional[datetime] = None
    analysis_completed_at: Optional[datetime] = None
    last_checked_at: datetime
    version: int = 1
    error_message: Optional[str] = None


# --- Event ---


class Event(BaseModel):
    id: str
    document_id: str
    document_page: Optional[int] = None

    # What
    what_category: EventCategory
    what_subcategory: str = ""
    what_description: str = ""

    # Where
    location_name: Optional[str] = None
    location_city: Optional[str] = None
    location_state: Optional[str] = None
    location_country: Optional[str] = None
    location_id: Optional[str] = None

    # When
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    date_raw_text: str = ""

    # Who
    people_ids: list[str] = Field(default_factory=list)

    # Victims
    victim_ids: list[str] = Field(default_factory=list)

    # Why / Motive
    motive_categories: list[MotiveCategory] = Field(default_factory=list)
    motive_description: Optional[str] = None

    # Metadata
    confidence_score: float = 0.0
    raw_text_excerpt: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Person ---


class Person(BaseModel):
    id: str
    full_name: str
    aliases: list[str] = Field(default_factory=list)
    role: PersonRole = PersonRole.OTHER
    description: Optional[str] = None
    document_ids: list[str] = Field(default_factory=list)
    event_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Location ---


class Location(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    event_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Victim ---


class Victim(BaseModel):
    id: str  # "victim_00001"
    document_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Victim Identity Mapping (PRIVATE) ---


class VictimIdentityMapping(BaseModel):
    id: str
    victim_id: str
    encrypted_identifiers: str  # AES-256 encrypted blob
    document_references: list[str] = Field(default_factory=list)
