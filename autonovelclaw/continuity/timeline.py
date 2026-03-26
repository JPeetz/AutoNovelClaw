"""Timeline validator — ensures temporal consistency across chapters.

Tracks time-of-day, elapsed days, travel durations, and temporal references
to catch "it was morning, then two paragraphs later it was dusk without
any time passing" type errors.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time references
# ---------------------------------------------------------------------------

TIME_MARKERS: dict[str, float] = {
    # Approximate hour-of-day for common temporal references
    "dawn": 6.0, "sunrise": 6.5, "early morning": 7.0,
    "morning": 9.0, "mid-morning": 10.0, "midmorning": 10.0,
    "noon": 12.0, "midday": 12.0, "afternoon": 14.0,
    "late afternoon": 16.0, "evening": 18.0, "dusk": 19.0,
    "sunset": 19.5, "twilight": 20.0, "night": 22.0,
    "midnight": 0.0, "small hours": 3.0, "predawn": 5.0,
}

ELAPSED_PATTERNS: list[tuple[str, str]] = [
    (r"(\d+)\s+hours?\s+later", "hours"),
    (r"(\d+)\s+days?\s+later", "days"),
    (r"(\d+)\s+weeks?\s+later", "weeks"),
    (r"(\d+)\s+months?\s+later", "months"),
    (r"(?:two|2)\s+hours?\s+later", "two_hours"),
    (r"(?:three|3)\s+hours?\s+later", "three_hours_elapsed"),
    (r"(?:four|4)\s+hours?\s+later", "four_hours"),
    (r"(?:five|5)\s+hours?\s+later", "five_hours"),
    (r"(?:six|6)\s+hours?\s+later", "six_hours"),
    (r"(?:several|a\s+few)\s+hours?\s+later", "several_hours"),
    (r"(?:half\s+an?\s+hour|thirty\s+minutes)\s+later", "half_hour"),
    (r"next\s+morning", "next_morning"),
    (r"next\s+day", "next_day"),
    (r"the\s+following\s+(?:day|morning|evening|night)", "next_day"),
    (r"two\s+days\s+(?:later|after)", "two_days"),
    (r"three\s+days\s+(?:later|after)", "three_days"),
    (r"a\s+week\s+(?:later|after)", "one_week"),
]


@dataclass
class TimePoint:
    """A temporal reference found in the text."""
    chapter: int
    paragraph: int
    time_type: str      # "absolute" (morning/dusk) or "relative" (3 hours later)
    reference: str      # the original text matched
    approx_hour: float = -1.0   # 0-24, or -1 if relative
    elapsed_value: float = 0.0  # hours elapsed (for relative)
    context: str = ""


@dataclass
class TimelineIssue:
    """A temporal consistency problem."""
    issue_type: str     # "time_jump", "time_reversal", "impossible_travel", "ambiguous"
    severity: str
    description: str
    chapter: int = 0
    suggestion: str = ""


class TimelineValidator:
    """Validates temporal consistency across chapters.

    Tracks absolute time references (morning, dusk, midnight) and relative
    references (three hours later, next morning) to detect impossible
    sequences.
    """

    def __init__(self) -> None:
        self.timepoints: list[TimePoint] = []
        self.chapter_time_state: dict[int, float] = {}  # chapter → last known hour

    def process_chapter(self, chapter_num: int, text: str) -> list[TimelineIssue]:
        """Extract time references from a chapter and check consistency."""
        issues: list[TimelineIssue] = []
        paragraphs = text.split("\n\n")
        last_hour = self.chapter_time_state.get(chapter_num - 1, -1.0)

        for para_idx, paragraph in enumerate(paragraphs):
            para_lower = paragraph.lower()

            # Check absolute time markers
            for marker, hour in TIME_MARKERS.items():
                if marker in para_lower:
                    tp = TimePoint(
                        chapter=chapter_num,
                        paragraph=para_idx,
                        time_type="absolute",
                        reference=marker,
                        approx_hour=hour,
                        context=paragraph[:80],
                    )
                    self.timepoints.append(tp)

                    # Check for backwards time within same chapter
                    if last_hour >= 0 and hour < last_hour - 1.0:
                        # Time went backwards (e.g., from evening to morning)
                        # unless a scene break or "next day" intervened
                        if not self._has_scene_break_before(paragraphs, para_idx):
                            issues.append(TimelineIssue(
                                issue_type="time_reversal",
                                severity="warning",
                                description=(
                                    f"Time appears to go backwards: "
                                    f"~{last_hour:.0f}:00 → '{marker}' (~{hour:.0f}:00) "
                                    f"without a scene break or day transition"
                                ),
                                chapter=chapter_num,
                                suggestion="Add a scene break or 'next morning' transition",
                            ))
                    last_hour = hour

            # Check relative time markers
            for pattern, marker_type in ELAPSED_PATTERNS:
                match = re.search(pattern, para_lower)
                if match:
                    elapsed = self._parse_elapsed(match, marker_type)
                    tp = TimePoint(
                        chapter=chapter_num,
                        paragraph=para_idx,
                        time_type="relative",
                        reference=match.group(0),
                        elapsed_value=elapsed,
                        context=paragraph[:80],
                    )
                    self.timepoints.append(tp)

                    if last_hour >= 0:
                        last_hour = (last_hour + elapsed) % 24.0

        self.chapter_time_state[chapter_num] = last_hour
        return issues

    def check_cross_chapter(self) -> list[TimelineIssue]:
        """Check timeline consistency across all processed chapters."""
        issues: list[TimelineIssue] = []

        # Check that chapter transitions make temporal sense
        sorted_chapters = sorted(self.chapter_time_state.keys())
        for i in range(len(sorted_chapters) - 1):
            ch_a = sorted_chapters[i]
            ch_b = sorted_chapters[i + 1]
            time_a = self.chapter_time_state[ch_a]
            time_b_points = [tp for tp in self.timepoints
                            if tp.chapter == ch_b and tp.time_type == "absolute"]

            if time_a >= 0 and time_b_points:
                first_time_b = time_b_points[0].approx_hour
                # If chapter A ended late at night and chapter B starts in the morning,
                # that's fine (next day). But if A ended in the morning and B starts
                # in the morning without any time skip, flag it.
                if (abs(time_a - first_time_b) < 2.0
                        and not any(tp.time_type == "relative" and tp.elapsed_value > 2
                                    for tp in time_b_points)):
                    issues.append(TimelineIssue(
                        issue_type="ambiguous",
                        severity="info",
                        description=(
                            f"Chapters {ch_a}→{ch_b}: both at ~{time_a:.0f}:00 — "
                            f"clarify if time has passed between chapters"
                        ),
                        chapter=ch_b,
                        suggestion="Add a temporal anchor at chapter start",
                    ))

        return issues

    def _has_scene_break_before(self, paragraphs: list[str], para_idx: int) -> bool:
        """Check if there's a scene break (***) in the preceding paragraphs."""
        for i in range(max(0, para_idx - 3), para_idx):
            if paragraphs[i].strip() in ("* * *", "***", "---"):
                return True
        return False

    def _parse_elapsed(self, match: re.Match, marker_type: str) -> float:
        """Parse elapsed time in hours."""
        if marker_type == "hours":
            return float(match.group(1))
        elif marker_type == "days":
            return float(match.group(1)) * 24
        elif marker_type == "weeks":
            return float(match.group(1)) * 168
        elif marker_type == "months":
            return float(match.group(1)) * 720
        elif marker_type == "two_hours":
            return 2.0
        elif marker_type == "three_hours_elapsed":
            return 3.0
        elif marker_type == "four_hours":
            return 4.0
        elif marker_type == "five_hours":
            return 5.0
        elif marker_type == "six_hours":
            return 6.0
        elif marker_type == "several_hours":
            return 4.0  # approximate
        elif marker_type == "half_hour":
            return 0.5
        elif marker_type == "next_morning":
            return 12.0
        elif marker_type == "next_day":
            return 24.0
        elif marker_type == "two_days":
            return 48.0
        elif marker_type == "three_days":
            return 72.0
        elif marker_type == "one_week":
            return 168.0
        return 0.0

    def summary(self) -> str:
        """Generate a timeline summary."""
        lines = [f"# Timeline Summary — {len(self.timepoints)} time references\n"]
        by_chapter: dict[int, list[TimePoint]] = {}
        for tp in self.timepoints:
            by_chapter.setdefault(tp.chapter, []).append(tp)

        for ch, points in sorted(by_chapter.items()):
            lines.append(f"\n## Chapter {ch}")
            for tp in points:
                if tp.time_type == "absolute":
                    lines.append(f"  - [{tp.reference}] ~{tp.approx_hour:.0f}:00")
                else:
                    lines.append(f"  - [{tp.reference}] +{tp.elapsed_value:.0f}h")

        return "\n".join(lines)


