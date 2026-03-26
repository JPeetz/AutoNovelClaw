"""Review parser — robust extraction of ratings, strengths, weaknesses, suggestions.

Reviews come as free-form text from LLMs. This module reliably extracts
structured data from them: numeric ratings, categorised feedback sections,
and actionable suggestions — with fallback strategies when the LLM doesn't
follow the requested format exactly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ReviewItem:
    """A single piece of feedback (strength, weakness, or suggestion)."""
    text: str
    category: str = ""     # "prose", "character", "pacing", "sensory", etc.
    severity: str = ""     # for weaknesses: "minor", "moderate", "major"
    location: str = ""     # where in the chapter (if specified)


@dataclass
class ParsedReview:
    """Structured data extracted from a reviewer's free-form text."""
    raw_text: str
    rating: float = 0.0
    rating_source: str = ""    # which pattern matched
    strengths: list[ReviewItem] = field(default_factory=list)
    weaknesses: list[ReviewItem] = field(default_factory=list)
    suggestions: list[ReviewItem] = field(default_factory=list)
    improvement_path: str = ""  # "with these changes → X.X/10"
    engagement_moments: list[str] = field(default_factory=list)  # for Reader reviews
    drag_points: list[str] = field(default_factory=list)         # for Reader reviews
    confusion_points: list[str] = field(default_factory=list)    # for Reader reviews
    memorability: str = ""
    character_investment: str = ""
    parse_confidence: float = 1.0  # 0-1, how confident we are in the parse

    @property
    def is_positive(self) -> bool:
        return self.rating >= 8.0

    @property
    def needs_work(self) -> bool:
        return self.rating < 7.5


# ---------------------------------------------------------------------------
# Rating extraction — multiple strategies
# ---------------------------------------------------------------------------

_RATING_PATTERNS: list[tuple[str, str]] = [
    # Most specific patterns first
    (r"OVERALL\s*RATING\s*:\s*(\d+\.?\d*)\s*/\s*10", "overall_rating"),
    (r"ENGAGEMENT\s*RATING\s*:\s*(\d+\.?\d*)\s*/\s*10", "engagement_rating"),
    (r"Rating\s*:\s*(\d+\.?\d*)\s*/\s*10", "rating_colon"),
    (r"(\d+\.?\d*)\s*/\s*10", "bare_slash"),
    (r"(\d+\.?\d*)\s*out\s*of\s*10", "out_of_10"),
    (r"score\s*(?:of\s*)?(\d+\.?\d*)", "score_of"),
]


