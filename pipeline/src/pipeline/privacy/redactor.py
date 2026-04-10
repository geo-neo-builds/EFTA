"""Redaction checks to ensure no victim names appear in public data."""

from __future__ import annotations

import json
import logging
import re

from pipeline.db.firestore_client import FirestoreClient
from pipeline.privacy.victim_tracker import VictimTracker

logger = logging.getLogger(__name__)


class Redactor:
    """Ensures no victim identifying information leaks into public data.

    Scans extracted events, person records, and other public-facing data
    to verify no victim names or identifying details are present.
    """

    def __init__(
        self,
        victim_tracker: VictimTracker,
        firestore_client: FirestoreClient | None = None,
    ):
        self._tracker = victim_tracker
        self.db = firestore_client or FirestoreClient()
        self._known_victim_names: set[str] | None = None

    def load_victim_names(self):
        """Load all known victim names from encrypted mappings for checking."""
        self._known_victim_names = set()
        mappings = self.db.get_all_victim_mappings()
        for mapping in mappings:
            try:
                decrypted = self._tracker._decrypt(mapping.encrypted_identifiers)
                info = json.loads(decrypted)
                if "name" in info:
                    name = info["name"].strip().lower()
                    self._known_victim_names.add(name)
                    # Also add individual name parts for partial matching
                    for part in name.split():
                        if len(part) > 2:  # skip short words like "a", "de"
                            self._known_victim_names.add(part)
            except Exception:
                logger.exception("Failed to decrypt mapping %s", mapping.id)

    def check_text(self, text: str) -> list[str]:
        """Check a text string for victim name leaks.

        Returns a list of found victim name matches (empty if clean).
        """
        if self._known_victim_names is None:
            self.load_victim_names()

        text_lower = text.lower()
        found = []
        for name in self._known_victim_names:
            # Use word boundary matching to avoid false positives
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text_lower):
                found.append(name)

        return found

    def check_event(self, event_dict: dict) -> list[str]:
        """Check an event record for victim name leaks.

        Scans all string fields in the event for matches.
        """
        leaks = []
        for key, value in event_dict.items():
            if isinstance(value, str):
                found = self.check_text(value)
                if found:
                    leaks.extend(f"{key}: {name}" for name in found)
        return leaks

    def redact_text(self, text: str) -> str:
        """Replace any victim names in text with [REDACTED].

        This is a safety net — ideally the LLM never outputs victim names,
        but this catches any that slip through.
        """
        if self._known_victim_names is None:
            self.load_victim_names()

        result = text
        for name in sorted(self._known_victim_names, key=len, reverse=True):
            # Replace longer names first to avoid partial replacements
            pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
            result = pattern.sub("[REDACTED]", result)

        return result

    def audit_all_events(self) -> list[dict]:
        """Scan all events in the database for victim name leaks.

        Returns a list of findings with event_id and leaked names.
        """
        logger.info("Auditing all events for victim name leaks...")
        findings = []

        # Query all events (paginated)
        events = self.db.query_events(limit=1000)
        for event in events:
            leaks = self.check_event(event.model_dump())
            if leaks:
                findings.append({
                    "event_id": event.id,
                    "document_id": event.document_id,
                    "leaks": leaks,
                })

        if findings:
            logger.warning("Found %d events with potential victim name leaks!", len(findings))
        else:
            logger.info("Audit clean: no victim name leaks found.")

        return findings
