"""Pydantic models for LLM extraction output validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _none_to_empty(v):
    """Coerce None to empty string — Gemini sometimes returns null for optional fields."""
    return "" if v is None else v


class ExtractedVictim(BaseModel):
    """A victim reference extracted from a document."""
    placeholder: str  # e.g., "VICTIM_1" — LLM's internal placeholder
    identifying_info: dict = Field(default_factory=dict)  # age, description, etc.


class ExtractedPerson(BaseModel):
    """A non-victim person extracted from a document."""
    name: str
    role: str = "other"  # perpetrator, associate, witness, law_enforcement, legal, other
    description: str = ""

    _normalize_role = field_validator("role", mode="before")(_none_to_empty)
    _normalize_desc = field_validator("description", mode="before")(_none_to_empty)


class ExtractedLocation(BaseModel):
    """A location extracted from a document."""
    name: str
    city: str = ""
    state: str = ""
    country: str = ""

    _normalize_city = field_validator("city", mode="before")(_none_to_empty)
    _normalize_state = field_validator("state", mode="before")(_none_to_empty)
    _normalize_country = field_validator("country", mode="before")(_none_to_empty)


class ExtractedEvent(BaseModel):
    """A single event/incident extracted from a document."""

    # What
    what_category: str  # crime, meeting, transaction, travel, communication, other
    what_subcategory: str = ""
    what_description: str

    # Where
    location: ExtractedLocation | None = None

    # When
    date_raw_text: str = ""
    date_start: str = ""  # ISO format or partial like "1999" or "March 2002"
    date_end: str = ""
    date_precision: str = "unknown"  # exact, month, year, approximate, unknown

    # Who (perpetrators/associates by name)
    people: list[ExtractedPerson] = Field(default_factory=list)

    # Victims (by placeholder only — NEVER by name)
    victims: list[ExtractedVictim] = Field(default_factory=list)

    # Why / Motive
    motive_categories: list[str] = Field(default_factory=list)
    motive_description: str = ""

    # Metadata
    confidence: float = 0.0  # 0.0-1.0
    source_text: str = ""  # the text excerpt this was extracted from
    page_number: int | None = None

    # Coerce nulls from Gemini to empty strings on string fields
    _norm_subcat = field_validator("what_subcategory", mode="before")(_none_to_empty)
    _norm_desc = field_validator("what_description", mode="before")(_none_to_empty)
    _norm_date_raw = field_validator("date_raw_text", mode="before")(_none_to_empty)
    _norm_date_start = field_validator("date_start", mode="before")(_none_to_empty)
    _norm_date_end = field_validator("date_end", mode="before")(_none_to_empty)
    _norm_precision = field_validator("date_precision", mode="before")(_none_to_empty)
    _norm_motive_desc = field_validator("motive_description", mode="before")(_none_to_empty)
    _norm_source_text = field_validator("source_text", mode="before")(_none_to_empty)


class ExtractionResult(BaseModel):
    """Complete extraction result from a document or page."""
    events: list[ExtractedEvent] = Field(default_factory=list)
    people: list[ExtractedPerson] = Field(default_factory=list)
    victims: list[ExtractedVictim] = Field(default_factory=list)
    locations: list[ExtractedLocation] = Field(default_factory=list)

    # Document-level classification
    document_type: str = "other"
    document_type_confidence: float = 0.0
    document_summary: str = ""

    _norm_doc_type = field_validator("document_type", mode="before")(_none_to_empty)
    _norm_summary = field_validator("document_summary", mode="before")(_none_to_empty)
