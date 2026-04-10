"""Pydantic models for LLM extraction output validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedVictim(BaseModel):
    """A victim reference extracted from a document."""
    placeholder: str  # e.g., "VICTIM_1" — LLM's internal placeholder
    identifying_info: dict = Field(default_factory=dict)  # age, description, etc.


class ExtractedPerson(BaseModel):
    """A non-victim person extracted from a document."""
    name: str
    role: str = "other"  # perpetrator, associate, witness, law_enforcement, legal, other
    description: str = ""


class ExtractedLocation(BaseModel):
    """A location extracted from a document."""
    name: str
    city: str = ""
    state: str = ""
    country: str = "United States"


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


class ExtractionResult(BaseModel):
    """Complete extraction result from a document or page."""
    events: list[ExtractedEvent] = Field(default_factory=list)
    people: list[ExtractedPerson] = Field(default_factory=list)
    victims: list[ExtractedVictim] = Field(default_factory=list)
    locations: list[ExtractedLocation] = Field(default_factory=list)