# ============================================================================
# Foreshadowing tracker
# ============================================================================

@dataclass
class ForeshadowSeed:
    """A foreshadowing seed planted in the text."""
    seed_id: str
    description: str
    planted_chapter: int
    planted_context: str
    resolved: bool = False
    resolved_chapter: int = 0
    resolved_context: str = ""
    seed_type: str = "plot"  # "plot", "character", "world", "thematic"


@dataclass
class ForeshadowIssue:
    """A foreshadowing consistency problem."""
    issue_type: str  # "unresolved", "premature_resolution", "orphaned"
    severity: str
    description: str
    seed_id: str = ""
    suggestion: str = ""


class ForeshadowTracker:
    """Tracks foreshadowing seeds across the manuscript.

    Seeds are extracted from beat sheets and chapter text. The tracker
    verifies that planted seeds are eventually harvested and that no
    seeds are orphaned (mentioned once, never again).
    """

    def __init__(self) -> None:
        self.seeds: dict[str, ForeshadowSeed] = {}

    def register_seed(
        self,
        seed_id: str,
        description: str,
        planted_chapter: int,
        context: str = "",
        seed_type: str = "plot",
    ) -> None:
        """Register a foreshadowing seed."""
        self.seeds[seed_id] = ForeshadowSeed(
            seed_id=seed_id,
            description=description,
            planted_chapter=planted_chapter,
            planted_context=context,
            seed_type=seed_type,
        )

    def resolve_seed(self, seed_id: str, chapter: int, context: str = "") -> bool:
        """Mark a seed as resolved. Returns False if seed not found."""
        seed = self.seeds.get(seed_id)
        if seed is None:
            return False
        seed.resolved = True
        seed.resolved_chapter = chapter
        seed.resolved_context = context
        return True

    def extract_seeds_from_outline(self, outline_text: str) -> int:
        """Extract foreshadowing markers from the book outline.

        Looks for lines mentioning "foreshadow", "plant", "seed", "hint",
        "set up", "tease" in the outline.
        """
        count = 0
        lines = outline_text.split("\n")
        current_chapter = 0

        for line in lines:
            ch_match = re.search(r"Chapter\s+(\d+)", line, re.IGNORECASE)
            if ch_match:
                current_chapter = int(ch_match.group(1))

            line_lower = line.lower()
            if any(kw in line_lower for kw in [
                "foreshadow", "plant", "seed", "hint at", "set up",
                "tease", "foreshadow", "setup for",
            ]):
                seed_id = f"outline_seed_{count}"
                self.register_seed(
                    seed_id=seed_id,
                    description=line.strip()[:200],
                    planted_chapter=current_chapter,
                    context=line.strip(),
                    seed_type="plot",
                )
                count += 1

        return count

    def check_resolution(self, total_chapters: int) -> list[ForeshadowIssue]:
        """Check that all seeds are properly resolved by the end of the book."""
        issues: list[ForeshadowIssue] = []

        for seed in self.seeds.values():
            if not seed.resolved:
                # Unresolved seed — might be intended for a sequel
                severity = "warning" if seed.planted_chapter < total_chapters - 2 else "info"
                issues.append(ForeshadowIssue(
                    issue_type="unresolved",
                    severity=severity,
                    description=(
                        f"Foreshadowing seed '{seed.description[:80]}' "
                        f"planted in chapter {seed.planted_chapter} is never resolved"
                    ),
                    seed_id=seed.seed_id,
                    suggestion=(
                        "Either resolve this in a later chapter, mark it as "
                        "intentional sequel setup, or remove the foreshadowing"
                    ),
                ))
            elif seed.resolved_chapter <= seed.planted_chapter:
                issues.append(ForeshadowIssue(
                    issue_type="premature_resolution",
                    severity="warning",
                    description=(
                        f"Seed '{seed.description[:60]}' resolved in chapter "
                        f"{seed.resolved_chapter}, same as or before planting "
                        f"in chapter {seed.planted_chapter}"
                    ),
                    seed_id=seed.seed_id,
                    suggestion="Foreshadowing should be planted before resolution",
                ))

        return issues

    def summary(self) -> str:
        """Generate a foreshadowing status report."""
        resolved = sum(1 for s in self.seeds.values() if s.resolved)
        total = len(self.seeds)
        lines = [f"# Foreshadowing Tracker — {resolved}/{total} resolved\n"]

        for seed in sorted(self.seeds.values(), key=lambda s: s.planted_chapter):
            status = "✅" if seed.resolved else "❓"
            lines.append(
                f"  {status} Ch{seed.planted_chapter}: {seed.description[:80]}"
            )
            if seed.resolved:
                lines.append(f"      → Resolved in Ch{seed.resolved_chapter}")

        return "\n".join(lines)
