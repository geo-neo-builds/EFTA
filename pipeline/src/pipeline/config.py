"""Configuration loaded from environment variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "efta-analysis")
    gcp_region: str = os.getenv("GCP_REGION", "us-central1")
    gcs_bucket_name: str = os.getenv("GCS_BUCKET_NAME", "efta-analysis-documents")
    firestore_database: str = os.getenv("FIRESTORE_DATABASE", "(default)")
    document_ai_processor_id: str = os.getenv("DOCUMENT_AI_PROCESSOR_ID", "")
    document_ai_location: str = os.getenv("DOCUMENT_AI_LOCATION", "us")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    pubsub_topic_downloaded: str = os.getenv("PUBSUB_TOPIC_DOWNLOADED", "document-downloaded")
    pubsub_topic_ocr_complete: str = os.getenv("PUBSUB_TOPIC_OCR_COMPLETE", "document-ocr-complete")
    victim_encryption_key_secret: str = os.getenv(
        "VICTIM_ENCRYPTION_KEY_SECRET", "victim-encryption-key"
    )


config = Config()
