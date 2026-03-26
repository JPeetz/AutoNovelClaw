"""Publishing sub-package — EPUB, PDF, and KDP validation.

The novel-writing equivalent of AutoResearchClaw's templates/ package.

Usage::

    from autonovelclaw.publishing import build_epub, build_pdf, validate_all
"""

from autonovelclaw.publishing.epub_builder import build_epub
from autonovelclaw.publishing.pdf_builder import build_pdf
from autonovelclaw.publishing.validator import (
    KDPValidationReport,
    ValidationIssue,
    validate_epub,
    validate_pdf,
    validate_cover_image,
    validate_metadata,
    validate_all,
)

__all__ = [
    "build_epub", "build_pdf",
    "KDPValidationReport", "ValidationIssue",
    "validate_epub", "validate_pdf", "validate_cover_image",
    "validate_metadata", "validate_all",
]
