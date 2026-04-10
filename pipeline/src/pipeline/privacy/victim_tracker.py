"""Victim numbering and encrypted identity mapping.

Ensures victims are tracked consistently across documents
while keeping their real identities encrypted and private.
"""

from __future__ import annotations

import hashlib
import json
import logging
from base64 import b64decode, b64encode

from cryptography.fernet import Fernet
from google.cloud import secretmanager

from pipeline.config import config
from pipeline.db.firestore_client import FirestoreClient
from pipeline.db.models import Victim, VictimIdentityMapping

logger = logging.getLogger(__name__)


class VictimTracker:
    """Manages victim numbering and encrypted identity mapping.

    Each victim gets a sequential ID (victim_00001, victim_00002, etc.).
    Real identifying information is encrypted with AES and stored separately.
    The tracker can match new victim references against existing ones
    to maintain consistent numbering across documents.
    """

    def __init__(self, firestore_client: FirestoreClient | None = None):
        self.db = firestore_client or FirestoreClient()
        self._fernet = self._load_encryption_key()
        self._mapping_cache: dict[str, str] | None = None

    def _load_encryption_key(self) -> Fernet:
        """Load the encryption key from Secret Manager."""
        client = secretmanager.SecretManagerServiceClient()
        name = (
            f"projects/{config.gcp_project_id}"
            f"/secrets/{config.victim_encryption_key_secret}/versions/latest"
        )
        response = client.access_secret_version(request={"name": name})
        key_hex = response.payload.data.decode("utf-8").strip()
        # Convert 256-bit hex key to Fernet-compatible base64 key (32 bytes)
        key_bytes = bytes.fromhex(key_hex)
        fernet_key = b64encode(key_bytes)
        return Fernet(fernet_key)

    def get_or_create_victim_id(
        self,
        identifying_info: dict,
        document_id: str,
    ) -> str:
        """Look up or create a victim ID based on identifying information.

        Args:
            identifying_info: Dict with keys like "name", "age", "description"
                that can be used to match this victim across documents.
            document_id: The document where this victim was found.

        Returns:
            A victim ID like "victim_00001".
        """
        # Create a normalized fingerprint for matching
        fingerprint = self._create_fingerprint(identifying_info)

        # Check existing mappings for a match
        existing_id = self._find_existing_victim(fingerprint)
        if existing_id:
            # Update the existing victim with this document reference
            self._add_document_reference(existing_id, document_id)
            logger.info("Matched existing victim: %s", existing_id)
            return existing_id

        # Create a new victim
        victim_id = self.db.get_next_victim_id()

        # Store the victim record (public, no identifying info)
        victim = Victim(
            id=victim_id,
            document_ids=[document_id],
        )
        self.db.upsert_victim(victim)

        # Store the encrypted identity mapping (private)
        encrypted = self._encrypt(json.dumps(identifying_info))
        mapping = VictimIdentityMapping(
            id=hashlib.md5(fingerprint.encode()).hexdigest()[:16],
            victim_id=victim_id,
            encrypted_identifiers=encrypted,
            document_references=[document_id],
        )
        self.db.upsert_victim_mapping(mapping)

        # Invalidate cache
        self._mapping_cache = None

        logger.info("Created new victim: %s", victim_id)
        return victim_id

    def _create_fingerprint(self, identifying_info: dict) -> str:
        """Create a normalized fingerprint from identifying info for matching.

        Normalizes names, removes whitespace variations, lowercases, etc.
        """
        parts = []
        if "name" in identifying_info:
            name = identifying_info["name"].strip().lower()
            # Normalize common name variations
            name = " ".join(name.split())  # collapse whitespace
            parts.append(f"name:{name}")
        if "age" in identifying_info:
            parts.append(f"age:{identifying_info['age']}")
        if "description" in identifying_info:
            desc = identifying_info["description"].strip().lower()[:100]
            parts.append(f"desc:{desc}")

        return "|".join(sorted(parts))

    def _find_existing_victim(self, fingerprint: str) -> str | None:
        """Check if a victim with this fingerprint already exists."""
        if self._mapping_cache is None:
            self._load_mapping_cache()

        return self._mapping_cache.get(fingerprint)

    def _load_mapping_cache(self):
        """Load all victim mappings and build a fingerprint→victim_id cache."""
        self._mapping_cache = {}
        mappings = self.db.get_all_victim_mappings()
        for mapping in mappings:
            try:
                decrypted = self._decrypt(mapping.encrypted_identifiers)
                info = json.loads(decrypted)
                fingerprint = self._create_fingerprint(info)
                self._mapping_cache[fingerprint] = mapping.victim_id
            except Exception:
                logger.exception(
                    "Failed to decrypt victim mapping %s", mapping.id
                )

    def _add_document_reference(self, victim_id: str, document_id: str):
        """Add a document reference to an existing victim."""
        # Update victim record
        victim = Victim(id=victim_id, document_ids=[document_id])
        existing = self.db._db.collection("victims").document(victim_id).get()
        if existing.exists:
            data = existing.to_dict()
            doc_ids = data.get("document_ids", [])
            if document_id not in doc_ids:
                doc_ids.append(document_id)
                self.db._db.collection("victims").document(victim_id).update(
                    {"document_ids": doc_ids}
                )

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt a string and return base64-encoded ciphertext."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext string."""
        return self._fernet.decrypt(ciphertext.encode()).decode()
