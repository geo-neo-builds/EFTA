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
    VISION_PROCESSING = "vision_processing"
    VISION_COMPLETE = "vision_complete"
    VISION_FAILED = "vision_failed"
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


class DocumentType(str, Enum):
    """Content-level classification of a document, independent of file format."""
    EMAIL = "email"
    HANDWRITTEN_NOTE = "handwritten_note"
    LEGAL_FILING = "legal_filing"          # motions, briefs, court orders
    COURT_TRANSCRIPT = "court_transcript"
    DEPOSITION = "deposition"
    CONTRACT = "contract"
    FINANCIAL_RECORD = "financial_record"  # wire transfers, statements, invoices
    FLIGHT_LOG = "flight_log"
    PHONE_RECORD = "phone_record"
    PHOTOGRAPH = "photograph"
    EVIDENCE_CARD = "evidence_card"        # FBI metadata card with date/case ID/location
    EXHIBIT_MARKER = "exhibit_marker"      # FBI room placard with letter (e.g., "H", "JJ")
    AUDIO_RECORDING = "audio_recording"
    VIDEO_RECORDING = "video_recording"
    CORRESPONDENCE = "correspondence"      # letters, memos
    GOVERNMENT_RECORD = "government_record"  # FBI/BOP/CBP files
    NEWS_ARTICLE = "news_article"
    OTHER = "other"


class RoomType(str, Enum):
    """Type of room or area shown in an evidence photograph."""
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    KITCHEN = "kitchen"
    DINING_ROOM = "dining_room"
    LIVING_ROOM = "living_room"
    OFFICE = "office"
    LIBRARY = "library"
    GYM = "gym"
    CLOSET = "closet"
    HALLWAY = "hallway"
    ENTRYWAY = "entryway"
    STAIRCASE = "staircase"
    GARAGE = "garage"
    POOL_AREA = "pool_area"
    SPA_AREA = "spa_area"
    BASEMENT = "basement"
    ATTIC = "attic"
    UTILITY_ROOM = "utility_room"
    LAUNDRY_ROOM = "laundry_room"
    STORAGE_ROOM = "storage_room"
    EXTERIOR = "exterior"
    VEHICLE_INTERIOR = "vehicle_interior"
    AIRCRAFT_INTERIOR = "aircraft_interior"
    BOAT_INTERIOR = "boat_interior"
    OTHER = "other"
    UNKNOWN = "unknown"


class ElementCategory(str, Enum):
    """High-level categories for items identified in evidence photos.

    Used as denormalized filter tags on the Document. Detailed individual
    items are stored as ImageElement records in a separate collection.
    """
    ARTWORK = "artwork"                  # paintings, sculptures, statues
    FRAMED_PHOTO = "framed_photo"
    BOOK = "book"
    FURNITURE = "furniture"
    COMPUTER = "computer"
    PHONE = "phone"
    CAMERA = "camera"
    OTHER_ELECTRONICS = "other_electronics"
    KITCHEN_ITEM = "kitchen_item"
    BATHROOM_FIXTURE = "bathroom_fixture"
    EXERCISE_EQUIPMENT = "exercise_equipment"
    CLOTHING = "clothing"
    SHOES = "shoes"
    JEWELRY = "jewelry"
    LUGGAGE = "luggage"
    DOCUMENT_PAPER = "document_paper"   # papers, files, folders visible in scene
    MEDICAL_ITEM = "medical_item"
    SEXUAL_ITEM = "sexual_item"          # adult items, bondage gear
    WEAPON = "weapon"
    DRUG = "drug"
    DECORATIVE = "decorative"            # vases, candles, etc.
    LIGHTING_FIXTURE = "lighting_fixture"
    PLANT = "plant"
    FOOD = "food"
    DISHWARE = "dishware"
    BEDDING = "bedding"
    MUSICAL_INSTRUMENT = "musical_instrument"
    VEHICLE = "vehicle"
    PEOPLE = "people"
    OTHER = "other"


# --- Document ---


