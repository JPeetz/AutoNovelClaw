"""Enhancement planner — prioritises changes from reviews.
Convergence tracker — tracks quality trend across enhancement loops.

The planner takes parsed reviews and produces a ranked list of changes
to make, ordered by expected impact on the rating.

The convergence tracker monitors whether enhancement loops are actually
improving quality or just burning tokens on diminishing returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from autonovelclaw.reviewers.parser import ParsedReview, ReviewItem

logger = logging.getLogger(__name__)


# ============================================================================
# Enhancement planner
# ============================================================================

@dataclass
class PlannedChange:
    """A single planned enhancement change."""
    priority: int          # 1 = highest
    category: str          # "prose", "character", "pacing", "sensory", etc.
    description: str       # what to change
    source: str            # "critic", "reader", "debate"
    expected_impact: str   # "high", "medium", "low"
    location_hint: str = "" # where in the chapter
    preserve: str = ""     # what NOT to change (identified strengths)


@dataclass
class EnhancementPlan:
    """Prioritised plan for Phase 1.X enhancement."""
    phase_name: str        # "Phase 1", "Phase 1.5", "Phase 1.75"
    changes: list[PlannedChange] = field(default_factory=list)
    strengths_to_preserve: list[str] = field(default_factory=list)
    max_word_count_delta_pct: float = 5.0

    @property
    def high_impact_count(self) -> int:
        return sum(1 for c in self.changes if c.expected_impact == "high")

    def to_markdown(self) -> str:
        lines = [
            f"# Enhancement Plan — {self.phase_name}\n",
            f"**Changes:** {len(self.changes)} "
            f"({self.high_impact_count} high-impact)",
            f"**Max word count delta:** {self.max_word_count_delta_pct}%\n",
        ]

        if self.strengths_to_preserve:
            lines.append("## Preserve These Strengths\n")
            for s in self.strengths_to_preserve:
                lines.append(f"  ✅ {s}")

        lines.append("\n## Planned Changes (priority order)\n")
        for c in self.changes:
            impact_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                c.expected_impact, "⚪")
            lines.append(
                f"  {c.priority}. {impact_icon} [{c.category}] {c.description}"
            )
            if c.location_hint:
                lines.append(f"     Location: {c.location_hint}")
            lines.append(f"     Source: {c.source}")

        return "\n".join(lines)

    def to_prompt_instructions(self) -> str:
        """Convert the plan into instructions for the enhancement LLM call."""
        parts = [
            f"Apply {self.phase_name} enhancements. Word count delta ≤{self.max_word_count_delta_pct}%.\n",
        ]

        if self.strengths_to_preserve:
            parts.append("PRESERVE THESE (do not change):")
            for s in self.strengths_to_preserve[:5]:
                parts.append(f"  ✅ {s}")
            parts.append("")

        parts.append("CHANGES TO MAKE (highest priority first):")
        for c in self.changes[:7]:  # Cap at 7 to avoid prompt bloat
            parts.append(f"  {c.priority}. [{c.category}] {c.description}")
            if c.location_hint:
                parts.append(f"     → Location: {c.location_hint}")

        return "\n".join(parts)


# Impact scoring based on category and loop iteration
_IMPACT_SCORES: dict[str, dict[int, str]] = {
    # category → {loop_index: expected_impact}
    "sensory": {0: "high", 1: "medium", 2: "low"},
    "prose": {0: "high", 1: "medium", 2: "low"},
    "pacing": {0: "high", 1: "high", 2: "medium"},
    "character": {0: "medium", 1: "high", 2: "medium"},
    "structure": {0: "medium", 1: "low", 2: "low"},
    "continuity": {0: "high", 1: "high", 2: "high"},  # always fix continuity
    "clarity": {0: "high", 1: "medium", 2: "low"},
    "general": {0: "medium", 1: "medium", 2: "low"},
    "engagement": {0: "medium", 1: "medium", 2: "low"},
    "emotional": {0: "medium", 1: "medium", 2: "low"},
}


def plan_enhancement(
    critic_review: ParsedReview,
    reader_review: ParsedReview | None = None,
    debate_analysis: str = "",
    loop_index: int = 0,
    max_changes: int = 7,
) -> EnhancementPlan:
    """Create a prioritised enhancement plan from reviews.

    Parameters
    ----------
    critic_review : ParsedReview
        Parsed Reviewer #1 (literary critic) output.
    reader_review : ParsedReview, optional
        Parsed Reviewer #2 (beta reader) output.
    debate_analysis : str
        Raw text from multi-critic debate analysis.
    loop_index : int
        Which enhancement loop we're in (0 = Phase 1, 1 = Phase 1.5, etc.)
    max_changes : int
        Maximum number of changes to include in the plan.
    """
    phase_name = {0: "Phase 1", 1: "Phase 1.5", 2: "Phase 1.75"}.get(
        loop_index, f"Phase 1.{loop_index}"
    )

    plan = EnhancementPlan(phase_name=phase_name)

    # Collect strengths to preserve
    for s in critic_review.strengths:
        plan.strengths_to_preserve.append(s.text[:100])
    if reader_review:
        for s in reader_review.strengths[:3]:
            if s.text[:100] not in plan.strengths_to_preserve:
                plan.strengths_to_preserve.append(s.text[:100])

    # Collect all change candidates
    candidates: list[tuple[str, ReviewItem, str]] = []

    # From critic suggestions (highest weight)
    for item in critic_review.suggestions:
        candidates.append(("critic", item, "high"))

    # From critic weaknesses (need to convert to actionable changes)
    for item in critic_review.weaknesses:
        candidates.append(("critic_weakness", item, "medium"))

    # From reader suggestions
    if reader_review:
        for item in reader_review.suggestions:
            candidates.append(("reader", item, "medium"))

        # Reader drag points are high-priority pacing fixes
        for dp in reader_review.drag_points:
            candidates.append(("reader_drag", ReviewItem(
                text=f"Fix drag point: {dp}",
                category="pacing",
            ), "high"))

        # Reader confusion points need immediate attention
        for cp in reader_review.confusion_points:
            candidates.append(("reader_confusion", ReviewItem(
                text=f"Clarify: {cp}",
                category="clarity",
            ), "high"))

    # Score and sort candidates
    scored: list[tuple[float, str, ReviewItem, str]] = []
    for source, item, base_impact in candidates:
        # Impact score based on category and loop index
        cat_impacts = _IMPACT_SCORES.get(item.category, _IMPACT_SCORES["general"])
        impact = cat_impacts.get(loop_index, "low")

        # Override: confusion and continuity are always high
        if item.category in ("clarity", "continuity"):
            impact = "high"

        # Numeric score for sorting
        impact_num = {"high": 3.0, "medium": 2.0, "low": 1.0}.get(impact, 1.0)

        # Boost critic suggestions over weaknesses
        if "suggestion" in source or source == "critic":
            impact_num *= 1.2

        # Boost reader drag/confusion points
        if "drag" in source or "confusion" in source:
            impact_num *= 1.3

        scored.append((impact_num, source, item, impact))

    # Sort by impact score (highest first)
    scored.sort(key=lambda x: x[0], reverse=True)

    # Build the plan
    seen_descriptions: set[str] = set()
    for priority, (score, source, item, impact) in enumerate(scored[:max_changes], 1):
        # Deduplicate
        desc_key = item.text[:50].lower()
        if desc_key in seen_descriptions:
            continue
        seen_descriptions.add(desc_key)

        plan.changes.append(PlannedChange(
            priority=priority,
            category=item.category,
            description=item.text,
            source=source.replace("_weakness", " weakness").replace("_", " "),
            expected_impact=impact,
            location_hint=item.location,
        ))

    return plan


# ============================================================================
# Convergence tracker
# ============================================================================

@dataclass
class ConvergencePoint:
    """A single data point in the quality convergence curve."""
    loop_index: int
    critic_rating: float
    reader_rating: float
    composite_rating: float
    improvement: float      # delta from previous loop
    word_count: int = 0
    word_count_delta_pct: float = 0.0


@dataclass
class ConvergenceAnalysis:
    """Analysis of quality convergence across enhancement loops."""
    points: list[ConvergencePoint] = field(default_factory=list)
    target_rating: float = 9.0
    diminishing_threshold: float = 0.2

    @property
    def current_composite(self) -> float:
        return self.points[-1].composite_rating if self.points else 0.0

    @property
    def total_improvement(self) -> float:
        if len(self.points) < 2:
            return 0.0
        return self.points[-1].composite_rating - self.points[0].composite_rating

    @property
    def latest_improvement(self) -> float:
        return self.points[-1].improvement if self.points else 0.0

    @property
    def is_converged(self) -> bool:
        """Check if quality has converged (meets target or diminishing returns)."""
        if not self.points:
            return False
        if self.current_composite >= self.target_rating:
            return True
        if len(self.points) >= 2 and self.latest_improvement < self.diminishing_threshold:
            return True
        return False

    @property
    def convergence_reason(self) -> str:
        if not self.points:
            return "no data"
        if self.current_composite >= self.target_rating:
            return f"target reached ({self.current_composite:.1f} >= {self.target_rating})"
        if len(self.points) >= 2 and self.latest_improvement < self.diminishing_threshold:
            return (
                f"diminishing returns (improvement {self.latest_improvement:+.2f} "
                f"< threshold {self.diminishing_threshold})"
            )
        return "not converged"

    @property
    def trend(self) -> str:
        """Describe the quality trend."""
        if len(self.points) < 2:
            return "insufficient data"
        improvements = [p.improvement for p in self.points[1:]]
        if all(i > 0 for i in improvements):
            return "improving"
        elif all(i < 0 for i in improvements):
            return "degrading"
        elif len(improvements) >= 2 and improvements[-1] < improvements[-2]:
            return "plateauing"
        return "mixed"

    def add_point(
        self,
        critic_rating: float,
        reader_rating: float,
        composite_rating: float,
        word_count: int = 0,
        prev_word_count: int = 0,
    ) -> ConvergencePoint:
        """Add a new convergence data point."""
        prev = self.points[-1].composite_rating if self.points else 0.0
        improvement = composite_rating - prev if self.points else composite_rating

        wc_delta = 0.0
        if prev_word_count > 0:
            wc_delta = ((word_count - prev_word_count) / prev_word_count) * 100

        point = ConvergencePoint(
            loop_index=len(self.points),
            critic_rating=critic_rating,
            reader_rating=reader_rating,
            composite_rating=composite_rating,
            improvement=improvement,
            word_count=word_count,
            word_count_delta_pct=wc_delta,
        )
        self.points.append(point)
        return point

    def to_markdown(self) -> str:
        lines = [
            "# Quality Convergence Analysis\n",
            f"**Target:** {self.target_rating}/10",
            f"**Current:** {self.current_composite:.1f}/10",
            f"**Converged:** {'✅ ' + self.convergence_reason if self.is_converged else '❌ ' + self.convergence_reason}",
            f"**Trend:** {self.trend}",
            f"**Total improvement:** {self.total_improvement:+.2f}\n",
        ]

        if self.points:
            lines.append("## Loop History\n")
            lines.append("| Loop | Critic | Reader | Composite | Δ | Words | WC Δ |")
            lines.append("|------|--------|--------|-----------|-----|-------|------|")
            for p in self.points:
                lines.append(
                    f"| {p.loop_index} | {p.critic_rating:.1f} | "
                    f"{p.reader_rating:.1f} | {p.composite_rating:.1f} | "
                    f"{p.improvement:+.2f} | {p.word_count:,} | "
                    f"{p.word_count_delta_pct:+.1f}% |"
                )

        return "\n".join(lines)
