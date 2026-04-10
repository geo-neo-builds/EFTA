"""Resolves raw FBI evidence card addresses into Property records.

Different photos in the same data set may write the same address slightly
differently (e.g. "9 East 71st St" vs "9 E 71st Street NY"). This module
normalizes addresses and matches them against known Epstein properties so
all photos from the same physical location end up sharing one Property.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Property

logger = logging.getLogger(__name__)


# Known Epstein properties — used to give each location a friendly nickname.
# The matching is fuzzy: any address containing one of the keywords gets
# stamped with the corresponding nickname.
KNOWN_PROPERTIES: list[dict] = [
    {
        "nickname": "9 East 71st Street (NYC Townhouse)",
        "name": "9 East 71st Street",
        "city": "New York",
        "state": "NY",
        "country": "United States",
        "keywords": ["9 e 71", "9 east 71", "71st st", "71st street"],
    },
    {
        "nickname": "Little St. James",
        "name": "Little St. James Island",
        "city": "Little St. James",
        "state": "USVI",
        "country": "U.S. Virgin Islands",
        "keywords": ["little st james", "little saint james", "little st. james", "lsj"],
    },
    {
        "nickname": "Great St. James",
        "name": "Great St. James Island",
        "city": "Great St. James",
        "state": "USVI",
        "country": "U.S. Virgin Islands",
        "keywords": ["great st james", "great saint james", "great st. james"],
    },
    {
        "nickname": "Zorro Ranch",
        "name": "Zorro Ranch",
        "city": "Stanley",
        "state": "NM",
        "country": "United States",
        "keywords": ["zorro ranch", "stanley, nm", "stanley nm"],
    },
    {
        "nickname": "El Brillo Way (Palm Beach)",
        "name": "358 El Brillo Way",
        "city": "Palm Beach",
        "state": "FL",
        "country": "United States",
        "keywords": ["el brillo", "palm beach", "358 el brillo"],
    },
    {
        "nickname": "Avenue Foch (Paris)",
        "name": "22 Avenue Foch",
        "city": "Paris",
        "state": None,
        "country": "France",
        "keywords": ["avenue foch", "ave foch", "paris"],
    },
]


class PropertyResolver:
    """Looks up or creates a Property record from a raw address string."""

    def __init__(self, firestore_client: FirestoreClient | None = None):
        self.db = firestore_client or FirestoreClient()
        # In-memory cache: normalized address → Property to avoid repeated lookups
        self._cache: dict[str, Property] = {}

    def resolve(self, raw_address: str | None) -> Property | None:
        """Find or create a Property for the given address."""
        if not raw_address:
            return None

        normalized = self._normalize(raw_address)
        if not normalized:
            return None

        # Check cache
        if normalized in self._cache:
            return self._cache[normalized]

        # Try to match against known properties
        match = self._match_known(normalized)
        if match is not None:
            prop_id = self._make_id(match["name"])
            existing = self.db.get_property(prop_id)
            if existing is not None:
                # Add this raw address as an alias if not already present
                if raw_address not in existing.aliases:
                    existing.aliases.append(raw_address)
                    existing.updated_at = datetime.now(timezone.utc)
                    self.db.upsert_property(existing)
                self._cache[normalized] = existing
                return existing

            # Create new property from known template
            prop = Property(
                id=prop_id,
                name=match["name"],
                nickname=match["nickname"],
                address=raw_address,
                city=match.get("city"),
                state=match.get("state"),
                country=match.get("country"),
                aliases=[raw_address],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            self.db.upsert_property(prop)
            self._cache[normalized] = prop
            logger.info("Created property: %s (%s)", prop.name, prop.nickname)
            return prop

        # No known match — create a new property from the raw address
        prop_id = self._make_id(normalized)
        existing = self.db.get_property(prop_id)
        if existing is not None:
            self._cache[normalized] = existing
            return existing

        prop = Property(
            id=prop_id,
            name=raw_address,
            address=raw_address,
            aliases=[raw_address],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db.upsert_property(prop)
        self._cache[normalized] = prop
        logger.info("Created unknown property: %s", prop.name)
        return prop

    @staticmethod
    def _normalize(address: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        s = address.lower().strip()
        s = re.sub(r"[.,;]", "", s)
        s = re.sub(r"\s+", " ", s)
        return s

    @staticmethod
    def _match_known(normalized: str) -> dict | None:
        for prop in KNOWN_PROPERTIES:
            for keyword in prop["keywords"]:
                if keyword in normalized:
                    return prop
        return None

    @staticmethod
    def _make_id(name: str) -> str:
        seed = name.lower().strip()
        return f"prop_{hashlib.md5(seed.encode()).hexdigest()[:12]}"
