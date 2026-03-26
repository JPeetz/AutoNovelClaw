"""Chapter structure validator — verifies structural requirements.

Checks that chapters meet the structural standards:
- Opening hook (sensory grounding in first 2 paragraphs)
- Scene breaks properly formatted
- Closing hook present
- Word count within targets
- Dialogue ratio within range
- No orphaned dialogue (opening quote without closing)
- Action/emotional beat frequency
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StructureIssue:
    """A structural problem found in the chapter."""
    issue_type: str
    severity: str       # "error", "warning", "info"
    description: str
    location: str = ""  # "opening", "middle", "closing", "paragraph N"
    suggestion: str = ""


@dataclass
class StructureReport:
    """Chapter structure validation report."""
    word_count: int = 0
    paragraph_count: int = 0
    scene_count: int = 0
    dialogue_ratio: float = 0.0
    has_opening_hook: bool = False
    has_sensory_opening: bool = False
    has_closing_hook: bool = False
    has_scene_breaks: bool = False
    issues: list[StructureIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    def to_markdown(self) -> str:
        status = "✅ VALID" if self.is_valid else "❌ ISSUES FOUND"
        lines = [
            f"# Chapter Structure Report — {status}\n",
            f"- Words: {self.word_count:,}",
            f"- Paragraphs: {self.paragraph_count}",
            f"- Scenes: {self.scene_count}",
            f"- Dialogue ratio: {self.dialogue_ratio:.0%}",
            f"- Opening hook: {'✅' if self.has_opening_hook else '❌'}",
            f"- Sensory opening: {'✅' if self.has_sensory_opening else '❌'}",
            f"- Closing hook: {'✅' if self.has_closing_hook else '❌'}",
            f"- Scene breaks: {'✅' if self.has_scene_breaks or self.scene_count <= 1 else '⚠️'}",
        ]

        if self.issues:
            lines.append(f"\n## Issues ({len(self.issues)})\n")
            for iss in self.issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(iss.severity, "•")
                loc = f" [{iss.location}]" if iss.location else ""
                lines.append(f"- {icon}{loc} {iss.description}")
                if iss.suggestion:
                    lines.append(f"  → {iss.suggestion}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sensory keyword check for opening paragraphs
# ---------------------------------------------------------------------------

_OPENING_SENSORY_WORDS = re.compile(
    r"\b(?:light|shadow|smell|scent|sound|silence|cold|warm|wind|air|"
    r"texture|rough|smooth|damp|humid|dust|mist|rain|sun|moon|"
    r"stone|wood|metal|leather|cloth|earth|water|fire|"
    r"heard|felt|tasted|breathed|touched|watched|listened)\b",
    re.IGNORECASE,
)


def validate_chapter_structure(
    text: str,
    *,
    min_words: int = 5000,
    max_words: int = 9000,
    min_dialogue_ratio: float = 0.10,
    max_dialogue_ratio: float = 0.50,
    expected_scenes: int = 3,
) -> StructureReport:
    """Validate the structural requirements of a chapter.

    Parameters
    ----------
    text : str
        The chapter text.
    min_words, max_words : int
        Word count range.
    min_dialogue_ratio, max_dialogue_ratio : float
        Acceptable dialogue ratio range.
    expected_scenes : int
        Expected number of scenes (approximate).
    """
    report = StructureReport()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    words = text.split()

    report.word_count = len(words)
    report.paragraph_count = len(paragraphs)

    # --- Word count check ---
    if report.word_count < min_words:
        report.issues.append(StructureIssue(
            "word_count", "error",
            f"Word count {report.word_count:,} below minimum {min_words:,}",
            suggestion=f"Chapter needs at least {min_words - report.word_count:,} more words",
        ))
    elif report.word_count > max_words:
        report.issues.append(StructureIssue(
            "word_count", "warning",
            f"Word count {report.word_count:,} above maximum {max_words:,}",
            suggestion="Consider splitting into scenes or tightening prose",
        ))

    # --- Opening hook ---
    if paragraphs:
        first_para = paragraphs[0]
        # A good opening should be at least 30 words and not start with "Chapter"
        if len(first_para.split()) >= 20 and not first_para.strip().startswith(("#", "Chapter")):
            report.has_opening_hook = True
        elif len(paragraphs) > 1:
            # Check second paragraph if first is a heading
            second_para = paragraphs[1] if len(paragraphs) > 1 else ""
            if len(second_para.split()) >= 20:
                report.has_opening_hook = True

        if not report.has_opening_hook:
            report.issues.append(StructureIssue(
                "opening", "warning",
                "No clear opening hook — first paragraph is too short or is a heading",
                location="opening",
                suggestion="Start with a vivid sensory image or action",
            ))

        # Check for sensory content in first 2 paragraphs
        opening_text = " ".join(paragraphs[:2]) if len(paragraphs) >= 2 else paragraphs[0]
        sensory_matches = _OPENING_SENSORY_WORDS.findall(opening_text)
        report.has_sensory_opening = len(sensory_matches) >= 2

        if not report.has_sensory_opening:
            report.issues.append(StructureIssue(
                "sensory_opening", "warning",
                "Opening lacks sensory grounding (need 2+ sensory words in first 2 paragraphs)",
                location="opening",
                suggestion="Add sight, smell, sound, texture, or temperature to the opening",
            ))

    # --- Scene breaks ---
    scene_break_pattern = re.compile(r"^\s*(?:\*\s*\*\s*\*|---)\s*$", re.MULTILINE)
    scene_breaks = scene_break_pattern.findall(text)
    report.scene_count = len(scene_breaks) + 1
    report.has_scene_breaks = len(scene_breaks) > 0

    if report.scene_count < expected_scenes - 1 and report.word_count > min_words:
        report.issues.append(StructureIssue(
            "scene_breaks", "info",
            f"Only {report.scene_count} scene(s) detected (expected ~{expected_scenes})",
            suggestion="Consider adding scene breaks (* * *) between distinct scenes",
        ))

    # --- Closing hook ---
    if paragraphs:
        last_paras = paragraphs[-3:] if len(paragraphs) >= 3 else paragraphs
        last_text = " ".join(last_paras).lower()

        # A closing hook often contains questions, unresolved tension, or forward motion
        hook_indicators = [
            r"\?",  # Questions
            r"\b(?:but|however|yet|still|though)\b",  # Tension
            r"\b(?:tomorrow|next|soon|coming|ahead|waiting|would)\b",  # Forward
            r"\b(?:couldn't|wouldn't|shouldn't|mustn't|can't)\b",  # Restraint
            r"\.\.\.",  # Ellipsis
            r"—$",  # Em-dash at end
        ]

        hook_count = sum(1 for pat in hook_indicators if re.search(pat, last_text))
        report.has_closing_hook = hook_count >= 1

        if not report.has_closing_hook:
            report.issues.append(StructureIssue(
                "closing", "warning",
                "No clear closing hook — chapter ending may not compel turning the page",
                location="closing",
                suggestion="End with unresolved tension, a question, or a revelation",
            ))

    # --- Dialogue ratio ---
    dialogue_lines = 0
    total_lines = 0
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        total_lines += 1
        # Count lines with dialogue markers
        if any(c in line for c in '"""\u201C\u201D'):
            dialogue_lines += 1

    report.dialogue_ratio = dialogue_lines / max(total_lines, 1)

    if report.dialogue_ratio < min_dialogue_ratio:
        report.issues.append(StructureIssue(
            "dialogue", "info",
            f"Low dialogue ratio: {report.dialogue_ratio:.0%} (target: {min_dialogue_ratio:.0%}+)",
            suggestion="Add more character interaction and conversation",
        ))
    elif report.dialogue_ratio > max_dialogue_ratio:
        report.issues.append(StructureIssue(
            "dialogue", "warning",
            f"High dialogue ratio: {report.dialogue_ratio:.0%} (target: <{max_dialogue_ratio:.0%})",
            suggestion="Balance with more narration, description, and interiority",
        ))

    # --- Orphaned dialogue check ---
    open_quotes = len(re.findall(r'["\u201C]', text))
    close_quotes = len(re.findall(r'["\u201D]', text))
    if abs(open_quotes - close_quotes) > 2:
        report.issues.append(StructureIssue(
            "dialogue_formatting", "warning",
            f"Mismatched quotes: {open_quotes} opening vs {close_quotes} closing",
            suggestion="Check for unclosed dialogue",
        ))

    # --- Very long paragraphs (potential wall-of-text) ---
    for idx, para in enumerate(paragraphs):
        wc = len(para.split())
        if wc > 300:
            report.issues.append(StructureIssue(
                "paragraph_length", "info",
                f"Very long paragraph ({wc} words) at position {idx}",
                location=f"paragraph {idx}",
                suggestion="Consider breaking into smaller paragraphs for readability",
            ))

    return report
