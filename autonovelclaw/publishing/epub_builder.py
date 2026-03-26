"""EPUB 3.0 builder for KDP Kindle publishing.

Generates a properly structured EPUB with:
- Cover image embedding
- NCX and EPUB 3 navigation
- Chapter-by-chapter HTML with CSS styling
- Metadata (title, author, language, identifiers)
- Table of contents
- Font embedding support
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_ebooklib():
    """Check that ebooklib is available."""
    try:
        import ebooklib  # noqa: F401
        return True
    except ImportError:
        logger.warning("ebooklib not installed — EPUB generation unavailable. pip install ebooklib")
        return False


# ---------------------------------------------------------------------------
# CSS for EPUB interior
# ---------------------------------------------------------------------------

EPUB_CSS = """\
body {
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1.6;
    margin: 1em;
    color: #1a1a1a;
}
h1 {
    font-size: 1.8em;
    text-align: center;
    margin-top: 2em;
    margin-bottom: 1em;
    page-break-before: always;
}
h2 {
    font-size: 1.4em;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}
p {
    text-indent: 1.5em;
    margin: 0.2em 0;
    text-align: justify;
}
p.first, p.no-indent {
    text-indent: 0;
}
p.scene-break {
    text-indent: 0;
    text-align: center;
    margin: 1.5em 0;
    font-size: 1.2em;
    letter-spacing: 0.5em;
}
.title-page {
    text-align: center;
    margin-top: 30%;
}
.title-page h1 {
    font-size: 2.2em;
    page-break-before: auto;
}
.title-page .subtitle {
    font-size: 1.2em;
    font-style: italic;
    margin: 0.5em 0;
}
.title-page .author {
    font-size: 1.4em;
    margin-top: 2em;
}
.copyright {
    font-size: 0.85em;
    margin-top: 3em;
    text-align: center;
}
blockquote {
    margin: 1em 2em;
    font-style: italic;
    color: #444;
}
"""


# ---------------------------------------------------------------------------
# Markdown → HTML conversion
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Convert simple markdown chapter text to HTML paragraphs.

    Handles:
    - Paragraphs (double newline separated)
    - Scene breaks (* * * or ---)
    - Bold (**text**) and italic (*text*)
    - Chapter headers (# or ##)
    """
    lines = text.split("\n\n")
    html_parts: list[str] = []
    is_first_para = True

    for block in lines:
        block = block.strip()
        if not block:
            continue

        # Scene break
        if block in ("* * *", "***", "---", "* * * *"):
            html_parts.append('<p class="scene-break">* * *</p>')
            is_first_para = True
            continue

        # Chapter header
        if block.startswith("# "):
            title = block.lstrip("#").strip()
            title = _inline_format(title)
            html_parts.append(f"<h1>{title}</h1>")
            is_first_para = True
            continue
        if block.startswith("## "):
            title = block.lstrip("#").strip()
            title = _inline_format(title)
            html_parts.append(f"<h2>{title}</h2>")
            is_first_para = True
            continue

        # Regular paragraph — handle single newlines within as line continuation
        text_block = block.replace("\n", " ")
        text_block = _inline_format(text_block)

        css_class = ' class="first"' if is_first_para else ""
        html_parts.append(f"<p{css_class}>{text_block}</p>")
        is_first_para = False

    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    """Apply inline markdown formatting (bold, italic)."""
    # Bold: **text** → <strong>text</strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic: *text* → <em>text</em> (but not ** already handled)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    # Em dash
    text = text.replace("---", "—").replace("--", "–")
    return text


# ---------------------------------------------------------------------------
# EPUB builder
# ---------------------------------------------------------------------------

def build_epub(
    *,
    title: str,
    author: str,
    chapters: dict[int, str],
    output_path: Path,
    subtitle: str = "",
    language: str = "en",
    cover_image_path: Path | None = None,
    series_name: str = "",
    series_number: int = 0,
    isbn: str = "",
    description: str = "",
    keywords: list[str] | None = None,
    copyright_text: str = "",
) -> Path:
    """Build a complete EPUB 3.0 file.

    Parameters
    ----------
    title : str
        Book title.
    author : str
        Author name.
    chapters : dict[int, str]
        Mapping of chapter number → chapter markdown text.
    output_path : Path
        Where to write the .epub file.
    subtitle, language, cover_image_path, series_name, etc.
        Optional metadata.

    Returns
    -------
    Path
        Path to the generated EPUB file.
    """
    if not _ensure_ebooklib():
        raise ImportError("ebooklib required for EPUB generation: pip install ebooklib")

    from ebooklib import epub

    book = epub.EpubBook()

    # --- Metadata ---
    book_id = isbn or f"urn:uuid:{uuid.uuid4()}"
    book.set_identifier(book_id)
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    if description:
        book.add_metadata("DC", "description", description)
    if series_name:
        book.add_metadata(None, "meta", series_name,
                          {"name": "calibre:series", "content": series_name})
        if series_number:
            book.add_metadata(None, "meta", str(series_number),
                              {"name": "calibre:series_index", "content": str(series_number)})

    # --- CSS ---
    css_item = epub.EpubItem(
        uid="style",
        file_name="style/default.css",
        media_type="text/css",
        content=EPUB_CSS.encode("utf-8"),
    )
    book.add_item(css_item)

    # --- Cover ---
    if cover_image_path and cover_image_path.exists():
        cover_data = cover_image_path.read_bytes()
        ext = cover_image_path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
        }.get(ext, "image/jpeg")

        book.set_cover("cover" + ext, cover_data)

    # --- Title page ---
    title_html = f"""<html><head><link rel="stylesheet" href="style/default.css"/></head>
<body>
<div class="title-page">
<h1>{_inline_format(title)}</h1>
{"<p class='subtitle'>" + _inline_format(subtitle) + "</p>" if subtitle else ""}
<p class="author">{_inline_format(author)}</p>
</div>
<div class="copyright">
<p>{copyright_text or f"Copyright © {author}. All rights reserved."}</p>
</div>
</body></html>"""

    title_page = epub.EpubHtml(
        title="Title Page",
        file_name="title.xhtml",
        content=title_html.encode("utf-8"),
    )
    title_page.add_item(css_item)
    book.add_item(title_page)

    # --- Chapters ---
    chapter_items: list[epub.EpubHtml] = []
    toc_entries: list[epub.Link] = []

    for ch_num in sorted(chapters.keys()):
        ch_text = chapters[ch_num]

        # Extract chapter title from first line if it's a header
        ch_title = f"Chapter {ch_num}"
        first_line = ch_text.split("\n")[0].strip()
        if first_line.startswith("#"):
            ch_title = first_line.lstrip("#").strip()

        # Convert to HTML
        ch_html_body = _md_to_html(ch_text)
        ch_html = f"""<html><head>
<link rel="stylesheet" href="style/default.css"/>
</head><body>
{ch_html_body}
</body></html>"""

        ch_item = epub.EpubHtml(
            title=ch_title,
            file_name=f"chapter_{ch_num:02d}.xhtml",
            content=ch_html.encode("utf-8"),
        )
        ch_item.add_item(css_item)
        book.add_item(ch_item)
        chapter_items.append(ch_item)
        toc_entries.append(epub.Link(
            f"chapter_{ch_num:02d}.xhtml",
            ch_title,
            f"ch{ch_num}",
        ))

    # --- Table of Contents ---
    book.toc = toc_entries

    # --- Navigation ---
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # --- Spine (reading order) ---
    book.spine = ["nav", title_page] + chapter_items

    # --- Write ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})

    logger.info("EPUB generated: %s (%d chapters)", output_path, len(chapters))
    return output_path