def extract_rating(text: str, default: float = 7.0) -> tuple[float, str]:
    """Extract a numeric rating from review text.

    Tries multiple patterns in order of specificity. Returns (rating, pattern_name).
    """
    for pattern, name in _RATING_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if 0 <= val <= 10:
                    return val, name
            except (ValueError, IndexError):
                continue

    logger.warning("Could not extract rating — using default %.1f", default)
    return default, "default"


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def _extract_section(text: str, headers: list[str]) -> str:
    """Extract a section by its header (tries multiple header formats).

    Handles indented text, various markdown header levels, and numbered sections.
    """
    import textwrap
    # Dedent to handle triple-quoted string indentation
    clean = textwrap.dedent(text).strip()

    for header in headers:
        h_escaped = re.escape(header)
        patterns = [
            # ## HEADER followed by content until next ## or end
            rf"^#{{1,4}}\s*{h_escaped}\s*\n(.*?)(?=^#{{1,4}}\s|\Z)",
            # HEADER: or **HEADER** followed by content until next uppercase header
            rf"^(?:\*\*)?(?:\d+\.\s*)?{h_escaped}(?:\*\*)?\s*:\s*\n?(.*?)(?=^(?:\*\*)?(?:\d+\.\s*)?[A-Z]{{2,}}|\Z)",
        ]
        for pat in patterns:
            match = re.search(pat, clean, re.DOTALL | re.MULTILINE | re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                if result:
                    return result
    return ""


def _extract_list_items(section_text: str) -> list[str]:
    """Extract list items from a section (bullet points, numbered, or plain lines)."""
    items: list[str] = []
    for line in section_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Remove list markers
        cleaned = re.sub(r"^(?:\d+\.\s*|[-*•]\s*|\*\*\d+\.\*\*\s*)", "", line).strip()
        if cleaned and len(cleaned) > 10:
            items.append(cleaned)
    return items


def _categorise_feedback(text: str) -> str:
    """Infer a category for a feedback item based on its content."""
    text_lower = text.lower()
    categories = {
        "prose": ["prose", "language", "word choice", "imagery", "sensory", "description",
                  "sentence", "rhythm", "cliché", "cliche", "purple", "overwritten"],
        "character": ["character", "dialogue", "voice", "motivation", "believable",
                     "flat", "depth", "personality", "arc"],
        "pacing": ["pace", "pacing", "slow", "drag", "rushed", "tension", "momentum",
                  "boring", "engaging", "hook"],
        "structure": ["structure", "scene", "chapter", "opening", "closing", "transition",
                     "break", "format"],
        "continuity": ["consistent", "continuity", "contradict", "timeline", "name"],
        "sensory": ["sense", "sensory", "smell", "sound", "texture", "visual",
                   "olfactory", "kinesthetic", "auditory", "gustatory"],
    }

    best_cat = ""
    best_score = 0
    for cat, keywords in categories.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat or "general"


# ---------------------------------------------------------------------------
# Full review parser
# ---------------------------------------------------------------------------

def parse_critic_review(text: str) -> ParsedReview:
    """Parse a Literary Critic (Reviewer #1) review.

    Expected structure:
    1. OVERALL RATING: X.X/10
    2. WHAT WORKS (3-5 items)
    3. WHAT DOESN'T WORK (3-5 items)
    4. SPECIFIC SUGGESTIONS (3-5 items)
    5. PATH TO IMPROVEMENT
    """
    review = ParsedReview(raw_text=text)
    review.rating, review.rating_source = extract_rating(text)

    # Strengths
    strengths_text = _extract_section(text, [
        "WHAT WORKS", "What Works", "STRENGTHS", "Strengths",
        "STRONGEST ELEMENTS", "What works well",
    ])
    if strengths_text:
        for item in _extract_list_items(strengths_text):
            review.strengths.append(ReviewItem(
                text=item,
                category=_categorise_feedback(item),
            ))

    # Weaknesses
    weaknesses_text = _extract_section(text, [
        "WHAT DOESN'T WORK", "What Doesn't Work", "WEAKNESSES",
        "Weaknesses", "WEAKEST ELEMENTS", "Areas for Improvement",
        "WHAT DOESN.T WORK",
    ])
    if weaknesses_text:
        for item in _extract_list_items(weaknesses_text):
            review.weaknesses.append(ReviewItem(
                text=item,
                category=_categorise_feedback(item),
            ))

    # Suggestions
    suggestions_text = _extract_section(text, [
        "SPECIFIC SUGGESTIONS", "Specific Suggestions", "SUGGESTIONS",
        "Suggestions", "RECOMMENDATIONS", "Recommendations",
        "ACTIONABLE CHANGES",
    ])
    if suggestions_text:
        for item in _extract_list_items(suggestions_text):
            review.suggestions.append(ReviewItem(
                text=item,
                category=_categorise_feedback(item),
            ))

    # Improvement path
    path_text = _extract_section(text, [
        "PATH TO IMPROVEMENT", "Path to Improvement",
        "POTENTIAL RATING", "With these changes",
    ])
    if path_text:
        review.improvement_path = path_text.strip()

    # Confidence based on how much we successfully extracted
    extracted = len(review.strengths) + len(review.weaknesses) + len(review.suggestions)
    review.parse_confidence = min(1.0, extracted / 6.0)

    if review.parse_confidence < 0.3:
        logger.warning("Low parse confidence (%.2f) — reviewer may not have followed format",
                       review.parse_confidence)

    return review


def parse_reader_review(text: str) -> ParsedReview:
    """Parse a Beta Reader (Reviewer #2) review.

    Expected structure:
    1. ENGAGEMENT RATING: X.X/10
    2. PAGE-TURNER MOMENTS
    3. DRAG POINTS
    4. CONFUSION POINTS
    5. EMOTIONAL PEAKS
    6. CHARACTER INVESTMENT
    7. MEMORABILITY
    8. SUGGESTIONS
    """
    review = ParsedReview(raw_text=text)
    review.rating, review.rating_source = extract_rating(text)

    # Page-turner moments → strengths
    page_turners = _extract_section(text, [
        "PAGE-TURNER MOMENTS", "Page-Turner Moments",
        "PAGE TURNER", "Exciting Parts",
    ])
    if page_turners:
        for item in _extract_list_items(page_turners):
            review.strengths.append(ReviewItem(text=item, category="engagement"))
            review.engagement_moments.append(item)

    # Drag points → weaknesses
    drags = _extract_section(text, [
        "DRAG POINTS", "Drag Points", "BORING PARTS",
        "Where I Lost Interest", "SLOW PARTS",
    ])
    if drags:
        for item in _extract_list_items(drags):
            review.weaknesses.append(ReviewItem(text=item, category="pacing"))
            review.drag_points.append(item)

    # Confusion points → weaknesses
    confusion = _extract_section(text, [
        "CONFUSION POINTS", "Confusion Points",
        "WHERE I GOT LOST", "Confusing Parts",
    ])
    if confusion:
        for item in _extract_list_items(confusion):
            review.weaknesses.append(ReviewItem(text=item, category="clarity"))
            review.confusion_points.append(item)

    # Emotional peaks → strengths
    emotional = _extract_section(text, [
        "EMOTIONAL PEAKS", "Emotional Peaks",
        "EMOTIONAL MOMENTS", "Where I Felt Something",
    ])
    if emotional:
        for item in _extract_list_items(emotional):
            review.strengths.append(ReviewItem(text=item, category="emotional"))

    # Character investment
    char_invest = _extract_section(text, [
        "CHARACTER INVESTMENT", "Character Investment",
        "DO I CARE", "Characters",
    ])
    review.character_investment = char_invest.strip() if char_invest else ""

    # Memorability
    memo = _extract_section(text, [
        "MEMORABILITY", "Memorability",
        "WHAT I'LL REMEMBER", "Memorable Moments",
    ])
    review.memorability = memo.strip() if memo else ""

    # Suggestions
    suggestions_text = _extract_section(text, [
        "SUGGESTIONS", "Suggestions", "RECOMMENDATIONS",
        "What Would Make It Better",
    ])
    if suggestions_text:
        for item in _extract_list_items(suggestions_text):
            review.suggestions.append(ReviewItem(
                text=item,
                category=_categorise_feedback(item),
            ))

    # Confidence
    extracted = (len(review.strengths) + len(review.weaknesses)
                 + len(review.suggestions) + (1 if review.memorability else 0))
    review.parse_confidence = min(1.0, extracted / 5.0)

    return review


def combine_reviews(
    critic: ParsedReview,
    reader: ParsedReview,
    critic_weight: float = 0.6,
    reader_weight: float = 0.4,
) -> dict[str, object]:
    """Combine two parsed reviews into a unified assessment.

    Returns a dict with composite rating, merged feedback, and priorities.
    """
    composite = (critic.rating * critic_weight) + (reader.rating * reader_weight)

    # Merge and deduplicate weaknesses
    all_weaknesses = critic.weaknesses + reader.weaknesses

    # Prioritise by frequency (if both reviewers flag something, it's higher priority)
    weakness_categories: dict[str, int] = {}
    for w in all_weaknesses:
        weakness_categories[w.category] = weakness_categories.get(w.category, 0) + 1

    # Sort suggestions by category priority
    priority_suggestions = sorted(
        critic.suggestions + reader.suggestions,
        key=lambda s: -weakness_categories.get(s.category, 0),
    )

    return {
        "composite_rating": round(composite, 1),
        "critic_rating": critic.rating,
        "reader_rating": reader.rating,
        "total_strengths": len(critic.strengths) + len(reader.strengths),
        "total_weaknesses": len(all_weaknesses),
        "total_suggestions": len(priority_suggestions),
        "priority_categories": sorted(
            weakness_categories.items(), key=lambda x: -x[1],
        ),
        "top_suggestions": priority_suggestions[:5],
        "drag_points": reader.drag_points,
        "confusion_points": reader.confusion_points,
        "memorable_elements": reader.memorability,
    }
