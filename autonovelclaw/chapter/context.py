"""Chapter context manager — assembles and budgets context for the Writer Agent.

The Writer Agent needs to fit world codex, character profiles, previous chapter
summary, beat sheets, lessons learned, and the scene plan into a single context
window alongside the system prompt and the generated output.

This module handles:
- Token estimation for each context component
- Priority-based truncation when context exceeds budget
- Smart excerpt selection (relevant sections of codex, not random chunks)
- Rolling context for continuity (summaries of N-1, N-2 chapters)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Approximate chars per token (conservative)
CHARS_PER_TOKEN = 4


def _est_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def _truncate(text: str, max_tokens: int) -> str:
    """Truncate to approximately max_tokens, cutting at paragraph boundary."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_para = cut.rfind("\n\n")
    if last_para > max_chars * 0.7:
        return cut[:last_para] + "\n\n[... truncated ...]"
    return cut + "\n\n[... truncated ...]"


@dataclass
class ContextBudget:
    """Token budget allocation for the Writer Agent's context window."""
    total_budget: int = 30000  # conservative estimate for most models
    system_prompt: int = 6000   # the writing DNA is large
    output_reserve: int = 8000  # reserve for the generated chapter
    codex: int = 4000
    characters: int = 3000
    scene_plan: int = 4000
    previous_summary: int = 1500
    lessons: int = 1000
    genre_overlay: int = 500
    remaining: int = 2000      # buffer

    def available_for_content(self) -> int:
        """Tokens available for all context content (excluding system + output)."""
        return self.total_budget - self.system_prompt - self.output_reserve


@dataclass
class AssembledContext:
    """The assembled context ready for the Writer Agent."""
    codex_excerpt: str = ""
    characters_excerpt: str = ""
    scene_plan: str = ""
    previous_summary: str = ""
    lessons_overlay: str = ""
    genre_overlay: str = ""
    total_estimated_tokens: int = 0

    def to_dict(self) -> dict[str, str]:
        return {
            "codex_excerpt": self.codex_excerpt,
            "characters_excerpt": self.characters_excerpt,
            "scene_plan": self.scene_plan,
            "previous_summary": self.previous_summary,
            "lessons_overlay": self.lessons_overlay,
            "genre_overlay": self.genre_overlay,
        }


def extract_relevant_codex(
    full_codex: str,
    chapter_text_hint: str = "",
    location_hint: str = "",
    max_tokens: int = 4000,
) -> str:
    """Extract the most relevant sections of the codex for a chapter.

    Instead of blindly truncating, tries to find sections that match
    the chapter's setting, characters, and themes.
    """
    if _est_tokens(full_codex) <= max_tokens:
        return full_codex

    sections = re.split(r"\n(?=##\s)", full_codex)
    if not sections:
        return _truncate(full_codex, max_tokens)

    # Score sections by relevance to chapter hints
    hints = (chapter_text_hint + " " + location_hint).lower()
    scored: list[tuple[float, str]] = []

    for section in sections:
        score = 0.0
        section_lower = section.lower()

        # Geography/setting sections always relevant
        if any(kw in section_lower[:100] for kw in ["geography", "landscape", "location", "setting"]):
            score += 5.0

        # Culture sections usually relevant
        if any(kw in section_lower[:100] for kw in ["culture", "society", "custom", "religion"]):
            score += 3.0

        # Boost if section mentions the chapter's location
        if location_hint:
            hint_words = location_hint.lower().split()
            score += sum(2.0 for w in hint_words if w in section_lower and len(w) > 3)

        # Boost if section mentions characters/locations from the chapter hint
        if chapter_text_hint:
            hint_words = set(chapter_text_hint.lower().split())
            overlap = sum(1 for w in hint_words if w in section_lower and len(w) > 4)
            score += overlap * 0.5

        scored.append((score, section))

    # Sort by relevance, take top sections within budget
    scored.sort(key=lambda x: x[0], reverse=True)

    parts: list[str] = []
    tokens_used = 0
    for _score, section in scored:
        section_tokens = _est_tokens(section)
        if tokens_used + section_tokens > max_tokens:
            # Try to fit a truncated version
            remaining = max_tokens - tokens_used
            if remaining > 200:
                parts.append(_truncate(section, remaining))
            break
        parts.append(section)
        tokens_used += section_tokens

    return "\n\n".join(parts)


