"""Entity tracker — maintains a database of every named entity across chapters.

Tracks characters (names, descriptions, abilities, relationships), locations
(descriptions, distances, features), objects (descriptions, owners, states),
and events (what happened, when, where, who was involved).

The tracker builds incrementally as chapters are processed, enabling
cross-chapter consistency checking.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EntityMention:
    """A single mention of an entity in the text."""
    chapter: int
    paragraph: int  # approximate paragraph number
    context: str    # surrounding text snippet (50-100 chars)
    attribute: str  # what was said about the entity ("has blue eyes", "carries a sword")


@dataclass
class TrackedEntity:
    """A named entity tracked across the manuscript."""
    name: str
    entity_type: str  # "character", "location", "object", "faction", "creature"
    aliases: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)  # key: value pairs
    mentions: list[EntityMention] = field(default_factory=list)
    first_chapter: int = 0
    last_chapter: int = 0

    def add_mention(self, chapter: int, paragraph: int, context: str, attribute: str = "") -> None:
        self.mentions.append(EntityMention(chapter, paragraph, context, attribute))
        if self.first_chapter == 0 or chapter < self.first_chapter:
            self.first_chapter = chapter
        if chapter > self.last_chapter:
            self.last_chapter = chapter

    def set_attribute(self, key: str, value: str, chapter: int) -> str | None:
        """Set an attribute. Returns the old value if it conflicts, None if consistent."""
        existing = self.attributes.get(key)
        if existing and existing.lower().strip() != value.lower().strip():
            return existing  # Conflict detected
        self.attributes[key] = value
        return None

    @property
    def mention_count(self) -> int:
        return len(self.mentions)

    @property
    def chapter_span(self) -> int:
        if self.first_chapter == 0:
            return 0
        return self.last_chapter - self.first_chapter + 1


@dataclass
class ConsistencyIssue:
    """A consistency problem found by the tracker."""
    entity_name: str
    issue_type: str    # "attribute_conflict", "name_variant", "missing_reference", "dead_end"
    severity: str      # "error", "warning", "info"
    description: str
    chapter: int = 0
    suggestion: str = ""


class EntityTracker:
    """Maintains a cross-chapter entity database for consistency checking.

    Usage::

        tracker = EntityTracker()
        tracker.process_chapter(1, chapter_text, character_profiles, codex)
        tracker.process_chapter(2, chapter_text, character_profiles, codex)
        issues = tracker.check_consistency()
    """

    def __init__(self) -> None:
        self.entities: dict[str, TrackedEntity] = {}
        self._name_variants: dict[str, str] = {}  # lowercase variant → canonical name

    def register_entity(
        self,
        name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        attributes: dict[str, str] | None = None,
    ) -> TrackedEntity:
        """Register a known entity (e.g., from character profiles or codex)."""
        canonical = name.strip()
        entity = self.entities.get(canonical)
        if entity is None:
            entity = TrackedEntity(name=canonical, entity_type=entity_type)
            self.entities[canonical] = entity

        # Register name variants for fuzzy matching
        self._name_variants[canonical.lower()] = canonical
        if aliases:
            entity.aliases.extend(aliases)
            for alias in aliases:
                self._name_variants[alias.lower()] = canonical

        if attributes:
            for k, v in attributes.items():
                entity.set_attribute(k, v, 0)

        return entity

    def register_characters_from_profiles(self, profiles_text: str) -> int:
        """Parse character profiles and register all characters.

        Returns the number of characters registered.
        """
        count = 0
        # Look for character headers: ## Name or ### Name
        headers = re.findall(r"^#{2,3}\s+(.+?)(?:\n|$)", profiles_text, re.MULTILINE)

        for header in headers:
            name = header.strip().rstrip("#").strip()
            # Skip section headers that aren't character names
            name_lower = name.lower()
            if any(re.search(rf"\b{skip}\b", name_lower) for skip in [
                "physical", "psychology", "voice", "relationships", "arc",
                "role", "presence", "backstory",
            ]):
                continue
            if len(name) > 50 or len(name) < 2:
                continue

            self.register_entity(name, "character")
            count += 1

        return count

    def register_locations_from_codex(self, codex_text: str) -> int:
        """Extract and register location names from the world codex."""
        count = 0
        # Look for capitalised multi-word proper nouns in geography sections
        geo_section = self._extract_section(codex_text, "geography")
        if not geo_section:
            geo_section = codex_text[:3000]

        # Find capitalised proper nouns (2-4 words)
        proper_nouns = re.findall(
            r"\b([A-Z][a-z]+(?:\s+(?:of\s+)?[A-Z][a-z]+){0,3})\b",
            geo_section,
        )
        seen: set[str] = set()
        for noun in proper_nouns:
            if noun.lower() in seen or len(noun) < 4:
                continue
            seen.add(noun.lower())
            # Skip common non-location words
            if noun.lower() in {"the", "this", "that", "these", "their", "there"}:
                continue
            self.register_entity(noun, "location")
            count += 1

        return count

    def process_chapter(
        self,
        chapter_num: int,
        chapter_text: str,
    ) -> list[ConsistencyIssue]:
        """Process a chapter, updating entity mentions and checking for issues.

        Returns a list of issues found during processing.
        """
        issues: list[ConsistencyIssue] = []
        paragraphs = chapter_text.split("\n\n")

        for para_idx, paragraph in enumerate(paragraphs):
            if not paragraph.strip():
                continue

            # Check each known entity for mentions
            for canonical, entity in self.entities.items():
                names_to_check = [entity.name] + entity.aliases
                for name in names_to_check:
                    # Find ALL occurrences in the paragraph
                    para_lower = paragraph.lower()
                    name_lower = name.lower()
                    search_start = 0
                    while True:
                        idx = para_lower.find(name_lower, search_start)
                        if idx == -1:
                            break
                        start = max(0, idx - 40)
                        end = min(len(paragraph), idx + len(name) + 40)
                        context = paragraph[start:end].strip()
                        entity.add_mention(chapter_num, para_idx, context)
                        search_start = idx + len(name_lower)

            # Check for potential new entities not yet tracked
            # (capitalised proper nouns not in our database)
            new_proper_nouns = re.findall(
                r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b",
                paragraph,
            )
            for noun in new_proper_nouns:
                if (noun.lower() not in self._name_variants
                        and not self._is_common_word(noun)
                        and len(noun) > 3):
                    # Potential untracked entity
                    issues.append(ConsistencyIssue(
                        entity_name=noun,
                        issue_type="untracked_entity",
                        severity="info",
                        description=f"Potential new entity '{noun}' in chapter {chapter_num} "
                                    f"not found in character profiles or codex",
                        chapter=chapter_num,
                        suggestion=f"Consider adding '{noun}' to character profiles or codex",
                    ))

        return issues

    def check_consistency(self) -> list[ConsistencyIssue]:
        """Run all consistency checks across tracked entities.

        Returns a comprehensive list of issues.
        """
        issues: list[ConsistencyIssue] = []
        issues.extend(self._check_name_variants())
        issues.extend(self._check_disappearances())
        issues.extend(self._check_attribute_conflicts())
        return issues

    def _check_name_variants(self) -> list[ConsistencyIssue]:
        """Check for inconsistent name spelling/capitalisation."""
        issues: list[ConsistencyIssue] = []

        for entity in self.entities.values():
            # Collect all mentioned forms of this entity's name
            mentioned_forms: dict[str, int] = {}
            for mention in entity.mentions:
                # Extract the exact form used in context
                for name in [entity.name] + entity.aliases:
                    if name.lower() in mention.context.lower():
                        # Find the exact form in context
                        idx = mention.context.lower().find(name.lower())
                        exact = mention.context[idx:idx + len(name)]
                        mentioned_forms[exact] = mentioned_forms.get(exact, 0) + 1

            # Check for variant forms
            if len(mentioned_forms) > 1:
                forms_str = ", ".join(f"'{f}' ({c}×)" for f, c in
                                       sorted(mentioned_forms.items(), key=lambda x: -x[1]))
                most_common = max(mentioned_forms, key=mentioned_forms.get)  # type: ignore
                if any(f != most_common for f in mentioned_forms):
                    issues.append(ConsistencyIssue(
                        entity_name=entity.name,
                        issue_type="name_variant",
                        severity="warning",
                        description=f"Name variants detected: {forms_str}",
                        suggestion=f"Standardise to '{most_common}' throughout",
                    ))

        return issues

    def _check_disappearances(self) -> list[ConsistencyIssue]:
        """Check for characters who appear then vanish without resolution."""
        issues: list[ConsistencyIssue] = []

        for entity in self.entities.values():
            if entity.entity_type != "character":
                continue
            if entity.mention_count < 2:
                continue

            # Check for large gaps in chapter mentions
            mentioned_chapters = sorted(set(m.chapter for m in entity.mentions))
            if len(mentioned_chapters) < 2:
                continue

            for i in range(len(mentioned_chapters) - 1):
                gap = mentioned_chapters[i + 1] - mentioned_chapters[i]
                if gap > 3:  # More than 3 chapters without mention
                    issues.append(ConsistencyIssue(
                        entity_name=entity.name,
                        issue_type="character_gap",
                        severity="info",
                        description=(
                            f"'{entity.name}' appears in chapter {mentioned_chapters[i]} "
                            f"then not again until chapter {mentioned_chapters[i + 1]} "
                            f"({gap} chapter gap)"
                        ),
                        chapter=mentioned_chapters[i],
                        suggestion="Consider mentioning or referencing this character "
                                   "in intervening chapters, or explain their absence",
                    ))

        return issues

    def _check_attribute_conflicts(self) -> list[ConsistencyIssue]:
        """Check for conflicting attributes (e.g., eye colour changes)."""
        issues: list[ConsistencyIssue] = []

        for entity in self.entities.values():
            # Look for physical descriptions that change
            # This requires attribute extraction from text, which is done
            # during process_chapter. For now, check registered attributes.
            for key, value in entity.attributes.items():
                if not value:
                    continue
                # Check if mentions contain contradictory descriptions
                for mention in entity.mentions:
                    context_lower = mention.context.lower()
                    if key.lower() in context_lower:
                        # There's a description of this attribute — check it
                        if value.lower() not in context_lower:
                            issues.append(ConsistencyIssue(
                                entity_name=entity.name,
                                issue_type="attribute_conflict",
                                severity="warning",
                                description=(
                                    f"'{entity.name}' attribute '{key}' may conflict: "
                                    f"registered as '{value}', but chapter {mention.chapter} "
                                    f"context: '{mention.context[:60]}'"
                                ),
                                chapter=mention.chapter,
                                suggestion=f"Verify '{key}' is consistent for '{entity.name}'",
                            ))

        return issues

    def _extract_section(self, text: str, section_name: str) -> str:
        """Extract a named section from a document."""
        pattern = rf"(?i)(?:^|\n)##?\s*(?:\d+\.)?\s*{section_name}.*?\n(.*?)(?=\n##?\s|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _is_common_word(self, word: str) -> bool:
        """Check if a word is a common English word (not a proper noun)."""
        common = {
            "the", "and", "but", "for", "not", "you", "all", "can", "her",
            "was", "one", "our", "out", "are", "has", "his", "how", "its",
            "may", "new", "now", "old", "see", "way", "who", "did", "get",
            "let", "say", "she", "too", "use", "had", "each", "make",
            "like", "long", "look", "many", "some", "them", "than", "been",
            "call", "come", "could", "into", "just", "know", "more", "much",
            "only", "over", "such", "take", "than", "that", "them", "then",
            "these", "they", "this", "time", "very", "when", "which", "with",
            "would", "about", "after", "could", "every", "first", "found",
            "great", "house", "large", "later", "never", "other", "place",
            "point", "right", "small", "still", "think", "three", "under",
            "water", "where", "world", "young", "before", "between",
            "chapter", "through", "another", "because", "without",
            "something", "everything", "nothing", "himself", "herself",
        }
        return word.lower() in common

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Save the entity database to JSON."""
        data = {
            name: {
                "name": e.name,
                "entity_type": e.entity_type,
                "aliases": e.aliases,
                "attributes": e.attributes,
                "first_chapter": e.first_chapter,
                "last_chapter": e.last_chapter,
                "mention_count": e.mention_count,
            }
            for name, e in self.entities.items()
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, path: Path) -> None:
        """Load the entity database from JSON."""
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, edata in data.items():
            entity = TrackedEntity(
                name=edata["name"],
                entity_type=edata["entity_type"],
                aliases=edata.get("aliases", []),
                attributes=edata.get("attributes", {}),
                first_chapter=edata.get("first_chapter", 0),
                last_chapter=edata.get("last_chapter", 0),
            )
            self.entities[name] = entity
            self._name_variants[name.lower()] = name
            for alias in entity.aliases:
                self._name_variants[alias.lower()] = name

    def summary(self) -> str:
        """Generate a human-readable summary of tracked entities."""
        lines = [f"# Entity Tracker Summary — {len(self.entities)} entities\n"]
        by_type: dict[str, list[TrackedEntity]] = {}
        for e in self.entities.values():
            by_type.setdefault(e.entity_type, []).append(e)

        for etype, entities in sorted(by_type.items()):
            lines.append(f"\n## {etype.title()} ({len(entities)})")
            for e in sorted(entities, key=lambda x: -x.mention_count):
                chapters = f"ch{e.first_chapter}"
                if e.last_chapter > e.first_chapter:
                    chapters += f"–{e.last_chapter}"
                lines.append(
                    f"  - **{e.name}** ({e.mention_count} mentions, {chapters})"
                )
                if e.aliases:
                    lines.append(f"    Aliases: {', '.join(e.aliases)}")

        return "\n".join(lines)
