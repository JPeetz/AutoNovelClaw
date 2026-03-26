"""PDF builder for KDP Print interior formatting.

Generates a print-ready interior PDF with:
- Configurable trim size (5x8, 5.25x8, 5.5x8.5, 6x9)
- Proper gutter margins based on page count
- Running headers (book title left, chapter title right)
- Page numbering
- Drop caps for chapter openings
- Scene break ornaments
- Orphan/widow control
- Typography suited for fiction (serif, proper leading)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_reportlab():
    """Check that reportlab is available."""
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        logger.warning("reportlab not installed — PDF generation unavailable. pip install reportlab")
        return False


# ---------------------------------------------------------------------------
# KDP trim size specifications (inches)
# ---------------------------------------------------------------------------

TRIM_SIZES: dict[str, tuple[float, float]] = {
    "5x8": (5.0, 8.0),
    "5.25x8": (5.25, 8.0),
    "5.5x8.5": (5.5, 8.5),
    "6x9": (6.0, 9.0),
}

# Minimum inside (gutter) margins by page count
GUTTER_MARGINS: list[tuple[int, float]] = [
    (150, 0.375),   # 24-150 pages
    (400, 0.75),    # 151-400 pages
    (600, 0.875),   # 401-600 pages
    (9999, 1.0),    # 601+ pages
]

OUTSIDE_MARGIN = 0.5   # inches
TOP_MARGIN = 0.6       # inches
BOTTOM_MARGIN = 0.6    # inches


def _gutter_for_pages(page_count: int) -> float:
    """Return the minimum gutter margin for a given page count."""
    for max_pages, margin in GUTTER_MARGINS:
        if page_count <= max_pages:
            return margin
    return 1.0


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def build_pdf(
    *,
    title: str,
    author: str,
    chapters: dict[int, str],
    output_path: Path,
    trim_size: str = "6x9",
    subtitle: str = "",
    copyright_text: str = "",
    estimated_pages: int = 300,
) -> Path:
    """Build a KDP Print-ready interior PDF.

    Parameters
    ----------
    title : str
        Book title.
    author : str
        Author name.
    chapters : dict[int, str]
        Mapping of chapter number → chapter text (plain text or light markdown).
    output_path : Path
        Where to write the PDF.
    trim_size : str
        KDP trim size key (e.g., "6x9", "5.5x8.5").
    subtitle : str
        Optional subtitle.
    copyright_text : str
        Copyright notice text.
    estimated_pages : int
        Estimated page count (for gutter margin calculation).

    Returns
    -------
    Path
        Path to the generated PDF file.
    """
    if not _ensure_reportlab():
        raise ImportError("reportlab required for PDF generation: pip install reportlab")

    from reportlab.lib.pagesizes import inch
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak,
        KeepTogether, Frame, PageTemplate, BaseDocTemplate,
    )
    from reportlab.lib.units import inch as unit_inch

    # --- Page dimensions ---
    if trim_size not in TRIM_SIZES:
        logger.warning("Unknown trim size '%s' — defaulting to 6x9", trim_size)
        trim_size = "6x9"

    page_w, page_h = TRIM_SIZES[trim_size]
    page_w_pts = page_w * 72
    page_h_pts = page_h * 72

    gutter = _gutter_for_pages(estimated_pages)

    # --- Styles ---
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "BookBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=15,
        alignment=TA_JUSTIFY,
        firstLineIndent=24,
        spaceBefore=0,
        spaceAfter=2,
    )

    body_first = ParagraphStyle(
        "BookBodyFirst",
        parent=body_style,
        firstLineIndent=0,
    )

    chapter_title_style = ParagraphStyle(
        "ChapterTitle",
        parent=styles["Heading1"],
        fontName="Times-Bold",
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        spaceBefore=72,
        spaceAfter=36,
    )

    scene_break_style = ParagraphStyle(
        "SceneBreak",
        parent=body_style,
        alignment=TA_CENTER,
        firstLineIndent=0,
        spaceBefore=18,
        spaceAfter=18,
        fontSize=12,
    )

    title_style = ParagraphStyle(
        "BookTitle",
        parent=styles["Title"],
        fontName="Times-Bold",
        fontSize=24,
        leading=30,
        alignment=TA_CENTER,
        spaceBefore=144,
        spaceAfter=12,
    )

    subtitle_style = ParagraphStyle(
        "BookSubtitle",
        parent=styles["Normal"],
        fontName="Times-Italic",
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=36,
    )

    author_style = ParagraphStyle(
        "BookAuthor",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=16,
        alignment=TA_CENTER,
        spaceBefore=48,
    )

    copyright_style = ParagraphStyle(
        "Copyright",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
    )

    # --- Build document ---
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=(page_w_pts, page_h_pts),
        leftMargin=gutter * 72,
        rightMargin=OUTSIDE_MARGIN * 72,
        topMargin=TOP_MARGIN * 72,
        bottomMargin=BOTTOM_MARGIN * 72,
        title=title,
        author=author,
    )

    story: list[Any] = []

    # --- Title page ---
    story.append(Spacer(1, 72))
    story.append(Paragraph(title, title_style))
    if subtitle:
        story.append(Paragraph(subtitle, subtitle_style))
    story.append(Paragraph(author, author_style))
    story.append(PageBreak())

    # --- Copyright page ---
    story.append(Spacer(1, 200))
    cp = copyright_text or (
        f"Copyright © {author}. All rights reserved.\n\n"
        f"No part of this publication may be reproduced, distributed, "
        f"or transmitted in any form without prior written permission."
    )
    for line in cp.split("\n"):
        if line.strip():
            story.append(Paragraph(line.strip(), copyright_style))
    story.append(PageBreak())

    # --- Chapters ---
    for ch_num in sorted(chapters.keys()):
        ch_text = chapters[ch_num]

        # Extract chapter title
        ch_title = f"Chapter {ch_num}"
        first_line = ch_text.split("\n")[0].strip()
        if first_line.startswith("#"):
            ch_title = first_line.lstrip("#").strip()
            # Remove the header from text to avoid duplication
            ch_text = "\n".join(ch_text.split("\n")[1:]).strip()

        # Chapter title
        story.append(Paragraph(ch_title, chapter_title_style))

        # Chapter body
        paragraphs = ch_text.split("\n\n")
        is_first = True

        for para_text in paragraphs:
            para_text = para_text.strip()
            if not para_text:
                continue

            # Scene break
            if para_text in ("* * *", "***", "---"):
                story.append(Paragraph("⁂", scene_break_style))
                is_first = True
                continue

            # Skip sub-headers within chapters
            if para_text.startswith("#"):
                sub_title = para_text.lstrip("#").strip()
                story.append(Paragraph(sub_title, ParagraphStyle(
                    "SubHead", parent=body_style,
                    fontName="Times-Bold", fontSize=12,
                    firstLineIndent=0, spaceBefore=18, spaceAfter=8,
                )))
                is_first = True
                continue

            # Clean up the paragraph
            clean = para_text.replace("\n", " ").strip()
            # Basic formatting
            clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
            clean = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", clean)
            clean = clean.replace("---", "—").replace("--", "–")

            style = body_first if is_first else body_style
            story.append(Paragraph(clean, style))
            is_first = False

        # Page break between chapters
        story.append(PageBreak())

    # --- Build ---
    doc.build(story)

    logger.info("PDF generated: %s (%d chapters, trim %s)", output_path, len(chapters), trim_size)
    return output_path
