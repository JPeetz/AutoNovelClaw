"""Content quality assessment for AutoNovelClaw.

Detects AI-typical phrasing, placeholder content, clichés, sensory gaps,
and other quality issues in generated text.  Provides quantitative metrics
for pipeline quality gates.

Usage
-----
::

    from autonovelclaw.quality import assess_chapter_quality
    report = assess_chapter_quality(chapter_text)
    print(f"Score: {report.overall_score}/100")
    for issue in report.issues:
        print(f"  [{issue.severity}] {issue.description}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI cliché / forbidden phrase patterns
# ---------------------------------------------------------------------------

AI_CLICHE_PATTERNS: list[tuple[str, str]] = [
    # (regex pattern, description)
    (r"\bit(?:'s| is) worth noting\b", "AI phrasing: 'it's worth noting'"),
    (r"\bmoreover\b", "AI phrasing: 'moreover'"),
    (r"\bfurthermore\b", "AI phrasing: 'furthermore'"),
    (r"\bin conclusion\b", "AI phrasing: 'in conclusion'"),
    (r"\bneedless to say\b", "AI phrasing: 'needless to say'"),
    (r"\bit is important to note\b", "AI phrasing: 'it is important to note'"),
    (r"\ba tapestry of\b", "AI cliché: 'a tapestry of'"),
    (r"\ba symphony of\b", "AI cliché: 'a symphony of'"),
    (r"\ba dance of\b", "AI cliché: 'a dance of'"),
    (r"\ba kaleidoscope of\b", "AI cliché: 'a kaleidoscope of'"),
    (r"\ba mosaic of\b", "AI cliché: 'a mosaic of' (overused)"),
    (r"\bpalpable tension\b", "Forbidden phrase: 'palpable tension'"),
    (r"\bpalpable\b.*\b(?:fear|dread|excitement|energy|silence)\b",
     "Forbidden: 'palpable' + emotion"),
    (r"\bpainting the sky\b", "Cliché: 'painting the sky'"),
    (r"\bsent (?:a )?shivers? down (?:his|her|their) spine\b",
     "Cliché: 'shivers down spine'"),
    (r"\btime stood still\b", "Cliché: 'time stood still'"),
    (r"\blike a ton of bricks\b", "Cliché: 'like a ton of bricks'"),
    (r"\bevery fiber of (?:his|her|their) being\b",
     "Cliché: 'every fiber of their being'"),
    (r"\bleft (?:him|her|them) breathless\b", "Cliché: 'left breathless'"),
    (r"\ba (?:sense|wave|surge) of (?:relief|dread|foreboding)\b",
     "Overused: 'a [sense/wave/surge] of [emotion]'"),
    (r"\bwith (?:bated|baited) breath\b", "Cliché: 'with bated breath'"),
    (r"\bthe silence was deafening\b", "Cliché: 'the silence was deafening'"),
    (r"\beyes (?:like|as) (?:pools|orbs|windows)\b",
     "Cliché: eyes compared to pools/orbs/windows"),
    (r"\bheart (?:pounded|hammered|raced) in (?:his|her|their) chest\b",
     "Overused: explicit heart-pounding (consider varied physical fear responses)"),
    (r"\bunbeknownst to\b", "Archaic/AI phrasing: 'unbeknownst to'"),
    (r"\bdelve\b", "AI-typical: 'delve' (overused by LLMs)"),
    (r"\bmeticulous(?:ly)?\b", "AI-typical: 'meticulous(ly)' (overused by LLMs)"),
    (r"\btestament to\b", "AI-typical: 'testament to' (overused by LLMs)"),
]

# ---------------------------------------------------------------------------
# Placeholder / template detection
# ---------------------------------------------------------------------------

PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    (r"\[INSERT\s+.*?\]", "Insert placeholder"),
    (r"\[TODO\s*:?\s*.*?\]", "TODO placeholder"),
    (r"\[PLACEHOLDER\s*:?\s*.*?\]", "Explicit placeholder"),
    (r"\[CHARACTER\s*NAME\]", "Character name placeholder"),
    (r"\[LOCATION\]", "Location placeholder"),
    (r"\[DESCRIPTION\]", "Description placeholder"),
    (r"(?i)lorem\s+ipsum", "Lorem ipsum filler"),
    (r"(?i)this\s+section\s+will\s+(describe|discuss|present|outline)",
     "Future-tense placeholder"),
    (r"(?i)add\s+(?:your|the)\s+(?:content|text|description)\s+here",
     "Content placeholder"),
    (r"(?i)replace\s+this\s+(?:text|content|section)", "Replace placeholder"),
    (r"(?i)TBD\b", "TBD marker"),
    (r"(?i)XXX\b", "XXX marker"),
    (r"(?i)FIXME\b", "FIXME marker"),
]

# ---------------------------------------------------------------------------
# Generic descriptor patterns (should be replaced with specific language)
# ---------------------------------------------------------------------------

GENERIC_DESCRIPTORS: list[tuple[str, str]] = [
    (r"\b(?:very|really|extremely) (?:beautiful|amazing|incredible|wonderful)\b",
     "Generic intensifier + adjective"),
    (r"\bit was (?:beautiful|amazing|incredible|wonderful|terrible|horrible)\b",
     "'It was [generic adjective]' — show, don't tell"),
    (r"\b(?:he|she|they) (?:was|were) (?:happy|sad|angry|afraid|scared)\b",
     "Told emotion instead of shown — use physical/sensory manifestation"),
    (r"\b(?:he|she|they) felt (?:happy|sad|angry|afraid|scared|nervous|anxious)\b",
     "'Felt [emotion]' — show through body language and physical response"),
]


# ---------------------------------------------------------------------------
# Sensory analysis
# ---------------------------------------------------------------------------

SENSORY_KEYWORDS: dict[str, list[str]] = {
    "visual": [
        "light", "shadow", "colour", "color", "bright", "dark", "gleam",
        "glow", "shimmer", "flicker", "pale", "crimson", "gold", "silver",
        "silhouette", "horizon", "haze", "mist", "smoke", "dust",
        "reflected", "illumin", "visible", "watched", "gaze", "stared",
        "glint", "flash", "beam", "ray", "dim", "vivid",
    ],
    "kinesthetic": [
        "texture", "rough", "smooth", "cold", "warm", "hot", "damp",
        "weight", "pressure", "trembl", "shiver", "sting", "burn",
        "grip", "clench", "pulse", "throb", "ache", "numb", "tingle",
        "humid", "sweat", "chill", "breeze", "gust", "impact", "jolt",
    ],
    "olfactory": [
        "smell", "scent", "odour", "odor", "stench", "fragr", "aroma",
        "reek", "whiff", "musk", "acrid", "pungent", "metallic",
        "copper", "ozone", "salt air", "smoke", "diesel", "damp",
        "rot", "decay", "perfume", "incense", "cooking", "blood",
    ],
    "auditory": [
        "sound", "silence", "echo", "whisper", "shout", "scream",
        "creak", "crack", "rumble", "thunder", "hiss", "buzz",
        "hum", "ring", "click", "clang", "splash", "drip",
        "footstep", "breath", "heartbeat", "rhythm", "murmur",
    ],
    "gustatory": [
        "taste", "bitter", "sweet", "sour", "salty", "metallic",
        "copper", "blood", "bile", "acid", "tongue", "mouth",
        "swallow", "sip", "gulp", "flavour", "flavor",
    ],
}


def _count_sensory(text: str) -> dict[str, int]:
    """Count sensory keyword occurrences per category."""
    text_lower = text.lower()
    counts: dict[str, int] = {}
    for sense, keywords in SENSORY_KEYWORDS.items():
        counts[sense] = sum(1 for kw in keywords if kw in text_lower)
    return counts


def _sensory_distribution(counts: dict[str, int]) -> dict[str, float]:
    """Convert raw counts to proportional distribution."""
    total = sum(counts.values())
    if total == 0:
        return {s: 0.0 for s in counts}
    return {s: c / total for s, c in counts.items()}


# ---------------------------------------------------------------------------
# Quality issue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QualityIssue:
    """A single quality issue found in the text."""
    category: str       # "ai_cliche", "placeholder", "generic", "sensory", "structure"
    severity: str       # "error", "warning", "info"
    description: str
    line_number: int = 0
    excerpt: str = ""


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    """Quality assessment for a chapter or manuscript section."""

    total_words: int = 0
    total_lines: int = 0
    total_paragraphs: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    sensory_counts: dict[str, int] = field(default_factory=dict)
    sensory_distribution: dict[str, float] = field(default_factory=dict)
    dialogue_ratio: float = 0.0
    avg_sentence_length: float = 0.0
    sentence_length_variance: float = 0.0
    overall_score: int = 100   # starts at 100, deductions per issue

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_markdown(self) -> str:
        lines = [
            f"# Quality Report",
            f"",
            f"**Score: {self.overall_score}/100**",
            f"Words: {self.total_words:,} | Paragraphs: {self.total_paragraphs} | "
            f"Errors: {self.error_count} | Warnings: {self.warning_count}",
            f"",
            f"## Sensory Distribution",
        ]
        for sense, pct in sorted(self.sensory_distribution.items(),
                                  key=lambda x: x[1], reverse=True):
            bar = "█" * int(pct * 40)
            lines.append(f"  {sense:15s} {bar} {pct:.0%}")

        lines.append(f"\n## Prose Metrics")
        lines.append(f"  Dialogue ratio: {self.dialogue_ratio:.0%}")
        lines.append(f"  Avg sentence length: {self.avg_sentence_length:.1f} words")
        lines.append(f"  Sentence variance: {self.sentence_length_variance:.1f}")

        if self.issues:
            lines.append(f"\n## Issues ({len(self.issues)})")
            for iss in self.issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(iss.severity, "•")
                loc = f" (line {iss.line_number})" if iss.line_number else ""
                lines.append(f"  {icon} [{iss.category}]{loc} {iss.description}")
                if iss.excerpt:
                    lines.append(f"     → \"{iss.excerpt[:80]}\"")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assessment functions
# ---------------------------------------------------------------------------

def assess_chapter_quality(
    text: str,
    *,
    sensory_targets: dict[str, float] | None = None,
    min_words: int = 3000,
    max_words: int = 12000,
) -> QualityReport:
    """Run a comprehensive quality assessment on chapter text.

    Parameters
    ----------
    text : str
        The chapter text to assess.
    sensory_targets : dict, optional
        Target sensory distribution (e.g., {"visual": 0.40, ...}).
    min_words : int
        Minimum expected word count.
    max_words : int
        Maximum expected word count.

    Returns
    -------
    QualityReport
        Detailed quality report with issues and metrics.
    """
    if sensory_targets is None:
        sensory_targets = {
            "visual": 0.40, "kinesthetic": 0.25, "olfactory": 0.20,
            "auditory": 0.10, "gustatory": 0.05,
        }

    lines = text.split("\n")
    words = text.split()
    paragraphs = [p for p in text.split("\n\n") if p.strip()]

    report = QualityReport(
        total_words=len(words),
        total_lines=len(lines),
        total_paragraphs=len(paragraphs),
    )

    # --- Word count check ---
    if report.total_words < min_words:
        report.issues.append(QualityIssue(
            "structure", "error",
            f"Word count {report.total_words:,} below minimum {min_words:,}",
        ))
        report.overall_score -= 15
    elif report.total_words > max_words:
        report.issues.append(QualityIssue(
            "structure", "warning",
            f"Word count {report.total_words:,} above maximum {max_words:,}",
        ))
        report.overall_score -= 5

    # --- AI cliché detection ---
    for pattern, description in AI_CLICHE_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                report.issues.append(QualityIssue(
                    "ai_cliche", "warning", description,
                    line_number=i,
                    excerpt=line.strip()[:100],
                ))
                report.overall_score -= 2

    # --- Placeholder detection ---
    for pattern, description in PLACEHOLDER_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                report.issues.append(QualityIssue(
                    "placeholder", "error", description,
                    line_number=i,
                    excerpt=line.strip()[:100],
                ))
                report.overall_score -= 10

    # --- Generic descriptor detection ---
    for pattern, description in GENERIC_DESCRIPTORS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                report.issues.append(QualityIssue(
                    "generic", "warning", description,
                    line_number=i,
                    excerpt=line.strip()[:100],
                ))
                report.overall_score -= 1

    # --- Sensory analysis ---
    report.sensory_counts = _count_sensory(text)
    report.sensory_distribution = _sensory_distribution(report.sensory_counts)

    # Check against targets
    for sense, target in sensory_targets.items():
        actual = report.sensory_distribution.get(sense, 0.0)
        if actual < target * 0.5:  # Less than half the target
            report.issues.append(QualityIssue(
                "sensory", "warning",
                f"Low {sense} content: {actual:.0%} (target: {target:.0%})",
            ))
            report.overall_score -= 3

    # --- Dialogue ratio ---
    dialogue_lines = sum(1 for line in lines if '"' in line or '"' in line or '"' in line)
    report.dialogue_ratio = dialogue_lines / max(len(lines), 1)

    if report.dialogue_ratio < 0.10:
        report.issues.append(QualityIssue(
            "structure", "warning",
            f"Low dialogue ratio: {report.dialogue_ratio:.0%} (target: 25-30%)",
        ))
        report.overall_score -= 3
    elif report.dialogue_ratio > 0.50:
        report.issues.append(QualityIssue(
            "structure", "warning",
            f"High dialogue ratio: {report.dialogue_ratio:.0%} — may need more narration",
        ))
        report.overall_score -= 2

    # --- Sentence length analysis ---
    sentences = re.split(r'[.!?]+', text)
    sentence_lengths = [len(s.split()) for s in sentences if s.strip()]
    if sentence_lengths:
        report.avg_sentence_length = sum(sentence_lengths) / len(sentence_lengths)
        mean = report.avg_sentence_length
        report.sentence_length_variance = (
            sum((l - mean) ** 2 for l in sentence_lengths) / len(sentence_lengths)
        ) ** 0.5

        # Low variance = monotonous rhythm
        if report.sentence_length_variance < 4.0 and len(sentence_lengths) > 20:
            report.issues.append(QualityIssue(
                "structure", "warning",
                f"Low sentence length variance ({report.sentence_length_variance:.1f}) — "
                f"rhythm may feel monotonous",
            ))
            report.overall_score -= 3

    # --- Repeated words in proximity ---
    _check_word_repetition(text, report, proximity=50)

    # Clamp score
    report.overall_score = max(0, min(100, report.overall_score))
    return report


def _check_word_repetition(
    text: str,
    report: QualityReport,
    proximity: int = 50,
) -> None:
    """Check for repeated distinctive words within N-word proximity."""
    # Only check words 6+ characters (skip common short words)
    words = text.lower().split()
    skip_words = {
        "through", "before", "around", "between", "without", "behind",
        "against", "during", "another", "because", "though", "should",
        "beneath", "nothing", "something", "everything", "himself",
        "herself", "itself", "already", "always", "chapter",
    }

    for i, word in enumerate(words):
        clean = re.sub(r"[^a-z]", "", word)
        if len(clean) < 6 or clean in skip_words:
            continue
        # Check ahead within proximity window
        window = words[i + 1:i + proximity]
        count = sum(1 for w in window if re.sub(r"[^a-z]", "", w) == clean)
        if count >= 3:
            report.issues.append(QualityIssue(
                "repetition", "info",
                f"Word '{clean}' appears {count + 1} times within {proximity} words",
            ))
            report.overall_score -= 1
            break  # Only flag once per word to avoid spam
