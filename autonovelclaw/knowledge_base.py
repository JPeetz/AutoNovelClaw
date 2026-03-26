"""Markdown-backed knowledge base for world codex, characters, chapters, etc.

Each category maps to a subdirectory.  Documents are stored as Markdown files
with YAML front-matter for metadata and search.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


class KnowledgeBase:
    """Simple file-backed knowledge store organised by category."""

    def __init__(self, root: Path, categories: list[str] | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        for cat in categories or []:
            (self.root / cat).mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def store(self, category: str, name: str, content: str, meta: dict[str, Any] | None = None) -> Path:
        """Store a document. Returns the file path."""
        cat_dir = self.root / category
        cat_dir.mkdir(exist_ok=True)

        safe_name = name.replace(" ", "_").replace("/", "_")
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        front_matter = ""
        if meta:
            front_matter = "---\n"
            for k, v in meta.items():
                front_matter += f"{k}: {json.dumps(v, default=str)}\n"
            front_matter += f"updated: {dt.datetime.now(dt.timezone.utc).isoformat()}\n"
            front_matter += "---\n\n"

        path = cat_dir / safe_name
        path.write_text(front_matter + content, encoding="utf-8")
        return path

    def retrieve(self, category: str, name: str) -> str | None:
        """Retrieve document content by name (without front-matter)."""
        safe_name = name.replace(" ", "_").replace("/", "_")
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        path = self.root / category / safe_name
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        # Strip YAML front-matter
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                text = text[end + 3:].lstrip("\n")
        return text

    def list_documents(self, category: str) -> list[str]:
        """List document names in a category."""
        cat_dir = self.root / category
        if not cat_dir.exists():
            return []
        return sorted(p.stem for p in cat_dir.glob("*.md"))

    def retrieve_all(self, category: str) -> dict[str, str]:
        """Retrieve all documents in a category as {name: content}."""
        result = {}
        for name in self.list_documents(category):
            content = self.retrieve(category, name)
            if content is not None:
                result[name] = content
        return result

    def delete(self, category: str, name: str) -> bool:
        """Delete a document. Returns True if it existed."""
        safe_name = name.replace(" ", "_").replace("/", "_")
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        path = self.root / category / safe_name
        if path.exists():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get_chapter_summary(self, chapter_num: int) -> str | None:
        """Retrieve a chapter summary for continuity context."""
        return self.retrieve("chapter_summaries", f"chapter_{chapter_num:02d}")

    def get_approved_chapter(self, chapter_num: int) -> str | None:
        """Retrieve an approved chapter's full text."""
        return self.retrieve("approved_chapters", f"chapter_{chapter_num:02d}")

    def get_world_codex(self) -> str:
        """Retrieve the full world codex."""
        return self.retrieve("world_codex", "codex") or ""

    def get_character_profiles(self) -> dict[str, str]:
        """Retrieve all character profiles."""
        return self.retrieve_all("characters")

    def store_lesson(self, lesson_type: str, content: str) -> Path:
        """Store a self-learning lesson."""
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.store(
            "lessons_learned",
            f"{lesson_type}_{ts}",
            content,
            meta={"type": lesson_type},
        )
