"""Page-aware chunker for local embedding.

Each chunk carries its source page number so the UI can show
"found on page 47" to users.

Strategy:
  - One chunk per page when the page fits inside the model's context.
  - For pages larger than `max_chars`, split into sub-chunks on
    paragraph/sentence boundaries with a small overlap so a phrase
    spanning two sub-chunks still matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# BGE-small-en-v1.5 has a 512-token context. ~4 chars/token gives us ~2048
# char budget, and we leave headroom for tokenizer overhead.
DEFAULT_MAX_CHARS = 1800
DEFAULT_OVERLAP = 150


@dataclass
class Chunk:
    doc_id: str
    page_number: int
    sub_chunk_index: int  # 0 for single-chunk pages; else 0..N-1
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_document(
    doc_id: str,
    pages: list[tuple[int, str]],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Convert a doc's per-page text into embedding-ready chunks.

    `pages` is a list of (page_number, page_text). Pages with no
    meaningful text are skipped.
    """
    chunks: list[Chunk] = []
    for page_number, text in pages:
        text = text.strip()
        if len(text) < 20:  # skip near-empty pages
            continue

        sub_chunks = _split_long_text(text, max_chars, overlap)
        for i, sc in enumerate(sub_chunks):
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    page_number=page_number,
                    sub_chunk_index=i,
                    text=sc,
                )
            )
    return chunks


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    # First try paragraph splits; fall back to sentence splits if any
    # paragraph is still too large.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    segments: list[str] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            segments.append(p)
        else:
            segments.extend(_SENTENCE_SPLIT.split(p))

    # Greedy regroup into chunks up to max_chars, with overlap.
    chunks: list[str] = []
    buf = ""
    for seg in segments:
        if not seg:
            continue
        candidate = f"{buf}\n\n{seg}" if buf else seg
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            # Start next buffer with an overlap tail of the previous chunk.
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = f"{tail}\n\n{seg}" if tail else seg
        else:
            # Single segment longer than max_chars: hard-split.
            for i in range(0, len(seg), max_chars - overlap):
                chunks.append(seg[i : i + max_chars])
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks
