"""Chapter sub-package — context management, sensory auditing, and validation.

The novel-writing equivalent of AutoResearchClaw's experiment/ package.

Usage::

    from autonovelclaw.chapter import assemble_writer_context, audit_chapter_sensory, validate_chapter_structure
"""

from autonovelclaw.chapter.context import (
    AssembledContext,
    ContextBudget,
    assemble_writer_context,
    extract_relevant_codex,
    extract_active_characters,
    build_rolling_context,
)
from autonovelclaw.chapter.sensory_auditor import (
    SensoryAuditReport,
    ParagraphSensory,
    audit_chapter_sensory,
)
from autonovelclaw.chapter.validator import (
    StructureReport,
    StructureIssue,
    validate_chapter_structure,
)

__all__ = [
    "AssembledContext", "ContextBudget", "assemble_writer_context",
    "extract_relevant_codex", "extract_active_characters", "build_rolling_context",
    "SensoryAuditReport", "ParagraphSensory", "audit_chapter_sensory",
    "StructureReport", "StructureIssue", "validate_chapter_structure",
]
