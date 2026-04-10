"""Speech-to-Text transcription for audio files (.wav, .mp3, .mp4)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.cloud import speech, storage

from pipeline.config import config

logger = logging.getLogger(__name__)


class AudioTranscriber:
    """Transcribes audio files using Google Cloud Speech-to-Text."""

    def __init__(self, storage_client: storage.Client | None = None):
        self._speech = speech.SpeechClient()
        self._storage = storage_client or storage.Client(project=config.gcp_project_id)
        self._bucket = self._storage.bucket(config.gcs_bucket_name)

    def transcribe_document(self, gcs_path: str) -> TranscriptionResult:
        """Transcribe an audio file from GCS.

        Args:
            gcs_path: Path within the GCS bucket (e.g., "originals/doj/file.wav")

        Returns:
            TranscriptionResult with transcribed text.
        """
        logger.info("Transcribing audio: %s", gcs_path)

        gcs_uri = f"gs://{config.gcs_bucket_name}/{gcs_path}"
        audio = speech.RecognitionAudio(uri=gcs_uri)

        encoding = self._get_encoding(gcs_path)
        recognition_config = speech.RecognitionConfig(
            encoding=encoding,
            language_code="en-US",
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
            model="latest_long",  # Best for long-form audio like interviews
            use_enhanced=True,
        )

        # Use long-running recognize for files that may be lengthy
        operation = self._speech.long_running_recognize(
            config=recognition_config,
            audio=audio,
        )

        logger.info("Waiting for transcription to complete...")
        response = operation.result(timeout=600)

        # Build structured result
        segments = []
        full_text_parts = []

        for i, result in enumerate(response.results):
            if not result.alternatives:
                continue
            best = result.alternatives[0]
            segment = TranscriptionSegment(
                segment_number=i + 1,
                text=best.transcript,
                confidence=best.confidence,
                words=[
                    WordInfo(
                        word=w.word,
                        start_time=w.start_time.total_seconds() if w.start_time else 0,
                        end_time=w.end_time.total_seconds() if w.end_time else 0,
                    )
                    for w in best.words
                ],
            )
            segments.append(segment)
            full_text_parts.append(best.transcript)

        full_text = " ".join(full_text_parts)

        result = TranscriptionResult(
            full_text=full_text,
            segments=segments,
            segment_count=len(segments),
        )

        logger.info(
            "Transcription complete: %d segments, %d chars",
            result.segment_count,
            len(result.full_text),
        )
        return result

    def transcribe_and_store(self, gcs_path: str, document_id: str) -> str:
        """Transcribe an audio file and store the results in GCS.

        Returns:
            The GCS path where transcription results are stored.
        """
        result = self.transcribe_document(gcs_path)

        output_path = f"text/{document_id}/transcription.json"
        output_blob = self._bucket.blob(output_path)
        output_blob.upload_from_string(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            content_type="application/json",
        )

        logger.info("Transcription stored at gs://%s/%s", config.gcs_bucket_name, output_path)
        return output_path

    @staticmethod
    def _get_encoding(path: str) -> speech.RecognitionConfig.AudioEncoding:
        suffix = Path(path).suffix.lower()
        encodings = {
            ".wav": speech.RecognitionConfig.AudioEncoding.LINEAR16,
            ".mp3": speech.RecognitionConfig.AudioEncoding.MP3,
            ".flac": speech.RecognitionConfig.AudioEncoding.FLAC,
            ".ogg": speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        }
        return encodings.get(suffix, speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED)

    @staticmethod
    def is_audio_file(path: str) -> bool:
        """Check if a file path is an audio file we can transcribe."""
        suffix = Path(path).suffix.lower()
        return suffix in (".wav", ".mp3", ".flac", ".ogg", ".mp4")


class WordInfo:
    """A single word with timing info."""

    def __init__(self, word: str, start_time: float, end_time: float):
        self.word = word
        self.start_time = start_time
        self.end_time = end_time

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class TranscriptionSegment:
    """A segment of transcribed audio."""

    def __init__(
        self,
        segment_number: int,
        text: str,
        confidence: float,
        words: list[WordInfo] | None = None,
    ):
        self.segment_number = segment_number
        self.text = text
        self.confidence = confidence
        self.words = words or []

    def to_dict(self) -> dict:
        return {
            "segment_number": self.segment_number,
            "text": self.text,
            "confidence": self.confidence,
            "words": [w.to_dict() for w in self.words],
        }


class TranscriptionResult:
    """Complete transcription result for an audio file."""

    def __init__(self, full_text: str, segments: list[TranscriptionSegment], segment_count: int):
        self.full_text = full_text
        self.segments = segments
        self.segment_count = segment_count

    def to_dict(self) -> dict:
        return {
            "full_text": self.full_text,
            "pages": [  # Use "pages" key for compatibility with TextStore
                {
                    "page_number": s.segment_number,
                    "text": s.text,
                    "confidence": s.confidence,
                }
                for s in self.segments
            ],
            "page_count": self.segment_count,
            "segments": [s.to_dict() for s in self.segments],
        }
