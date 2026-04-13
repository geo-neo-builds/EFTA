"""Extract entities from page text using spaCy + regex. No LLM calls.

The spaCy pass yields PERSON / ORG / GPE (geo-political entity) / LOC /
DATE labels. The regex pass yields EMAIL / PHONE / MONEY — categories
spaCy handles poorly or inconsistently.

We deliberately keep the entity set coarse here. Finer-grained tags (e.g.
"description of an artwork", "shipping label") are a later LLM pass on
filtered subsets, not something the free tier tries to solve.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Entity-type labels we keep from spaCy. Others are discarded as noise.
SPACY_KEEP_LABELS = {"PERSON", "ORG", "GPE", "LOC", "DATE", "NORP", "FAC", "EVENT"}

# US phone numbers: (xxx) xxx-xxxx, xxx-xxx-xxxx, xxx.xxx.xxxx, +1 xxx-xxx-xxxx
_RE_PHONE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\b[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# Dollar amounts: $1, $1,000, $1.50, $1,234.56, $1M, $1 million
_RE_MONEY = re.compile(
    r"\$[\d,]+(?:\.\d+)?(?:\s?(?:million|billion|thousand|M|B|K))?\b",
    re.IGNORECASE,
)


@dataclass
class Entity:
    page_number: int
    entity_type: str
    value: str
    normalized_value: str
    char_start: int | None
    char_end: int | None


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


class EntityExtractor:
    """Lazy-loading spaCy + regex entity extractor."""

    def __init__(self, spacy_model: str = "en_core_web_sm"):
        self.spacy_model = spacy_model
        self._nlp = None

    def _ensure_loaded(self):
        if self._nlp is not None:
            return
        try:
            import spacy
        except ImportError as e:
            raise RuntimeError(
                "spacy not installed. Run: pip install -e '.[local]'"
            ) from e
        try:
            self._nlp = spacy.load(
                self.spacy_model,
                # NER only — faster than full pipeline.
                disable=["lemmatizer", "attribute_ruler", "tagger", "parser"],
            )
        except OSError as e:
            raise RuntimeError(
                f"spaCy model '{self.spacy_model}' not found. "
                f"Run: python -m spacy download {self.spacy_model}"
            ) from e
        logger.info("Loaded spaCy model: %s", self.spacy_model)

    def extract_page(self, page_number: int, text: str) -> list[Entity]:
        """Extract entities from a single page's text."""
        out: list[Entity] = []
        if not text or not text.strip():
            return out

        # --- regex pass (cheap, always run first) ---
        for m in _RE_EMAIL.finditer(text):
            out.append(Entity(page_number, "EMAIL", m.group(),
                              _normalize(m.group()), m.start(), m.end()))
        for m in _RE_PHONE.finditer(text):
            out.append(Entity(page_number, "PHONE", m.group().strip(),
                              re.sub(r"\D", "", m.group()), m.start(), m.end()))
        for m in _RE_MONEY.finditer(text):
            out.append(Entity(page_number, "MONEY", m.group().strip(),
                              _normalize(m.group()), m.start(), m.end()))

        # --- spaCy NER pass ---
        self._ensure_loaded()
        # spaCy default is max_length=1,000,000; long pages are fine.
        doc = self._nlp(text)
        for ent in doc.ents:
            if ent.label_ not in SPACY_KEEP_LABELS:
                continue
            value = ent.text.strip()
            if len(value) < 2 or len(value) > 200:
                continue
            out.append(Entity(
                page_number=page_number,
                entity_type=ent.label_,
                value=value,
                normalized_value=_normalize(value),
                char_start=ent.start_char,
                char_end=ent.end_char,
            ))

        return out

    def extract_document(
        self, pages: list[tuple[int, str]]
    ) -> list[Entity]:
        """Extract entities from a document's page list."""
        entities: list[Entity] = []
        for page_number, text in pages:
            entities.extend(self.extract_page(page_number, text))
        return entities
