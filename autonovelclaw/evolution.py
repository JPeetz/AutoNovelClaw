"""Self-evolution system for the AutoNovelClaw pipeline.

Records lessons from each chapter and pipeline run (failures, quality issues,
reviewer patterns, enhancement effectiveness) and injects them into future
stages as prompt overlays.

Architecture
------------
* ``LessonCategory`` — 6 categories for novel-writing lessons.
* ``LessonEntry`` — single lesson (stage, category, severity, description, ts).
* ``EvolutionStore`` — JSONL-backed persistent store with append + query.
* ``extract_lessons_from_decisions()`` — auto-extract lessons from pipeline decisions.
* ``extract_lessons_from_reviews()`` — extract patterns from reviewer feedback.
* ``build_overlay()`` — generate per-stage prompt overlay text.

Usage
-----
::

    from autonovelclaw.evolution import EvolutionStore, extract_lessons_from_decisions

    store = EvolutionStore(Path("evolution"))
    lessons = extract_lessons_from_decisions(decisions)
    store.append_many(lessons)
    overlay = store.build_overlay("chapter_draft", max_lessons=5)
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lesson categories for novel writing
# ---------------------------------------------------------------------------

class LessonCategory(str, Enum):
    """Issue classification for extracted lessons."""

    PROSE = "prose"              # Voice drift, cliché usage, sensory gaps
    CHARACTER = "character"      # Consistency errors, flat characters, voice issues
    PACING = "pacing"            # Drag points, rushed scenes, rhythm problems
    CONTINUITY = "continuity"    # Name/timeline/world-rule errors caught by sentinel
    ENHANCEMENT = "enhancement"  # Which techniques improved ratings most
    PIPELINE = "pipeline"        # Stage failures, rate limits, system issues
    REVIEW = "review"            # Recurring reviewer complaints, rating patterns


_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    LessonCategory.PROSE: [
        "cliché", "cliche", "generic", "ai-typical", "phrasing", "voice drift",
        "sensory", "olfactory", "visual", "kinesthetic", "purple prose",
        "overwrought", "sentence rhythm", "repetitive", "show don't tell",
        "descriptor", "palpable", "tapestry", "symphony",
    ],
    LessonCategory.CHARACTER: [
        "character", "dialogue", "voice", "mannerism", "flat", "cardboard",
        "generic character", "speech pattern", "motivation", "arc",
        "personality", "contradictions", "believable",
    ],
    LessonCategory.PACING: [
        "pacing", "drag", "slow", "rushed", "tension", "momentum",
        "scene length", "action beat", "reflection", "hook", "boring",
        "skimming", "skim", "engaging", "page-turner",
    ],
    LessonCategory.CONTINUITY: [
        "continuity", "consistency", "name", "timeline", "geography",
        "world rule", "magic system", "foreshadowing", "contradiction",
        "established fact", "dead end",
    ],
    LessonCategory.ENHANCEMENT: [
        "enhancement", "phase 1", "surgical", "improvement", "rating",
        "converge", "convergence", "diminishing", "word count delta",
        "technique", "effective",
    ],
    LessonCategory.PIPELINE: [
        "timeout", "rate limit", "connection", "api", "failed",
        "retry", "error", "crash", "memory", "token",
    ],
    LessonCategory.REVIEW: [
        "reviewer", "critic", "reader", "feedback", "suggestion",
        "weakness", "strength", "rating pattern",
    ],
}


# ---------------------------------------------------------------------------
# Lesson entry
# ---------------------------------------------------------------------------

@dataclass
class LessonEntry:
    """A single lesson extracted from a pipeline run."""

    stage_name: str
    stage_num: int
    category: str
    severity: str   # "info", "warning", "error"
    description: str
    timestamp: str   # ISO 8601
    run_id: str = ""
    chapter: int = 0
    rating_before: float = 0.0
    rating_after: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LessonEntry:
        return cls(
            stage_name=str(data.get("stage_name", "")),
            stage_num=int(data.get("stage_num", 0)),
            category=str(data.get("category", "pipeline")),
            severity=str(data.get("severity", "info")),
            description=str(data.get("description", "")),
            timestamp=str(data.get("timestamp", "")),
            run_id=str(data.get("run_id", "")),
            chapter=int(data.get("chapter", 0)),
            rating_before=float(data.get("rating_before", 0)),
            rating_after=float(data.get("rating_after", 0)),
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(stage_name: str, text: str) -> str:
    """Classify text into a LessonCategory based on keyword matches."""
    combined = f"{stage_name} {text}".lower()
    best_category = LessonCategory.PIPELINE
    best_score = 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


# ---------------------------------------------------------------------------
# Lesson extraction
# ---------------------------------------------------------------------------

def extract_lessons_from_decisions(
    decisions: list[dict[str, Any]],
    run_id: str = "",
) -> list[LessonEntry]:
    """Extract lessons from pipeline decision records.

    Detects:
    - REWRITE decisions → what went wrong enough to need a full rewrite
    - REFINE decisions → what needed surgical improvement
    - HUMAN_ESCALATION → loops exhausted, human had to intervene
    - Rating patterns → chapters that struggled vs sailed through
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lessons: list[LessonEntry] = []

    for dec in decisions:
        stage = str(dec.get("stage", ""))
        decision = str(dec.get("decision", ""))
        rationale = str(dec.get("rationale", ""))
        chapter = int(dec.get("chapter", 0))

        if decision == "rewrite":
            lessons.append(LessonEntry(
                stage_name=stage,
                stage_num=0,
                category=LessonCategory.PROSE,
                severity="error",
                description=f"Chapter {chapter} required full REWRITE: {rationale[:300]}",
                timestamp=now,
                run_id=run_id,
                chapter=chapter,
            ))

        elif decision == "human_escalation":
            lessons.append(LessonEntry(
                stage_name=stage,
                stage_num=0,
                category=LessonCategory.PIPELINE,
                severity="error",
                description=f"Chapter {chapter} required HUMAN ESCALATION: {rationale[:300]}",
                timestamp=now,
                run_id=run_id,
                chapter=chapter,
            ))

        elif decision == "refine":
            category = _classify(stage, rationale)
            lessons.append(LessonEntry(
                stage_name=stage,
                stage_num=0,
                category=category,
                severity="warning",
                description=f"Chapter {chapter} needed REFINE: {rationale[:300]}",
                timestamp=now,
                run_id=run_id,
                chapter=chapter,
            ))

        elif decision == "rejected":
            lessons.append(LessonEntry(
                stage_name=stage,
                stage_num=0,
                category=LessonCategory.PIPELINE,
                severity="warning",
                description=f"Gate rejected at {stage}: {rationale[:300]}",
                timestamp=now,
                run_id=run_id,
                chapter=chapter,
            ))

    return lessons


def extract_lessons_from_reviews(
    review_text: str,
    chapter: int,
    rating: float,
    reviewer_id: int = 1,
    run_id: str = "",
) -> list[LessonEntry]:
    """Extract recurring patterns from reviewer feedback.

    Scans review text for common complaint patterns and creates lessons
    so future chapters can preemptively address them.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lessons: list[LessonEntry] = []
    review_lower = review_text.lower()

    # Pattern detection
    patterns: list[tuple[str, str, str]] = [
        # (keyword_pattern, category, description_template)
        (r"sensory.{0,30}(thin|lacking|missing|weak|absent)",
         LessonCategory.PROSE,
         "Reviewer flagged weak sensory immersion in chapter {ch}"),
        (r"(cliché|cliche|generic|ai-typical|boilerplate)",
         LessonCategory.PROSE,
         "Reviewer detected clichéd or generic phrasing in chapter {ch}"),
        (r"(pacing|drag|slow|boring|skim|lost.{0,10}focus)",
         LessonCategory.PACING,
         "Reviewer flagged pacing issues (dragging/boring) in chapter {ch}"),
        (r"dialogue.{0,30}(flat|generic|stilted|unnatural|same)",
         LessonCategory.CHARACTER,
         "Reviewer flagged flat/generic dialogue in chapter {ch}"),
        (r"(character|protagonist).{0,30}(flat|one-dimensional|cardboard|generic)",
         LessonCategory.CHARACTER,
         "Reviewer flagged flat characterisation in chapter {ch}"),
        (r"(confus|unclear|lost|didn.t understand|had to re-?read)",
         LessonCategory.PACING,
         "Reviewer reported confusion points in chapter {ch}"),
        (r"(exposition|info.?dump|telling.{0,10}not.{0,10}showing)",
         LessonCategory.PROSE,
         "Reviewer flagged exposition/telling-not-showing in chapter {ch}"),
        (r"pov.{0,20}(break|inconsistent|shift|head.?hopping)",
         LessonCategory.CONTINUITY,
         "Reviewer detected POV breaks in chapter {ch}"),
    ]

    for pat, category, desc_template in patterns:
        if re.search(pat, review_lower):
            lessons.append(LessonEntry(
                stage_name="independent_review",
                stage_num=17,
                category=category,
                severity="warning",
                description=desc_template.format(ch=chapter),
                timestamp=now,
                run_id=run_id,
                chapter=chapter,
                rating_before=rating,
            ))

    # Low rating lesson
    if rating < 7.5:
        lessons.append(LessonEntry(
            stage_name="independent_review",
            stage_num=17,
            category=LessonCategory.REVIEW,
            severity="error",
            description=(
                f"Chapter {chapter} rated {rating:.1f}/10 — below refine threshold. "
                f"Review highlights: {review_text[:200]}"
            ),
            timestamp=now,
            run_id=run_id,
            chapter=chapter,
            rating_before=rating,
        ))

    return lessons


def extract_lessons_from_enhancement(
    chapter: int,
    phase_name: str,
    rating_before: float,
    rating_after: float,
    change_log: str,
    run_id: str = "",
) -> list[LessonEntry]:
    """Track which enhancement techniques improved ratings most."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    improvement = rating_after - rating_before

    severity = "info"
    if improvement >= 0.5:
        severity = "info"  # good improvement
    elif improvement < 0.1:
        severity = "warning"  # poor improvement

    return [LessonEntry(
        stage_name="surgical_enhancement",
        stage_num=20,
        category=LessonCategory.ENHANCEMENT,
        severity=severity,
        description=(
            f"Chapter {chapter} {phase_name}: {rating_before:.1f} → {rating_after:.1f} "
            f"({improvement:+.1f}). Changes: {change_log[:200]}"
        ),
        timestamp=now,
        run_id=run_id,
        chapter=chapter,
        rating_before=rating_before,
        rating_after=rating_after,
    )]


