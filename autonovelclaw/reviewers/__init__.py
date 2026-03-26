"""Reviewers sub-package — review parsing, enhancement planning, convergence tracking.

The novel-writing equivalent of AutoResearchClaw's agents/benchmark_agent/
and agents/figure_agent/ packages.

Usage::

    from autonovelclaw.reviewers import parse_critic_review, plan_enhancement, ConvergenceAnalysis

    critic = parse_critic_review(review_text)
    plan = plan_enhancement(critic, reader_review)
    print(plan.to_markdown())
"""

from autonovelclaw.reviewers.parser import (
    ParsedReview,
    ReviewItem,
    parse_critic_review,
    parse_reader_review,
    combine_reviews,
    extract_rating,
)
from autonovelclaw.reviewers.planner import (
    EnhancementPlan,
    PlannedChange,
    ConvergenceAnalysis,
    ConvergencePoint,
    plan_enhancement,
)

__all__ = [
    "ParsedReview", "ReviewItem",
    "parse_critic_review", "parse_reader_review", "combine_reviews", "extract_rating",
    "EnhancementPlan", "PlannedChange", "plan_enhancement",
    "ConvergenceAnalysis", "ConvergencePoint",
]
