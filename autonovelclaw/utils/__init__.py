"""Token estimation and context-window management utilities."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Average English: ~4 characters per token (conservative)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length (fast, no dependencies)."""
    return len(text) // CHARS_PER_TOKEN


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    # Try to cut at a paragraph boundary
    truncated = text[:max_chars]
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars * 0.8:
        return truncated[:last_para]
    # Fall back to sentence boundary
    last_period = truncated.rfind(". ")
    if last_period > max_chars * 0.8:
        return truncated[:last_period + 1]
    return truncated


def chunk_for_context(
    text: str,
    max_tokens: int = 4000,
    overlap_tokens: int = 200,
) -> list[str]:
    """Split text into chunks that fit within a token budget, with overlap."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]

        # Try to break at paragraph boundary
        if end < len(text):
            last_para = chunk.rfind("\n\n")
            if last_para > max_chars * 0.7:
                chunk = chunk[:last_para]
                end = start + last_para

        chunks.append(chunk.strip())
        start = end - overlap_chars  # overlap for continuity

    return chunks


def word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def reading_time_minutes(text: str, wpm: int = 250) -> float:
    """Estimate reading time in minutes."""
    return word_count(text) / wpm
