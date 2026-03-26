"""Sensory auditor — analyses sensory distribution per paragraph.

Goes beyond the quality module's keyword counting by doing paragraph-level
analysis: which paragraphs have 2+ senses, which are sensory deserts,
and what the overall distribution looks like versus targets.

This is used by Stage 13 (Sensory Enhancement) to identify exactly WHERE
sensory content needs to be added, not just THAT it needs to be added.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Sensory keyword sets (more comprehensive than the quality module's)
_SENSE_PATTERNS: dict[str, list[str]] = {
    "visual": [
        r"\b(?:light|shadow|glow|shimmer|gleam|flash|beam|dark|bright|dim|"
        r"vivid|pale|crimson|gold|silver|scarlet|azure|emerald|violet|"
        r"silhouette|horizon|haze|mist|smoke|dust|colour|color|reflected|"
        r"illumin\w+|glint|flicker|visible|stared?|gazed?|watched|glanced?|"
        r"peered|squinted|glimpsed|spotted|noticed|loomed|towered|"
        r"sunset|sunrise|moonlight|starlight|candlelight|firelight)\b",
    ],
    "kinesthetic": [
        r"\b(?:texture|rough|smooth|cold|warm|hot|damp|moist|dry|"
        r"weight|heavy|light|pressure|trembl\w+|shiver\w+|sting|burn\w*|"
        r"grip|clench|pulse|throb|ache|numb|tingle|humid|sweat|"
        r"chill\w*|breeze|gust|impact|jolt|shudder|vibrat\w+|"
        r"calloused|scarred|weathered|gnarled|tender|sore|"
        r"goosebumps|gooseflesh|pins.and.needles|cramped?)\b",
    ],
    "olfactory": [
        r"\b(?:smell\w*|scent\w*|odou?r\w*|stench|fragran\w+|aroma\w*|"
        r"reek\w*|whiff|musk\w*|acrid|pungent|metallic.{0,10}(?:tang|smell)|"
        r"copper\w*.{0,10}(?:tang|taste|smell)|ozone|salt.?air|"
        r"perfume|incense|rot\w*|decay\w*|foul|noisome|"
        r"diesel|gasoline|avgas|kerosene|cordite|gunpowder|"
        r"cooking|baking|spice\w*|herb\w*|bread|meat|"
        r"sweat\w*.{0,10}(?:smell|stink|stench)|blood.{0,10}(?:smell|tang))\b",
    ],
    "auditory": [
        r"\b(?:sound\w*|silence|silent|echo\w*|whisper\w*|shout\w*|scream\w*|"
        r"creak\w*|crack\w*|rumbl\w+|thunder\w*|hiss\w*|buzz\w*|"
        r"hum\w*|ring\w*|click\w*|clang\w*|splash\w*|drip\w*|"
        r"footstep\w*|breath\w*|heartbeat|rhythm|murmur\w*|"
        r"roar\w*|groan\w*|grind\w*|scrape\w*|snap\w*|pop\w*|"
        r"boom\w*|clatter\w*|rustle\w*|thud\w*|crash\w*|"
        r"quiet|loud|deafen\w*|muffled|muted|piercing)\b",
    ],
    "gustatory": [
        r"\b(?:taste\w*|bitter\w*|sweet\w*|sour\w*|salty|metallic.{0,10}taste|"
        r"copper.{0,10}(?:taste|mouth|tongue)|blood.{0,10}(?:taste|mouth)|"
        r"bile|acid\w*.{0,10}(?:taste|tongue|throat)|"
        r"tongue|mouth|swallow\w*|sip\w*|gulp\w*|"
        r"flavou?r\w*|savor\w*|savour\w*|"
        r"dry.{0,10}(?:mouth|tongue|throat)|parched)\b",
    ],
}


@dataclass
class ParagraphSensory:
    """Sensory analysis for a single paragraph."""
    paragraph_index: int
    word_count: int
    senses_present: list[str]     # which senses are engaged
    sense_count: int              # how many distinct senses
    is_dialogue_heavy: bool       # >50% dialogue
    is_sensory_desert: bool       # 0 senses in a non-dialogue paragraph
    details: dict[str, int] = field(default_factory=dict)  # sense → match count


@dataclass
class SensoryAuditReport:
    """Full sensory audit of a chapter."""

    total_paragraphs: int = 0
    analysed_paragraphs: int = 0    # non-trivial (>10 words)
    paragraphs_with_2plus: int = 0
    sensory_deserts: int = 0        # paragraphs with 0 senses (excluding dialogue)
    sense_totals: dict[str, int] = field(default_factory=dict)
    sense_distribution: dict[str, float] = field(default_factory=dict)
    paragraph_details: list[ParagraphSensory] = field(default_factory=list)

    # Targets
    target_2plus_ratio: float = 0.65  # 65% of paragraphs with 2+ senses
    targets: dict[str, float] = field(default_factory=lambda: {
        "visual": 0.40, "kinesthetic": 0.25, "olfactory": 0.20,
        "auditory": 0.10, "gustatory": 0.05,
    })

    @property
    def actual_2plus_ratio(self) -> float:
        if self.analysed_paragraphs == 0:
            return 0.0
        return self.paragraphs_with_2plus / self.analysed_paragraphs

    @property
    def meets_targets(self) -> bool:
        """Check if all sensory targets are met (within 50% tolerance)."""
        for sense, target in self.targets.items():
            actual = self.sense_distribution.get(sense, 0.0)
            if actual < target * 0.5:
                return False
        return self.actual_2plus_ratio >= self.target_2plus_ratio * 0.8

    def gap_analysis(self) -> dict[str, float]:
        """Return the gap between actual and target for each sense."""
        gaps: dict[str, float] = {}
        for sense, target in self.targets.items():
            actual = self.sense_distribution.get(sense, 0.0)
            gaps[sense] = actual - target
        return gaps

    def weakest_paragraphs(self, n: int = 5) -> list[ParagraphSensory]:
        """Return the N paragraphs with the least sensory content."""
        non_dialogue = [p for p in self.paragraph_details
                        if not p.is_dialogue_heavy and p.word_count > 20]
        return sorted(non_dialogue, key=lambda p: p.sense_count)[:n]

    def to_markdown(self) -> str:
        lines = [
            "# Sensory Audit Report\n",
            f"**Paragraphs analysed:** {self.analysed_paragraphs}/{self.total_paragraphs}",
            f"**With 2+ senses:** {self.paragraphs_with_2plus} "
            f"({self.actual_2plus_ratio:.0%}, target: {self.target_2plus_ratio:.0%})",
            f"**Sensory deserts:** {self.sensory_deserts}\n",
            "## Distribution vs Targets\n",
        ]

        for sense in ["visual", "kinesthetic", "olfactory", "auditory", "gustatory"]:
            actual = self.sense_distribution.get(sense, 0.0)
            target = self.targets.get(sense, 0.0)
            bar = "█" * int(actual * 40)
            status = "✅" if actual >= target * 0.5 else "⚠️"
            lines.append(
                f"  {status} {sense:15s} {bar:20s} {actual:5.0%} (target: {target:.0%})"
            )

        gaps = self.gap_analysis()
        needs_boost = [(s, g) for s, g in gaps.items() if g < -0.05]
        if needs_boost:
            lines.append("\n## Needs Attention")
            for sense, gap in sorted(needs_boost, key=lambda x: x[1]):
                lines.append(f"  - **{sense}**: {gap:+.0%} below target")

        # Weakest paragraphs
        weak = self.weakest_paragraphs(3)
        if weak:
            lines.append("\n## Weakest Paragraphs (sensory deserts)")
            for p in weak:
                lines.append(
                    f"  - Paragraph {p.paragraph_index}: "
                    f"{p.word_count} words, {p.sense_count} senses"
                )

        return "\n".join(lines)


def audit_chapter_sensory(
    text: str,
    targets: dict[str, float] | None = None,
) -> SensoryAuditReport:
    """Run a full sensory audit on chapter text.

    Analyses each paragraph individually for sensory content, then
    computes overall distribution and identifies gaps.
    """
    if targets is None:
        targets = {
            "visual": 0.40, "kinesthetic": 0.25, "olfactory": 0.20,
            "auditory": 0.10, "gustatory": 0.05,
        }

    report = SensoryAuditReport(targets=targets)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    report.total_paragraphs = len(paragraphs)

    sense_totals: dict[str, int] = {s: 0 for s in _SENSE_PATTERNS}

    for idx, paragraph in enumerate(paragraphs):
        words = paragraph.split()
        wc = len(words)

        # Skip very short paragraphs (scene breaks, single lines)
        if wc < 10:
            continue

        report.analysed_paragraphs += 1

        # Check if dialogue-heavy
        quote_chars = sum(1 for c in paragraph if c in '""\u201C\u201D')
        is_dialogue = quote_chars > len(paragraph) * 0.02 and wc > 10

        # Count sensory matches per sense
        para_senses: dict[str, int] = {}
        senses_present: list[str] = []

        for sense, patterns in _SENSE_PATTERNS.items():
            count = 0
            for pat in patterns:
                count += len(re.findall(pat, paragraph, re.IGNORECASE))
            if count > 0:
                para_senses[sense] = count
                senses_present.append(sense)
                sense_totals[sense] += count

        sense_count = len(senses_present)
        is_desert = sense_count == 0 and not is_dialogue and wc > 20

        if sense_count >= 2:
            report.paragraphs_with_2plus += 1
        if is_desert:
            report.sensory_deserts += 1

        report.paragraph_details.append(ParagraphSensory(
            paragraph_index=idx,
            word_count=wc,
            senses_present=senses_present,
            sense_count=sense_count,
            is_dialogue_heavy=is_dialogue,
            is_sensory_desert=is_desert,
            details=para_senses,
        ))

    # Compute distribution
    report.sense_totals = sense_totals
    total_mentions = sum(sense_totals.values())
    if total_mentions > 0:
        report.sense_distribution = {
            s: c / total_mentions for s, c in sense_totals.items()
        }
    else:
        report.sense_distribution = {s: 0.0 for s in sense_totals}

    return report