class Document(BaseModel):
    id: str
    source_url: str
    source_type: SourceType
    filename: str
    gcs_path: str
    gcs_text_path: Optional[str] = None
    gcs_vision_path: Optional[str] = None  # gs path of vision_result.json
    download_date: datetime
    file_hash: str
    page_count: int = 0
    processing_status: ProcessingStatus = ProcessingStatus.DOWNLOADED
    ocr_completed_at: Optional[datetime] = None
    vision_completed_at: Optional[datetime] = None
    analysis_completed_at: Optional[datetime] = None
    last_checked_at: datetime
    version: int = 1
    error_message: Optional[str] = None

    # Content classification (set during LLM extraction)
    document_type: Optional[DocumentType] = None
    document_type_confidence: float = 0.0

    # Format flags (set during OCR)
    has_handwriting: bool = False
    is_audio: bool = False
    is_image: bool = False

    # ---- Vision-derived fields (for evidence photos) ----

    # Setting
    room_type: Optional[RoomType] = None
    indoor: Optional[bool] = None  # true if indoor, false if outdoor

    # Exhibit/Property grouping
    is_exhibit_marker: bool = False    # photo contains an FBI room placard
    exhibit_label: Optional[str] = None  # the letter/code on the placard (e.g., "H", "JJ")
    is_evidence_card: bool = False     # photo contains an FBI metadata card
    exhibit_id: Optional[str] = None   # which Exhibit this photo belongs to
    property_id: Optional[str] = None  # which Property this photo belongs to

    # Extracted FBI evidence card metadata (when applicable)
    photo_date: Optional[str] = None   # raw date string from evidence card
    photo_case_id: Optional[str] = None
    photo_location_address: Optional[str] = None

    # Element tags (denormalized for fast filtering)
    element_categories: list[ElementCategory] = Field(default_factory=list)

    # People info (no identifying details)
    people_count: int = 0
    has_redactions: bool = False

    # Free-text descriptions
    vision_summary: Optional[str] = None
    document_summary: Optional[str] = None  # set by either OCR-LLM or Vision pipeline


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


# --- Property ---


class Property(BaseModel):
    """A physical location/property that the FBI raided and photographed.

    Examples: '9 East 71st St NYC' (Manhattan townhouse),
    'Little St. James', 'Zorro Ranch', 'El Brillo Way Palm Beach'.
    Properties group Exhibits, which group Photos.
    """
    id: str                              # auto-generated stable id
    name: str                            # human-friendly name (e.g., "9 East 71st St")
    address: Optional[str] = None        # full street address as found on FBI cards
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    nickname: Optional[str] = None       # well-known name (e.g., "Little St. James")
    case_ids: list[str] = Field(default_factory=list)  # all FBI case IDs that reference this property
    aliases: list[str] = Field(default_factory=list)   # other ways this property is referred to
    exhibit_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    exhibit_count: int = 0
    photo_count: int = 0
    raid_dates: list[str] = Field(default_factory=list)  # dates from FBI evidence cards
    summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Exhibit ---


class Exhibit(BaseModel):
    """A group of evidence photos belonging to a single FBI exhibit/room.

    Defined by the photo containing an FBI room placard (e.g., letter "H")
    and continuing through subsequent photos until the next placard appears.
    Belongs to a Property.
    """
    id: str                              # auto-generated id
    label: str                           # e.g., "H", "JJ", "B-2"
    property_id: Optional[str] = None    # which Property this exhibit belongs to
    starting_document_id: str            # the photo containing the placard
    document_ids: list[str] = Field(default_factory=list)  # all photos in this exhibit
    photo_count: int = 0
    room_type: Optional[RoomType] = None
    location_address: Optional[str] = None  # from the most recent evidence card
    case_id: Optional[str] = None
    photo_date: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- ImageElement ---


class ImageElement(BaseModel):
    """A notable element identified inside an evidence photo.

    Allows fine-grained queries like "all photos containing books titled X"
    or "all photos containing artwork by artist Y", in addition to the
    high-level category filter on the Document record itself.
    """
    id: str                              # auto-generated
    document_id: str                     # which photo
    page_number: int = 1                 # which page if multi-page
    category: ElementCategory
    description: str                     # short free-text description
    notable: bool = False                # particularly noteworthy

    # Optional type-specific fields
    title: Optional[str] = None          # e.g., book title or artwork name
    creator: Optional[str] = None        # author or artist
    quantity: Optional[int] = None       # e.g., "5 books"
    confidence: float = 0.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