# ---------------------------------------------------------------------------
# Time-decay weighting
# ---------------------------------------------------------------------------

HALF_LIFE_DAYS: float = 45.0   # Novel-writing lessons decay slower than research
MAX_AGE_DAYS: float = 90.0


def _time_weight(timestamp_iso: str) -> float:
    """Compute exponential decay weight based on lesson age.

    Uses 45-day half-life (creative insights age slower than technical ones).
    Returns 0.0 for lessons older than 90 days.
    """
    try:
        ts = datetime.fromisoformat(timestamp_iso)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        age_days = age.total_seconds() / 86400.0
        if age_days > MAX_AGE_DAYS:
            return 0.0
        return math.exp(-age_days * math.log(2) / HALF_LIFE_DAYS)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Evolution store
# ---------------------------------------------------------------------------

class EvolutionStore:
    """JSONL-backed persistent store for pipeline lessons.

    Supports:
    - Append individual or batch lessons
    - Query with time-decay weighting and stage relevance
    - Generate per-stage prompt overlays
    - Track effectiveness of enhancement techniques
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lessons_path = self._dir / "lessons.jsonl"

    @property
    def lessons_path(self) -> Path:
        return self._lessons_path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, lesson: LessonEntry) -> None:
        """Append a single lesson."""
        with self._lessons_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")

    def append_many(self, lessons: list[LessonEntry]) -> None:
        """Append multiple lessons atomically."""
        if not lessons:
            return
        with self._lessons_path.open("a", encoding="utf-8") as f:
            for lesson in lessons:
                f.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Appended %d lessons to evolution store", len(lessons))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_all(self) -> list[LessonEntry]:
        """Load all lessons from disk."""
        if not self._lessons_path.exists():
            return []
        lessons: list[LessonEntry] = []
        for line in self._lessons_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                lessons.append(LessonEntry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return lessons

    def count(self) -> int:
        """Return total number of stored lessons."""
        return len(self.load_all())

    # ------------------------------------------------------------------
    # Query with relevance scoring
    # ------------------------------------------------------------------

    def query_for_stage(
        self,
        stage_name: str,
        *,
        max_lessons: int = 5,
        category_filter: str | None = None,
    ) -> list[LessonEntry]:
        """Return the most relevant lessons for a stage, weighted by recency.

        Scoring:
        - Time-decay weight (45-day half-life, 90-day max)
        - 2× boost for direct stage name matches
        - 1.5× boost for errors over warnings/info
        - Optional category filter
        """
        all_lessons = self.load_all()
        scored: list[tuple[float, LessonEntry]] = []

        for lesson in all_lessons:
            weight = _time_weight(lesson.timestamp)
            if weight <= 0.0:
                continue
            if category_filter and lesson.category != category_filter:
                continue

            # Boost direct stage matches
            if lesson.stage_name == stage_name:
                weight *= 2.0

            # Boost errors
            if lesson.severity == "error":
                weight *= 1.5
            elif lesson.severity == "warning":
                weight *= 1.2

            scored.append((weight, lesson))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:max_lessons]]

    def query_enhancement_effectiveness(self) -> list[dict[str, Any]]:
        """Analyse which enhancement techniques yielded the best improvements.

        Returns sorted list of enhancement lessons with improvement deltas.
        """
        all_lessons = self.load_all()
        enhancements = [
            {
                "chapter": l.chapter,
                "description": l.description,
                "improvement": l.rating_after - l.rating_before,
                "rating_before": l.rating_before,
                "rating_after": l.rating_after,
                "timestamp": l.timestamp,
            }
            for l in all_lessons
            if l.category == LessonCategory.ENHANCEMENT
            and l.rating_before > 0
            and l.rating_after > 0
        ]
        enhancements.sort(key=lambda x: x["improvement"], reverse=True)
        return enhancements

    # ------------------------------------------------------------------
    # Prompt overlay generation
    # ------------------------------------------------------------------

    def build_overlay(
        self,
        stage_name: str,
        *,
        max_lessons: int = 5,
    ) -> str:
        """Generate a prompt overlay for a given stage.

        Returns a formatted string to inject into the stage's system prompt.
        Empty string if no relevant lessons exist.
        """
        lessons = self.query_for_stage(stage_name, max_lessons=max_lessons)
        if not lessons:
            return ""

        parts: list[str] = ["## Lessons from Prior Chapters/Runs\n"]
        severity_icons = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}

        for i, lesson in enumerate(lessons, 1):
            icon = severity_icons.get(lesson.severity, "•")
            parts.append(
                f"{i}. {icon} [{lesson.category}] {lesson.description}"
            )

        parts.append(
            "\nUse these lessons to avoid repeating past mistakes "
            "and apply techniques that worked."
        )

        # Add enhancement effectiveness summary if writing/enhancing
        if stage_name in ("chapter_draft", "surgical_enhancement"):
            effective = self.query_enhancement_effectiveness()
            if effective:
                best = effective[:3]
                parts.append("\n### Most Effective Techniques")
                for item in best:
                    parts.append(
                        f"- Ch{item['chapter']}: {item['improvement']:+.1f} rating "
                        f"({item['description'][:100]})"
                    )

        return "\n".join(parts)

    def build_summary_report(self) -> str:
        """Generate a human-readable summary of all lessons."""
        all_lessons = self.load_all()
        if not all_lessons:
            return "No lessons recorded yet."

        # Group by category
        by_cat: dict[str, list[LessonEntry]] = {}
        for l in all_lessons:
            by_cat.setdefault(l.category, []).append(l)

        parts = [f"# Evolution Report — {len(all_lessons)} lessons\n"]
        for cat, lessons in sorted(by_cat.items()):
            parts.append(f"\n## {cat.upper()} ({len(lessons)} lessons)")
            for l in lessons[-5:]:  # Last 5 per category
                parts.append(f"  - [{l.severity}] {l.description[:120]}")

        # Enhancement effectiveness
        effective = self.query_enhancement_effectiveness()
        if effective:
            avg_improvement = sum(e["improvement"] for e in effective) / len(effective)
            parts.append(f"\n## Enhancement Effectiveness")
            parts.append(f"  Average improvement: {avg_improvement:+.2f} rating points")
            parts.append(f"  Best: {effective[0]['improvement']:+.1f} (Ch{effective[0]['chapter']})")
            if len(effective) > 1:
                worst = effective[-1]
                parts.append(f"  Worst: {worst['improvement']:+.1f} (Ch{worst['chapter']})")

        return "\n".join(parts)
