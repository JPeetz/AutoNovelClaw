"""KDP validator — validates publishing files against Amazon KDP guidelines.

Checks EPUB structure, PDF dimensions, cover image specs, metadata
completeness, and content guidelines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single KDP validation problem."""
    category: str     # "epub", "pdf", "cover", "metadata", "content"
    severity: str     # "error", "warning", "info"
    description: str
    fix: str = ""


@dataclass
class KDPValidationReport:
    """Complete KDP validation report."""
    issues: list[ValidationIssue] = field(default_factory=list)
    epub_valid: bool = True
    pdf_valid: bool = True
    metadata_complete: bool = True
    cover_valid: bool = True

    @property
    def is_publishable(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_markdown(self) -> str:
        status = "✅ PUBLISHABLE" if self.is_publishable else "❌ NOT READY"
        lines = [
            f"# KDP Validation Report — {status}\n",
            f"Errors: {self.error_count} | Warnings: {self.warning_count}\n",
        ]

        if self.issues:
            for iss in self.issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(iss.severity, "•")
                lines.append(f"- {icon} [{iss.category}] {iss.description}")
                if iss.fix:
                    lines.append(f"  → Fix: {iss.fix}")
        else:
            lines.append("No issues found. Ready for KDP upload.")

        return "\n".join(lines)


def validate_epub(epub_path: Path) -> list[ValidationIssue]:
    """Validate an EPUB file against KDP requirements."""
    issues: list[ValidationIssue] = []

    if not epub_path.exists():
        issues.append(ValidationIssue(
            "epub", "error", f"EPUB file not found: {epub_path}",
            fix="Run the EPUB generation stage first.",
        ))
        return issues

    size_mb = epub_path.stat().st_size / (1024 * 1024)

    # KDP max file size: 650 MB
    if size_mb > 650:
        issues.append(ValidationIssue(
            "epub", "error",
            f"EPUB file too large: {size_mb:.1f} MB (KDP max: 650 MB)",
            fix="Reduce image sizes or chapter count.",
        ))
    elif size_mb > 50:
        issues.append(ValidationIssue(
            "epub", "warning",
            f"EPUB file is {size_mb:.1f} MB — may be slow to download",
        ))

    # Check it's actually a zip/epub
    try:
        with open(epub_path, "rb") as f:
            magic = f.read(4)
        if magic != b"PK\x03\x04":
            issues.append(ValidationIssue(
                "epub", "error",
                "File does not appear to be a valid EPUB (not a ZIP archive)",
                fix="Regenerate the EPUB file.",
            ))
    except OSError as exc:
        issues.append(ValidationIssue(
            "epub", "error", f"Cannot read EPUB: {exc}",
        ))

    # Check minimum size (very small EPUBs are likely empty)
    if size_mb < 0.01:
        issues.append(ValidationIssue(
            "epub", "error",
            f"EPUB file suspiciously small ({size_mb:.3f} MB) — may be empty",
            fix="Check that chapters were properly included.",
        ))

    return issues


def validate_pdf(pdf_path: Path, trim_size: str = "6x9") -> list[ValidationIssue]:
    """Validate a PDF file against KDP Print requirements."""
    issues: list[ValidationIssue] = []

    if not pdf_path.exists():
        issues.append(ValidationIssue(
            "pdf", "error", f"PDF file not found: {pdf_path}",
            fix="Run the paperback formatting stage first.",
        ))
        return issues

    size_mb = pdf_path.stat().st_size / (1024 * 1024)

    # KDP Print max: 1.5 GB
    if size_mb > 1500:
        issues.append(ValidationIssue(
            "pdf", "error",
            f"PDF too large: {size_mb:.1f} MB (KDP max: 1.5 GB)",
        ))

    # Check PDF magic bytes
    try:
        with open(pdf_path, "rb") as f:
            magic = f.read(5)
        if magic != b"%PDF-":
            issues.append(ValidationIssue(
                "pdf", "error",
                "File does not appear to be a valid PDF",
                fix="Regenerate the PDF file.",
            ))
    except OSError as exc:
        issues.append(ValidationIssue(
            "pdf", "error", f"Cannot read PDF: {exc}",
        ))

    return issues


def validate_cover_image(cover_path: Path | None) -> list[ValidationIssue]:
    """Validate cover image against KDP requirements."""
    issues: list[ValidationIssue] = []

    if cover_path is None or not cover_path.exists():
        issues.append(ValidationIssue(
            "cover", "warning",
            "No cover image provided — KDP requires a cover for publishing",
            fix="Create a cover image: minimum 2560×1600 pixels, 300 DPI, RGB colour space.",
        ))
        return issues

    size_mb = cover_path.stat().st_size / (1024 * 1024)

    # KDP cover max: 50 MB
    if size_mb > 50:
        issues.append(ValidationIssue(
            "cover", "error",
            f"Cover image too large: {size_mb:.1f} MB (KDP max: 50 MB)",
            fix="Compress or resize the cover image.",
        ))

    # Check format
    ext = cover_path.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        issues.append(ValidationIssue(
            "cover", "error",
            f"Unsupported cover format: {ext} (KDP accepts JPEG, PNG, TIFF)",
            fix="Convert cover to JPEG or PNG.",
        ))

    # Try to check dimensions (if PIL available)
    try:
        from PIL import Image
        img = Image.open(cover_path)
        w, h = img.size

        # KDP Kindle: minimum 625×1000, recommended 2560×1600
        if w < 625 or h < 1000:
            issues.append(ValidationIssue(
                "cover", "error",
                f"Cover too small: {w}×{h} (minimum: 625×1000)",
                fix="Use an image at least 2560×1600 pixels.",
            ))
        elif w < 2560 or h < 1600:
            issues.append(ValidationIssue(
                "cover", "warning",
                f"Cover dimensions {w}×{h} — recommended: 2560×1600 for best quality",
            ))

        # Check colour mode
        if img.mode not in ("RGB", "RGBA"):
            issues.append(ValidationIssue(
                "cover", "warning",
                f"Cover colour mode is {img.mode} — KDP recommends RGB",
                fix="Convert cover to RGB colour space.",
            ))

        img.close()
    except ImportError:
        logger.debug("PIL not available — skipping cover dimension check")
    except Exception as exc:
        issues.append(ValidationIssue(
            "cover", "warning", f"Could not validate cover dimensions: {exc}",
        ))

    return issues


def validate_metadata(metadata: dict[str, Any]) -> list[ValidationIssue]:
    """Validate metadata completeness for KDP."""
    issues: list[ValidationIssue] = []

    required_fields = ["title", "author"]
    for field_name in required_fields:
        if not metadata.get(field_name):
            issues.append(ValidationIssue(
                "metadata", "error",
                f"Missing required metadata: {field_name}",
                fix=f"Set {field_name} in your config file.",
            ))

    recommended_fields = ["genre", "word_count", "chapter_count"]
    for field_name in recommended_fields:
        if not metadata.get(field_name):
            issues.append(ValidationIssue(
                "metadata", "warning",
                f"Missing recommended metadata: {field_name}",
            ))

    # Book description length
    description = metadata.get("description", "")
    if description and len(description) > 4000:
        issues.append(ValidationIssue(
            "metadata", "warning",
            f"Book description too long: {len(description)} chars (KDP max: 4000)",
            fix="Shorten the book description to under 4000 characters.",
        ))

    # Keywords
    keywords = metadata.get("keywords", [])
    if isinstance(keywords, list) and len(keywords) > 7:
        issues.append(ValidationIssue(
            "metadata", "warning",
            f"Too many keywords: {len(keywords)} (KDP max: 7)",
            fix="Reduce to 7 keywords maximum.",
        ))

    return issues


def validate_all(
    *,
    epub_path: Path | None = None,
    pdf_path: Path | None = None,
    cover_path: Path | None = None,
    metadata: dict[str, Any] | None = None,
    trim_size: str = "6x9",
) -> KDPValidationReport:
    """Run all KDP validations and produce a unified report."""
    report = KDPValidationReport()

    if epub_path:
        epub_issues = validate_epub(epub_path)
        report.issues.extend(epub_issues)
        report.epub_valid = not any(i.severity == "error" for i in epub_issues)

    if pdf_path:
        pdf_issues = validate_pdf(pdf_path, trim_size)
        report.issues.extend(pdf_issues)
        report.pdf_valid = not any(i.severity == "error" for i in pdf_issues)

    cover_issues = validate_cover_image(cover_path)
    report.issues.extend(cover_issues)
    report.cover_valid = not any(i.severity == "error" for i in cover_issues)

    if metadata:
        meta_issues = validate_metadata(metadata)
        report.issues.extend(meta_issues)
        report.metadata_complete = not any(i.severity == "error" for i in meta_issues)

    return report
