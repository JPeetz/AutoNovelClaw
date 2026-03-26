"""Full-manuscript continuity verification — combines all checks.

Runs entity tracking, timeline validation, and foreshadowing analysis
across the complete manuscript, producing a unified report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autonovelclaw.continuity.tracker import EntityTracker, ConsistencyIssue
from autonovelclaw.continuity.timeline import (
    TimelineValidator, TimelineIssue,
    ForeshadowTracker, ForeshadowIssue,
)

logger = logging.getLogger(__name__)


@dataclass
class VerificationReport:
    """Unified continuity verification report."""

    entity_issues: list[ConsistencyIssue] = field(default_factory=list)
    timeline_issues: list[TimelineIssue] = field(default_factory=list)
    foreshadow_issues: list[ForeshadowIssue] = field(default_factory=list)
    chapters_checked: int = 0
    entities_tracked: int = 0
    time_references: int = 0
    foreshadow_seeds: int = 0
    foreshadow_resolved: int = 0

    @property
    def total_issues(self) -> int:
        return len(self.entity_issues) + len(self.timeline_issues) + len(self.foreshadow_issues)

    @property
    def error_count(self) -> int:
        return (
            sum(1 for i in self.entity_issues if i.severity == "error")
            + sum(1 for i in self.timeline_issues if i.severity == "error")
            + sum(1 for i in self.foreshadow_issues if i.severity == "error")
        )

    @property
    def warning_count(self) -> int:
        return (
            sum(1 for i in self.entity_issues if i.severity == "warning")
            + sum(1 for i in self.timeline_issues if i.severity == "warning")
            + sum(1 for i in self.foreshadow_issues if i.severity == "warning")
        )

    @property
    def is_clean(self) -> bool:
        return self.error_count == 0 and self.warning_count == 0

    def to_markdown(self) -> str:
        """Generate a comprehensive Markdown report."""
        lines = [
            "# Continuity Verification Report\n",
            f"**Chapters checked:** {self.chapters_checked}",
            f"**Entities tracked:** {self.entities_tracked}",
            f"**Time references:** {self.time_references}",
            f"**Foreshadowing seeds:** {self.foreshadow_seeds} "
            f"({self.foreshadow_resolved} resolved)\n",
            f"**Issues:** {self.total_issues} "
            f"(❌ {self.error_count} errors, ⚠️ {self.warning_count} warnings)\n",
        ]

        if self.is_clean:
            lines.append("✅ **No continuity issues found. Manuscript is consistent.**\n")
            return "\n".join(lines)

        # Entity issues
        if self.entity_issues:
            lines.append("\n## Entity Consistency Issues\n")
            for issue in self.entity_issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.severity, "•")
                lines.append(
                    f"- {icon} **{issue.entity_name}** [{issue.issue_type}]: "
                    f"{issue.description}"
                )
                if issue.suggestion:
                    lines.append(f"  - Fix: {issue.suggestion}")

        # Timeline issues
        if self.timeline_issues:
            lines.append("\n## Timeline Issues\n")
            for issue in self.timeline_issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.severity, "•")
                ch = f" (Ch{issue.chapter})" if issue.chapter else ""
                lines.append(f"- {icon} [{issue.issue_type}]{ch}: {issue.description}")
                if issue.suggestion:
                    lines.append(f"  - Fix: {issue.suggestion}")

        # Foreshadowing issues
        if self.foreshadow_issues:
            lines.append("\n## Foreshadowing Issues\n")
            for issue in self.foreshadow_issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(issue.severity, "•")
                lines.append(f"- {icon} [{issue.issue_type}]: {issue.description}")
                if issue.suggestion:
                    lines.append(f"  - Fix: {issue.suggestion}")

        return "\n".join(lines)


def verify_manuscript(
    chapters: dict[int, str],
    character_profiles: str = "",
    world_codex: str = "",
    book_outline: str = "",
) -> VerificationReport:
    """Run full continuity verification across all chapters.

    Parameters
    ----------
    chapters : dict[int, str]
        Mapping of chapter number → chapter text.
    character_profiles : str
        Full character profiles text (for entity registration).
    world_codex : str
        Full world codex text (for location registration).
    book_outline : str
        Book outline text (for foreshadowing extraction).

    Returns
    -------
    VerificationReport
        Comprehensive report of all continuity issues found.
    """
    report = VerificationReport()

    # --- Entity tracking ---
    entity_tracker = EntityTracker()

    if character_profiles:
        n_chars = entity_tracker.register_characters_from_profiles(character_profiles)
        logger.info("Registered %d characters from profiles", n_chars)

    if world_codex:
        n_locs = entity_tracker.register_locations_from_codex(world_codex)
        logger.info("Registered %d locations from codex", n_locs)

    # --- Timeline tracking ---
    timeline = TimelineValidator()

    # --- Foreshadowing tracking ---
    foreshadow = ForeshadowTracker()
    if book_outline:
        n_seeds = foreshadow.extract_seeds_from_outline(book_outline)
        logger.info("Extracted %d foreshadowing seeds from outline", n_seeds)

    # --- Process each chapter ---
    for ch_num in sorted(chapters.keys()):
        chapter_text = chapters[ch_num]

        # Entity tracking
        entity_issues = entity_tracker.process_chapter(ch_num, chapter_text)
        # Filter to only warnings/errors (skip info-level untracked entities)
        report.entity_issues.extend(
            i for i in entity_issues if i.severity in ("error", "warning")
        )

        # Timeline validation
        time_issues = timeline.process_chapter(ch_num, chapter_text)
        report.timeline_issues.extend(time_issues)

    # --- Cross-chapter checks ---
    report.entity_issues.extend(entity_tracker.check_consistency())
    report.timeline_issues.extend(timeline.check_cross_chapter())
    report.foreshadow_issues.extend(
        foreshadow.check_resolution(len(chapters))
    )

    # --- Stats ---
    report.chapters_checked = len(chapters)
    report.entities_tracked = len(entity_tracker.entities)
    report.time_references = len(timeline.timepoints)
    report.foreshadow_seeds = len(foreshadow.seeds)
    report.foreshadow_resolved = sum(1 for s in foreshadow.seeds.values() if s.resolved)

    return report
