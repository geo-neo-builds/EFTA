"""Pydantic models for Gemini Vision extraction output."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _none_to_empty(v):
    return "" if v is None else v


def _none_to_false(v):
    return False if v is None else v


def _none_to_zero_int(v):
    return 0 if v is None else v


def _none_to_zero_float(v):
    return 0.0 if v is None else v


def _none_to_empty_list(v):
    return [] if v is None else v


class FBIMetadata(BaseModel):
    is_fbi_evidence_card: bool = False
    date: Optional[str] = None
    case_id: Optional[str] = None
    photographer: Optional[str] = None
    location_label: Optional[str] = None
    room_marker: Optional[str] = None  # FBI room placard letter, e.g., "H", "JJ"

    _is_card = field_validator("is_fbi_evidence_card", mode="before")(_none_to_false)


class PeopleVisible(BaseModel):
    count: int = 0
    public_figures_identified: list[str] = Field(default_factory=list)
    redacted_count: int = 0
    generic_description: str = ""

    _g = field_validator("generic_description", mode="before")(_none_to_empty)
    _c = field_validator("count", mode="before")(_none_to_zero_int)
    _rc = field_validator("redacted_count", mode="before")(_none_to_zero_int)
    _pf = field_validator("public_figures_identified", mode="before")(_none_to_empty_list)


class ExtractedElement(BaseModel):
    """A notable element identified in an image."""
    category: str  # see ElementCategory enum
    description: str  # short free-text description
    notable: bool = False
    title: Optional[str] = None    # for books, artwork
    creator: Optional[str] = None  # for books (author) or artwork (artist)
    quantity: Optional[int] = None
    confidence: float = 0.5

    _desc = field_validator("description", mode="before")(_none_to_empty)
    _notable = field_validator("notable", mode="before")(_none_to_false)
    _conf = field_validator("confidence", mode="before")(_none_to_zero_float)


class VisionResult(BaseModel):
    """Structured Gemini Vision analysis of a single image/page."""

    # Document-level classification
    document_type: str = "photograph"
    document_type_confidence: float = 0.0
    document_summary: str = ""

    # Setting / room
    indoor: Optional[bool] = None
    room_type: str = "unknown"
    setting_description: str = ""

    # Exhibit / FBI metadata detection
    is_evidence_card: bool = False    # FBI metadata card photo
    is_exhibit_marker: bool = False   # FBI room placard photo
    exhibit_label: Optional[str] = None  # the letter on a placard
    fbi_metadata: FBIMetadata = Field(default_factory=FBIMetadata)

    # Elements (structured)
    elements: list[ExtractedElement] = Field(default_factory=list)
    element_categories: list[str] = Field(default_factory=list)

    # People
    people_visible: PeopleVisible = Field(default_factory=PeopleVisible)

    # Other
    visible_text: list[str] = Field(default_factory=list)
    redactions_present: bool = False
    redaction_notes: str = ""
    evidentiary_notes: str = ""
    confidence: float = 0.0

    _summary = field_validator("document_summary", mode="before")(_none_to_empty)
    _doc_type = field_validator("document_type", mode="before")(_none_to_empty)
    _setting = field_validator("setting_description", mode="before")(_none_to_empty)
    _room = field_validator("room_type", mode="before")(_none_to_empty)
    _redact_notes = field_validator("redaction_notes", mode="before")(_none_to_empty)
    _ev_notes = field_validator("evidentiary_notes", mode="before")(_none_to_empty)
    _redactions = field_validator("redactions_present", mode="before")(_none_to_false)
    _is_card = field_validator("is_evidence_card", mode="before")(_none_to_false)
    _is_marker = field_validator("is_exhibit_marker", mode="before")(_none_to_false)
    _vt = field_validator("visible_text", mode="before")(_none_to_empty_list)
    _ec = field_validator("element_categories", mode="before")(_none_to_empty_list)
    _els = field_validator("elements", mode="before")(_none_to_empty_list)
    _conf = field_validator("confidence", mode="before")(_none_to_zero_float)
    _doc_conf = field_validator("document_type_confidence", mode="before")(_none_to_zero_float)