def extract_active_characters(
    all_profiles: str,
    character_names: list[str],
    max_tokens: int = 3000,
) -> str:
    """Extract profiles for only the characters active in this chapter."""
    if not character_names:
        return _truncate(all_profiles, max_tokens)

    sections = re.split(r"\n(?=##\s)", all_profiles)
    relevant: list[str] = []

    for section in sections:
        # Check if this section is about one of the active characters
        first_line = section.split("\n")[0].lower()
        if any(name.lower() in first_line for name in character_names):
            relevant.append(section)

    if not relevant:
        return _truncate(all_profiles, max_tokens)

    result = "\n\n".join(relevant)
    return _truncate(result, max_tokens)


def build_rolling_context(
    chapter_summaries: dict[int, str],
    current_chapter: int,
    max_tokens: int = 1500,
) -> str:
    """Build rolling continuity context from previous chapter summaries.

    Includes the full summary of the immediately previous chapter and
    shorter summaries of earlier chapters, within the token budget.
    """
    if current_chapter <= 1:
        return "This is the first chapter."

    parts: list[str] = []
    tokens_used = 0

    # Most recent chapter gets full summary
    prev = chapter_summaries.get(current_chapter - 1, "")
    if prev:
        prev_text = f"**Chapter {current_chapter - 1} (previous):** {prev}"
        parts.append(prev_text)
        tokens_used += _est_tokens(prev_text)

    # Earlier chapters get one-line summaries
    for ch in range(current_chapter - 2, 0, -1):
        summary = chapter_summaries.get(ch, "")
        if not summary:
            continue
        # Truncate to first sentence
        first_sentence = summary.split(".")[0] + "." if "." in summary else summary[:100]
        line = f"**Ch{ch}:** {first_sentence}"
        line_tokens = _est_tokens(line)
        if tokens_used + line_tokens > max_tokens:
            break
        parts.append(line)
        tokens_used += line_tokens

    return "\n".join(parts) if parts else "No previous chapters."


def assemble_writer_context(
    *,
    codex: str = "",
    characters: str = "",
    scene_plan: str = "",
    chapter_summaries: dict[int, str] | None = None,
    current_chapter: int = 1,
    lessons_overlay: str = "",
    genre_overlay: str = "",
    location_hint: str = "",
    active_character_names: list[str] | None = None,
    budget: ContextBudget | None = None,
) -> AssembledContext:
    """Assemble all context components within the token budget.

    Prioritises: scene_plan > characters > codex > previous_summary > lessons.
    """
    if budget is None:
        budget = ContextBudget()

    ctx = AssembledContext()

    # Scene plan (highest priority — this is what the writer needs to execute)
    ctx.scene_plan = _truncate(scene_plan, budget.scene_plan)

    # Active characters (second priority)
    if active_character_names:
        ctx.characters_excerpt = extract_active_characters(
            characters, active_character_names, budget.characters,
        )
    else:
        ctx.characters_excerpt = _truncate(characters, budget.characters)

    # World codex (smart extraction)
    ctx.codex_excerpt = extract_relevant_codex(
        codex, scene_plan, location_hint, budget.codex,
    )

    # Previous chapter summary (rolling context)
    ctx.previous_summary = build_rolling_context(
        chapter_summaries or {}, current_chapter, budget.previous_summary,
    )

    # Lessons learned
    ctx.lessons_overlay = _truncate(lessons_overlay, budget.lessons)

    # Genre overlay
    ctx.genre_overlay = _truncate(genre_overlay, budget.genre_overlay)

    # Calculate total
    ctx.total_estimated_tokens = sum(
        _est_tokens(v) for v in [
            ctx.codex_excerpt, ctx.characters_excerpt, ctx.scene_plan,
            ctx.previous_summary, ctx.lessons_overlay, ctx.genre_overlay,
        ]
    )

    logger.info(
        "Context assembled: ~%d tokens (codex=%d, chars=%d, plan=%d, prev=%d, lessons=%d)",
        ctx.total_estimated_tokens,
        _est_tokens(ctx.codex_excerpt),
        _est_tokens(ctx.characters_excerpt),
        _est_tokens(ctx.scene_plan),
        _est_tokens(ctx.previous_summary),
        _est_tokens(ctx.lessons_overlay),
    )

    return ctx
