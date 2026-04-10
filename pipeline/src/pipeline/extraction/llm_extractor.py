"""Gemini-based structured data extraction from OCR/transcription text."""

from __future__ import annotations

import json
import logging
import re

from google import genai
from google.genai import types

from pipeline.config import config
from pipeline.extraction.prompts import EXTRACTION_PROMPT, PAGE_EXTRACTION_PROMPT, SYSTEM_PROMPT
from pipeline.extraction.schema import ExtractionResult

logger = logging.getLogger(__name__)

# Max characters per LLM call — split longer documents into chunks
MAX_CHARS_PER_CALL = 30_000


class LLMExtractor:
    """Extracts structured data from text using Gemini."""

    def __init__(self):
        self._client = genai.Client(
            vertexai=True,
            project=config.gcp_project_id,
            location=config.gcp_region,
        )
        self._model = config.gemini_model

    def extract_from_text(
        self,
        text: str,
        page_number: int | None = None,
    ) -> ExtractionResult:
        """Extract structured events from a text string.

        Args:
            text: The document text to analyze.
            page_number: Optional page number for context.

        Returns:
            ExtractionResult with all extracted data.
        """
        if not text.strip():
            return ExtractionResult()

        if page_number is not None:
            prompt = PAGE_EXTRACTION_PROMPT.format(
                text=text,
                page_number=page_number,
            )
        else:
            prompt = EXTRACTION_PROMPT.format(text=text)

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1,  # Low temperature for factual extraction
                max_output_tokens=65536,
                response_mime_type="application/json",
            ),
        )

        # Parse the JSON response
        try:
            raw_text = response.text.strip()
            # Clean up any markdown code fences
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
            data = json.loads(raw_text)
            result = ExtractionResult(**data)
        except (json.JSONDecodeError, ValueError):
            logger.exception("Failed to parse LLM response: %s", response.text[:500])
            return ExtractionResult()

        logger.info(
            "Extracted %d events, %d people, %d victims, %d locations",
            len(result.events),
            len(result.people),
            len(result.victims),
            len(result.locations),
        )
        return result

    def extract_from_document(self, pages: list[dict]) -> ExtractionResult:
        """Extract structured data from a multi-page document.

        Processes pages in chunks to stay within token limits,
        then merges the results.

        Args:
            pages: List of page dicts with "page_number" and "text" keys.

        Returns:
            Merged ExtractionResult from all pages.
        """
        all_results = ExtractionResult()

        # Build chunks of pages that fit within the character limit
        current_chunk = []
        current_chars = 0

        for page in pages:
            page_text = page.get("text", "")
            if not page_text.strip():
                continue

            if current_chars + len(page_text) > MAX_CHARS_PER_CALL and current_chunk:
                # Process current chunk
                result = self._process_chunk(current_chunk)
                all_results = self._merge_results(all_results, result)
                current_chunk = []
                current_chars = 0

            current_chunk.append(page)
            current_chars += len(page_text)

        # Process remaining chunk
        if current_chunk:
            result = self._process_chunk(current_chunk)
            all_results = self._merge_results(all_results, result)

        return all_results

    def _process_chunk(self, pages: list[dict]) -> ExtractionResult:
        """Process a chunk of pages."""
        if len(pages) == 1:
            page = pages[0]
            return self.extract_from_text(
                page["text"],
                page_number=page.get("page_number"),
            )

        # Combine pages into a single text with page markers
        combined_text = ""
        for page in pages:
            page_num = page.get("page_number", "?")
            combined_text += f"\n--- Page {page_num} ---\n{page['text']}\n"

        return self.extract_from_text(combined_text)

    @staticmethod
    def _merge_results(a: ExtractionResult, b: ExtractionResult) -> ExtractionResult:
        """Merge two extraction results."""
        return ExtractionResult(
            events=a.events + b.events,
            people=a.people + b.people,
            victims=a.victims + b.victims,
            locations=a.locations + b.locations,
        )
