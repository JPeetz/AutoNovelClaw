"""Continuity sub-package — entity tracking, timeline validation, foreshadowing.

The novel-writing equivalent of AutoResearchClaw's literature/ package.
Ensures consistency across 60K+ words of manuscript.

Usage::

    from autonovelclaw.continuity import verify_manuscript
    report = verify_manuscript(chapters, character_profiles, world_codex, outline)
    print(report.to_markdown())
"""

from autonovelclaw.continuity.tracker import (
    EntityTracker,
    TrackedEntity,
    ConsistencyIssue,
)
from autonovelclaw.continuity.timeline import (
    TimelineValidator,
    TimelineIssue,
    ForeshadowTracker,
    ForeshadowIssue,
)
from autonovelclaw.continuity.verify import (
    VerificationReport,
    verify_manuscript,
)

__all__ = [
    "EntityTracker", "TrackedEntity", "ConsistencyIssue",
    "TimelineValidator", "TimelineIssue",
    "ForeshadowTracker", "ForeshadowIssue",
    "VerificationReport", "verify_manuscript",
]
