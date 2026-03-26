"""Stage executor — all 30 stage implementations.

Each ``_execute_*`` function receives the shared execution context and performs
the actual work for one pipeline stage.  The public ``execute_stage()`` function
dispatches to the correct handler.

Execution context (passed to every handler):
  - config: NovelClawConfig
  - llm: BaseLLMClient
  - ckpt: Checkpoint
  - kb: KnowledgeBase
  - prompts: PromptManager
  - run_dir: Path
  - auto_approve: bool
"""

from __future__ import annotations

import json
import logging
import re
import time as _time
from pathlib import Path
from typing import Any

from autonovelclaw.config import NovelClawConfig
from autonovelclaw.knowledge_base import KnowledgeBase
from autonovelclaw.llm import AgentRole
from autonovelclaw.llm.client import BaseLLMClient
from autonovelclaw.prompts import PromptManager
from autonovelclaw.pipeline.runner import Checkpoint
from autonovelclaw.pipeline.stages import Stage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_text(run_dir: Path, filename: str, content: str, subdir: str = "") -> Path:
    """Write a text artifact to the run directory."""
    base = run_dir / subdir if subdir else run_dir
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    path.write_text(content, encoding="utf-8")
    return path


def _word_count(text: str) -> int:
    return len(text.split())


def _extract_rating(text: str, default: float = 7.0) -> float:
    """Extract a numeric X.X/10 rating from review text."""
    patterns = [
        r"OVERALL\s*RATING:\s*(\d+\.?\d*)\s*/\s*10",
        r"ENGAGEMENT\s*RATING:\s*(\d+\.?\d*)\s*/\s*10",
        r"RATING:\s*(\d+\.?\d*)\s*/\s*10",
        r"(\d+\.?\d*)\s*/\s*10",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if 0 <= val <= 10:
                return val
    logger.warning("Could not extract rating from review — using default %.1f", default)
    return default


def _extract_chapter_section(full_text: str, chapter_num: int) -> str:
    """Extract a specific chapter's section from a multi-chapter document."""
    patterns = [
        rf"(?s)##\s*Chapter\s*{chapter_num}\b(.*?)(?=##\s*Chapter\s*{chapter_num + 1}\b|$)",
        rf"(?s)##\s*{chapter_num}\.\s(.*?)(?=##\s*{chapter_num + 1}\.\s|$)",
    ]
    for pat in patterns:
        match = re.search(pat, full_text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    # Fallback: return a chunk proportional to chapter count
    lines = full_text.split("\n")
    total_chapters = max(1, len(re.findall(r"##\s*Chapter\s*\d+", full_text, re.IGNORECASE)))
    chunk_size = max(50, len(lines) // total_chapters)
    start = (chapter_num - 1) * chunk_size
    end = min(start + chunk_size, len(lines))
    return "\n".join(lines[start:end])


def _truncate(text: str, max_chars: int = 4000) -> str:
    """Truncate text to fit context windows, cutting at paragraph boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_para = cut.rfind("\n\n")
    if last_para > max_chars * 0.7:
        return cut[:last_para] + "\n\n[... truncated for context ...]"
    return cut + "\n\n[... truncated for context ...]"


# ---------------------------------------------------------------------------
# Execution context (passed to all handlers)
# ---------------------------------------------------------------------------

class _Ctx:
    """Bundle of shared execution context."""
    __slots__ = ("config", "llm", "ckpt", "kb", "prompts", "run_dir", "auto_approve")

    def __init__(
        self,
        config: NovelClawConfig,
        llm: BaseLLMClient,
        ckpt: Checkpoint,
        kb: KnowledgeBase,
        prompts: PromptManager,
        run_dir: Path,
        auto_approve: bool,
    ) -> None:
        self.config = config
        self.llm = llm
        self.ckpt = ckpt
        self.kb = kb
        self.prompts = prompts
        self.run_dir = run_dir
        self.auto_approve = auto_approve

    @property
    def ch(self) -> int:
        """Current chapter number."""
        return self.ckpt.current_chapter

    def genre(self) -> str:
        return self.config.novel.genre.primary or "fiction"

    def genre_overlay(self) -> str:
        return self.prompts.get_genre_overlay(self.genre())

    def sensory_vars(self) -> dict[str, str]:
        s = self.config.writing.sensory_targets
        return {
            "sensory_visual": f"{s.visual:.0%}",
            "sensory_kinesthetic": f"{s.kinesthetic:.0%}",
            "sensory_olfactory": f"{s.olfactory:.0%}",
            "sensory_auditory": f"{s.auditory:.0%}",
            "sensory_gustatory": f"{s.gustatory:.0%}",
        }

    def chapter_vars(self) -> dict[str, str]:
        t = self.config.novel.target
        return {
            "wpc_min": str(t.words_per_chapter_min),
            "wpc_max": str(t.words_per_chapter_max),
            "pov": self.config.writing.pov,
            "tense": self.config.writing.tense,
        }


# ===================================================================
# PHASE 0: IDEATION
# ===================================================================

def _execute_idea_intake(ctx: _Ctx) -> None:
    """Stage 0: Parse the user's raw concept into structured elements."""
    topic = ctx.ckpt.get_artifact("raw_topic", "")
    if not topic:
        raise ValueError("No topic provided. Set --topic or config novel.title.")

    rp = ctx.prompts.for_stage("idea_intake", topic=topic)

    resp = ctx.llm.complete(
        role=AgentRole.IDEATION,
        system_prompt=rp.system,
        user_message=rp.user,
        json_mode=rp.json_mode,
        max_tokens=rp.max_tokens,
    )

    # Parse JSON response
    try:
        raw = resp.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for idea intake — storing raw text")
        parsed = {"raw_analysis": resp.text, "core_elements": [topic]}

    ctx.ckpt.store_artifact("parsed_concept", parsed)
    _save_text(ctx.run_dir, "parsed_concept.json", json.dumps(parsed, indent=2))
    logger.info("Idea parsed: genre=%s, tone=%s",
                parsed.get("implied_genre", "?"), parsed.get("implied_tone", "?"))


def _execute_storyline_generation(ctx: _Ctx) -> None:
    """Stage 1: Generate N distinct storylines from the parsed concept."""
    parsed = ctx.ckpt.get_artifact("parsed_concept", {})
    count = ctx.config.ideation.storyline_count

    rp = ctx.prompts.for_stage(
        "storyline_generation",
        storyline_count=str(count),
        parsed_concept=json.dumps(parsed, indent=2) if isinstance(parsed, dict) else str(parsed),
    )

    resp = ctx.llm.complete(
        role=AgentRole.IDEATION,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    ctx.ckpt.store_artifact("storylines_raw", resp.text)
    _save_text(ctx.run_dir, "storylines.md", resp.text)

    # Parse individual storylines
    storylines = _parse_storylines(resp.text, count)
    ctx.ckpt.store_artifact("storylines_parsed", storylines)
    _save_text(ctx.run_dir, "storylines_parsed.json", json.dumps(storylines, indent=2))
    logger.info("Generated %d storylines", len(storylines))


def _parse_storylines(text: str, expected: int) -> list[dict[str, str]]:
    """Best-effort parse of storyline blocks from LLM output."""
    storylines: list[dict[str, str]] = []
    # Split on ## STORYLINE or ## Storyline headers
    blocks = re.split(r"(?=##\s*STORYLINE\s*\d|##\s*Storyline\s*\d|##\s*\d+[\.\)]\s)", text)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 100:
            continue

        title_match = re.search(r"\*\*TITLE:\*\*\s*(.+)", block)
        logline_match = re.search(r"\*\*LOGLINE:\*\*\s*(.+)", block)
        genre_match = re.search(r"\*\*GENRE:\*\*\s*(.+)", block)
        standalone_match = re.search(r"Standalone\s*viability:\s*(HIGH|MEDIUM|LOW)", block, re.IGNORECASE)

        storylines.append({
            "number": str(len(storylines) + 1),
            "title": title_match.group(1).strip() if title_match else f"Storyline {len(storylines) + 1}",
            "logline": logline_match.group(1).strip() if logline_match else "",
            "genre": genre_match.group(1).strip() if genre_match else "",
            "standalone_viability": standalone_match.group(1).upper() if standalone_match else "MEDIUM",
            "full_text": block,
        })

    return storylines[:expected]


def _execute_selection_and_scope(ctx: _Ctx) -> None:
    """Stage 2: User selects a storyline and elaborates before automation.

    This stage ALWAYS prompts the user — even in auto-approve mode.
    This is the creative handshake: the user picks their preferred
    storyline, can modify/elaborate on it, and then full automation
    takes over from world-building onwards.
    """
    storylines = ctx.ckpt.get_artifact("storylines_parsed", [])

    if not storylines:
        raise RuntimeError("No storylines generated — check Stage 1 output")

    from rich.console import Console
    con = Console()

    # --- Step 1: Present storylines for selection ---
    con.print("\n[bold cyan]╔══════════════════════════════════════════╗[/]")
    con.print("[bold cyan]║       CHOOSE YOUR STORYLINE              ║[/]")
    con.print("[bold cyan]╚══════════════════════════════════════════╝[/]\n")

    for sl in storylines:
        con.print(f"  [bold yellow]{sl.get('number', '?')}.[/] [bold]{sl.get('title', 'Untitled')}[/]")
        if sl.get("logline"):
            con.print(f"     {sl['logline']}")
        if sl.get("genre"):
            con.print(f"     [dim]Genre: {sl['genre']}[/]")
        con.print()

    con.print(f"  [dim]Full details saved in: storylines.md[/]\n")

    while True:
        choice = input(f"  Which storyline? (1-{len(storylines)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(storylines):
            selected = storylines[int(choice) - 1]
            break
        con.print("  [red]Enter a number from the list above.[/]")

    con.print(f"\n  [green]Selected:[/] [bold]{selected.get('title', 'Untitled')}[/]\n")

    # --- Step 2: Let user elaborate, modify, or add details ---
    con.print("[bold cyan]═══ MAKE IT YOURS ═══[/]\n")
    con.print("  Now's your chance to shape the story before automation takes over.")
    con.print("  You can:")
    con.print("    • Change character names, settings, or relationships")
    con.print("    • Add plot elements, twists, or themes")
    con.print("    • Specify the tone, target audience, or ending")
    con.print("    • Request specific scenes or emotional beats")
    con.print("    • Or just press Enter to proceed as-is\n")

    elaboration = input("  Your additions/changes (or Enter to skip):\n  > ").strip()

    if elaboration:
        # Append user elaboration to the storyline
        selected["user_elaboration"] = elaboration
        original_text = selected.get("full_text", "")
        selected["full_text"] = (
            f"{original_text}\n\n"
            f"## USER DIRECTION\n\n"
            f"{elaboration}\n"
        )
        con.print(f"\n  [green]✓ Your direction has been added to the storyline.[/]")

        # If elaboration is substantial, offer a second pass
        if len(elaboration) > 50:
            more = input("  Anything else? (or Enter to proceed): ").strip()
            if more:
                selected["user_elaboration"] += f"\n{more}"
                selected["full_text"] += f"\n{more}\n"
                con.print(f"  [green]✓ Added.[/]")
    else:
        con.print(f"  [dim]Proceeding with storyline as generated.[/]")

    # --- Step 3: Scope selection ---
    con.print()
    scope_choice = input("  Standalone novel or series? (standalone/series): ").strip().lower()
    scope = "series" if "series" in scope_choice else "standalone"

    if scope == "series":
        book_count = input("  How many books? (2-12): ").strip()
        book_count_int = int(book_count) if book_count.isdigit() and 2 <= int(book_count) <= 12 else 4
        ctx.ckpt.store_artifact("series_book_count", book_count_int)

    # --- Confirm and hand off to automation ---
    con.print(f"\n[bold green]═══ AUTOMATION ENGAGED ═══[/]")
    con.print(f"  Title: [bold]{selected.get('title', 'Untitled')}[/]")
    con.print(f"  Scope: {scope}")
    if elaboration:
        con.print(f"  Your direction: [italic]{elaboration[:100]}{'...' if len(elaboration) > 100 else ''}[/]")
    con.print(f"\n  [dim]From here, the pipeline runs autonomously.")
    con.print(f"  You'll be notified at review stages and if anything goes wrong.[/]\n")

    ctx.ckpt.store_artifact("selected_storyline", selected)
    ctx.ckpt.store_artifact("novel_scope", scope)

    if selected.get("title"):
        ctx.config.novel.title = selected["title"]

    _save_text(ctx.run_dir, "selected_storyline.md",
               selected.get("full_text", json.dumps(selected, indent=2)))
    logger.info("Selected: %s (%s)%s", selected.get("title"), scope,
                f" + user elaboration ({len(elaboration)} chars)" if elaboration else "")


def _execute_series_arc_design(ctx: _Ctx) -> None:
    """Stage 3: Design the multi-book series arc (skipped for standalone)."""
    selected = ctx.ckpt.get_artifact("selected_storyline", {})
    book_count = ctx.ckpt.get_artifact("series_book_count", 4)

    selected_text = selected.get("full_text", json.dumps(selected, indent=2)) if isinstance(selected, dict) else str(selected)

    rp = ctx.prompts.for_stage(
        "series_arc_design",
        book_count=str(book_count),
        selected_storyline=_truncate(selected_text, 3000),
    )

    resp = ctx.llm.complete(
        role=AgentRole.IDEATION,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    ctx.ckpt.store_artifact("series_arc", resp.text)
    _save_text(ctx.run_dir, "series_arc.md", resp.text)
    ctx.kb.store("world_codex", "series_arc", resp.text, meta={"type": "series_arc"})
    logger.info("Series arc designed for %d books", book_count)


# ===================================================================
# PHASE A: WORLD-BUILDING
# ===================================================================

def _execute_codex_generation(ctx: _Ctx) -> None:
    """Stage 4: Generate a comprehensive world codex."""
    selected = ctx.ckpt.get_artifact("selected_storyline", {})
    series_arc = ctx.ckpt.get_artifact("series_arc", "")

    selected_text = selected.get("full_text", json.dumps(selected, indent=2)) if isinstance(selected, dict) else str(selected)

    series_context = f"SERIES ARC:\n{_truncate(series_arc, 2000)}" if series_arc else "Standalone novel."

    rp = ctx.prompts.for_stage(
        "codex_generation",
        selected_storyline=_truncate(selected_text, 3000),
        series_context=series_context,
        **ctx.sensory_vars(),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    # Validate: codex should be substantial
    wc = _word_count(resp.text)
    if wc < 1000:
        logger.warning("World codex seems thin (%d words) — consider regenerating", wc)

    ctx.kb.store("world_codex", "codex", resp.text, meta={"type": "world_codex", "words": wc})
    ctx.ckpt.store_artifact("world_codex_generated", True)
    _save_text(ctx.run_dir, "world_codex.md", resp.text, subdir="world")
    logger.info("World codex generated: %d words", wc)


def _execute_character_creation(ctx: _Ctx) -> None:
    """Stage 5: Create detailed character profiles."""
    selected = ctx.ckpt.get_artifact("selected_storyline", {})
    codex = ctx.kb.get_world_codex()

    selected_text = selected.get("full_text", json.dumps(selected, indent=2)) if isinstance(selected, dict) else str(selected)

    rp = ctx.prompts.for_stage(
        "character_creation",
        selected_storyline=_truncate(selected_text, 2000),
        codex_excerpt=_truncate(codex, 3000),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    wc = _word_count(resp.text)
    ctx.kb.store("characters", "all_profiles", resp.text, meta={"type": "characters", "words": wc})
    ctx.ckpt.store_artifact("characters_generated", True)
    _save_text(ctx.run_dir, "character_profiles.md", resp.text, subdir="world")
    logger.info("Character profiles generated: %d words", wc)


def _execute_system_design(ctx: _Ctx) -> None:
    """Stage 6: Design the magic/technology system."""
    selected = ctx.ckpt.get_artifact("selected_storyline", {})
    codex = ctx.kb.get_world_codex()
    genre = ctx.genre()

    system_type = "magic" if "fantasy" in genre.lower() else "technology"

    selected_text = selected.get("full_text", json.dumps(selected, indent=2)) if isinstance(selected, dict) else str(selected)

    rp = ctx.prompts.for_stage(
        "system_design",
        system_type=system_type,
        selected_storyline=_truncate(selected_text, 2000),
        codex_excerpt=_truncate(codex, 2000),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 4096,
    )

    ctx.kb.store("world_codex", f"{system_type}_system", resp.text, meta={"type": system_type})
    ctx.ckpt.store_artifact("system_designed", True)
    ctx.ckpt.store_artifact("system_type", system_type)
    _save_text(ctx.run_dir, f"{system_type}_system.md", resp.text, subdir="world")
    logger.info("%s system designed: %d words", system_type, _word_count(resp.text))


def _execute_world_validation(ctx: _Ctx) -> None:
    """Stage 7: Gate — user reviews and approves the world."""
    if ctx.auto_approve:
        logger.info("World auto-approved")
        return

    from rich.console import Console
    con = Console()
    con.print("\n[bold cyan]═══ WORLD VALIDATION ═══[/]")
    con.print("[yellow]Review world/ directory:[/]")
    for f in sorted((ctx.run_dir / "world").glob("*.md")):
        wc = _word_count(f.read_text(encoding="utf-8"))
        con.print(f"  • {f.name} ({wc:,} words)")
    con.print("\n[yellow]Type 'approve' to continue or 'reject' to regenerate:[/]")
    response = input("  > ").strip().lower()
    if response != "approve":
        raise RuntimeError("World rejected by user — regeneration needed")
    logger.info("World approved by user")


# ===================================================================
# PHASE B: STORY ARCHITECTURE
# ===================================================================

def _execute_book_outline(ctx: _Ctx) -> None:
    """Stage 8: Generate chapter-by-chapter outline."""
    selected = ctx.ckpt.get_artifact("selected_storyline", {})
    series_arc = ctx.ckpt.get_artifact("series_arc", "")
    codex = ctx.kb.get_world_codex()
    characters = ctx.kb.retrieve("characters", "all_profiles") or ""

    t = ctx.config.novel.target
    selected_text = selected.get("full_text", json.dumps(selected, indent=2)) if isinstance(selected, dict) else str(selected)

    series_context = f"SERIES ARC:\n{_truncate(series_arc, 2000)}" if series_arc else ""

    rp = ctx.prompts.for_stage(
        "book_outline",
        selected_storyline=_truncate(selected_text, 2000),
        series_context=series_context,
        codex_excerpt=_truncate(codex, 2000),
        characters_excerpt=_truncate(characters, 2000),
        ch_min=str(t.chapter_count_min),
        ch_max=str(t.chapter_count_max),
        wpc_min=str(t.words_per_chapter_min),
        wpc_max=str(t.words_per_chapter_max),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    # Count chapters in the outline
    chapter_count = len(re.findall(r"##\s*Chapter\s*\d+", resp.text, re.IGNORECASE))
    if chapter_count < t.chapter_count_min:
        chapter_count = t.chapter_count_min
    if chapter_count > t.chapter_count_max:
        chapter_count = t.chapter_count_max

    ctx.ckpt.store_artifact("book_outline", resp.text)
    ctx.ckpt.total_chapters = chapter_count
    ctx.ckpt.save()

    ctx.kb.store("world_codex", "book_outline", resp.text, meta={"type": "outline", "chapters": chapter_count})
    _save_text(ctx.run_dir, "book_outline.md", resp.text)
    logger.info("Outline generated: %d chapters, %d words", chapter_count, _word_count(resp.text))


def _execute_chapter_beat_sheets(ctx: _Ctx) -> None:
    """Stage 9: Generate detailed beat sheets for each chapter."""
    outline = ctx.ckpt.get_artifact("book_outline", "")
    codex = ctx.kb.get_world_codex()
    total = ctx.ckpt.total_chapters

    rp = ctx.prompts.for_stage(
        "chapter_beat_sheets",
        total_chapters=str(total),
        outline_excerpt=_truncate(outline, 4000),
        codex_excerpt=_truncate(codex, 1500),
        **ctx.sensory_vars(),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    ctx.ckpt.store_artifact("beat_sheets", resp.text)
    ctx.kb.store("world_codex", "beat_sheets", resp.text, meta={"type": "beats"})
    _save_text(ctx.run_dir, "beat_sheets.md", resp.text)
    logger.info("Beat sheets generated for %d chapters: %d words", total, _word_count(resp.text))


def _execute_outline_review(ctx: _Ctx) -> None:
    """Stage 10: Gate — user reviews and approves the outline."""
    if ctx.auto_approve:
        logger.info("Outline auto-approved")
        return

    from rich.console import Console
    con = Console()
    con.print("\n[bold cyan]═══ OUTLINE REVIEW ═══[/]")
    con.print(f"[yellow]Review: book_outline.md + beat_sheets.md[/]")
    con.print(f"  Chapters: {ctx.ckpt.total_chapters}")
    con.print("\n[yellow]Type 'approve' to begin writing or 'reject' to revise:[/]")
    response = input("  > ").strip().lower()
    if response != "approve":
        raise RuntimeError("Outline rejected — revision needed")
    logger.info("Outline approved by user")


# ===================================================================
# PHASE C: CHAPTER WRITING
# ===================================================================

def _execute_scene_planning(ctx: _Ctx) -> None:
    """Stage 11: Expand beat sheet into prose-ready scene plan."""
    ch = ctx.ch
    beat_sheets = ctx.ckpt.get_artifact("beat_sheets", "")
    outline = ctx.ckpt.get_artifact("book_outline", "")

    chapter_beats = _extract_chapter_section(beat_sheets, ch)
    chapter_outline = _extract_chapter_section(outline, ch)

    rp = ctx.prompts.for_stage(
        "scene_planning",
        chapter_num=str(ch),
        chapter_beats=_truncate(chapter_beats, 3000),
        chapter_outline=_truncate(chapter_outline, 2000),
        **ctx.sensory_vars(),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 4096,
    )

    ctx.ckpt.store_artifact(f"scene_plan_ch{ch}", resp.text)
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_scene_plan.md", resp.text, subdir="chapters")
    logger.info("Scene plan for chapter %d: %d words", ch, _word_count(resp.text))


def _execute_chapter_draft(ctx: _Ctx) -> None:
    """Stage 12: The Writer Agent writes the full chapter.

    Uses the chapter/context module for smart context window budgeting
    and the evolution system for lessons-learned overlay.
    """
    from autonovelclaw.chapter.context import assemble_writer_context

    ch = ctx.ch
    scene_plan = ctx.ckpt.get_artifact(f"scene_plan_ch{ch}", "")
    codex = ctx.kb.get_world_codex()
    characters = ctx.kb.retrieve("characters", "all_profiles") or ""
    outline = ctx.ckpt.get_artifact("book_outline", "")

    # Build chapter summaries dict for rolling context
    chapter_summaries: dict[int, str] = {}
    for prev_ch in range(1, ch):
        s = ctx.kb.get_chapter_summary(prev_ch)
        if s:
            chapter_summaries[prev_ch] = s

    # Evolution overlay (lessons from prior chapters/runs)
    lessons_overlay = ""
    evo_dir = ctx.run_dir / "evolution"
    if evo_dir.exists():
        from autonovelclaw.evolution import EvolutionStore
        store = EvolutionStore(evo_dir)
        lessons_overlay = store.build_overlay("chapter_draft", max_lessons=5)

    # Fallback: KB lessons
    if not lessons_overlay:
        lesson_docs = ctx.kb.retrieve_all("lessons_learned")
        if lesson_docs:
            recent = list(lesson_docs.values())[-5:]
            lessons_overlay = "## LESSONS FROM PREVIOUS CHAPTERS\n\n" + "\n\n".join(recent)

    # Smart context assembly with budget management
    assembled = assemble_writer_context(
        codex=codex,
        characters=characters,
        scene_plan=scene_plan,
        chapter_summaries=chapter_summaries,
        current_chapter=ch,
        lessons_overlay=lessons_overlay,
        genre_overlay=ctx.genre_overlay(),
        location_hint=_extract_chapter_section(outline, ch)[:200],
    )

    # Extract chapter title from outline
    ch_section = _extract_chapter_section(outline, ch)
    title_match = re.search(r"Chapter\s*\d+:\s*(.+)", ch_section)
    ch_title = title_match.group(1).strip() if title_match else f"Chapter {ch}"

    rp = ctx.prompts.for_stage(
        "chapter_draft",
        genre_overlay=assembled.genre_overlay,
        codex_excerpt=assembled.codex_excerpt,
        characters_excerpt=assembled.characters_excerpt,
        previous_summary=assembled.previous_summary,
        lessons_overlay=assembled.lessons_overlay,
        chapter_num=str(ch),
        chapter_title=ch_title,
        scene_plan=assembled.scene_plan,
        **ctx.sensory_vars(),
        **ctx.chapter_vars(),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    wc = _word_count(resp.text)
    min_wc = ctx.config.novel.target.words_per_chapter_min

    if wc < min_wc * 0.5:
        logger.warning(
            "Chapter %d draft very short (%d words, target %d) — may need rewrite",
            ch, wc, min_wc,
        )

    ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", resp.text)
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_draft.md", resp.text, subdir="chapters")

    # Generate continuity summary
    _generate_chapter_summary(ctx, ch, resp.text)

    logger.info("Chapter %d drafted: %d words (target: %d-%d)",
                ch, wc, min_wc, ctx.config.novel.target.words_per_chapter_max)


def _generate_chapter_summary(ctx: _Ctx, ch: int, chapter_text: str) -> None:
    """Generate a brief summary for continuity across chapters."""
    rp = ctx.prompts.for_stage(
        "chapter_summary",
        chapter_text=_truncate(chapter_text, 6000),
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 512,
    )

    ctx.kb.store("chapter_summaries", f"chapter_{ch:02d}", resp.text,
                 meta={"chapter": ch, "type": "summary"})


def _execute_sensory_enhancement(ctx: _Ctx) -> None:
    """Stage 13: Dedicated sensory immersion enhancement pass.

    Uses the sensory auditor to identify exactly WHERE enhancement is needed,
    then passes gap analysis to the LLM for targeted fixes.
    """
    from autonovelclaw.chapter.sensory_auditor import audit_chapter_sensory

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")

    # Audit current sensory density
    targets = {
        "visual": ctx.config.writing.sensory_targets.visual,
        "kinesthetic": ctx.config.writing.sensory_targets.kinesthetic,
        "olfactory": ctx.config.writing.sensory_targets.olfactory,
        "auditory": ctx.config.writing.sensory_targets.auditory,
        "gustatory": ctx.config.writing.sensory_targets.gustatory,
    }
    audit = audit_chapter_sensory(draft, targets=targets)

    # Save audit report
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_sensory_audit.md",
               audit.to_markdown(), subdir="reviews")

    # If already meets targets, skip LLM call
    if audit.meets_targets:
        logger.info("Chapter %d sensory audit: meets targets — skipping enhancement", ch)
        _save_text(ctx.run_dir, f"chapter_{ch:02d}_enhanced.md", draft, subdir="chapters")
        return

    # Build gap-specific instructions for the LLM
    gaps = audit.gap_analysis()
    gap_instructions = []
    for sense, gap in sorted(gaps.items(), key=lambda x: x[1]):
        if gap < -0.05:
            gap_instructions.append(f"- {sense.upper()}: {gap:+.0%} below target — ADD more {sense} detail")

    weak_paras = audit.weakest_paragraphs(5)
    weak_locations = ""
    if weak_paras:
        weak_locations = "PRIORITY PARAGRAPHS (sensory deserts):\n"
        for p in weak_paras:
            weak_locations += f"- Paragraph {p.paragraph_index}: {p.word_count} words, only {p.sense_count} senses\n"

    rp = ctx.prompts.for_stage(
        "sensory_enhancement",
        chapter_text=draft,
        **ctx.sensory_vars(),
    )

    # Inject gap analysis into the user prompt
    enhanced_user = rp.user + (
        f"\n\nSENSORY GAP ANALYSIS:\n"
        f"Current 2+ senses ratio: {audit.actual_2plus_ratio:.0%} (target: 65%)\n"
        f"Sensory deserts: {audit.sensory_deserts} paragraphs\n\n"
        f"{''.join(gap_instructions)}\n\n"
        f"{weak_locations}"
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=enhanced_user,
        max_tokens=rp.max_tokens or 8192,
    )

    old_wc = _word_count(draft)
    new_wc = _word_count(resp.text)
    delta_pct = ((new_wc - old_wc) / max(old_wc, 1)) * 100

    if delta_pct > 10:
        logger.warning("Sensory enhancement added %.1f%% — above 5%% target", delta_pct)

    ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", resp.text)
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_enhanced.md", resp.text, subdir="chapters")
    logger.info("Chapter %d sensory-enhanced: %d → %d words (+%.1f%%)", ch, old_wc, new_wc, delta_pct)


# ===================================================================
# PHASE D: STYLE VERIFICATION
# ===================================================================

def _execute_voice_consistency(ctx: _Ctx) -> None:
    """Stage 14: Check and fix voice consistency.

    Pre-scans with quality.py to identify specific AI clichés and generic
    descriptors, then passes findings to the LLM for targeted correction.
    """
    from autonovelclaw.quality import assess_chapter_quality

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")

    # Pre-scan for issues
    qr = assess_chapter_quality(draft, min_words=100, max_words=999999)
    ai_issues = [i for i in qr.issues if i.category in ("ai_cliche", "generic")]

    # Save quality pre-scan
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_quality_prescan.md",
               qr.to_markdown(), subdir="reviews")

    # Get style reference from previously approved chapter
    style_ref = ""
    if ch > 1:
        prev = ctx.kb.get_approved_chapter(ch - 1)
        if prev:
            style_ref = f"STYLE REFERENCE (approved previous chapter excerpt):\n{_truncate(prev, 2000)}"

    style_ref_block = style_ref or "This is the first chapter — check against style targets above."

    # If pre-scan found AI clichés, inject them into the prompt
    extra_instructions = ""
    if ai_issues:
        extra_instructions = "\n\nPRE-SCAN FOUND THESE SPECIFIC ISSUES:\n"
        for iss in ai_issues[:15]:
            loc = f" (line {iss.line_number})" if iss.line_number else ""
            extra_instructions += f"- {iss.description}{loc}\n"

    rp = ctx.prompts.for_stage(
        "voice_consistency",
        style_reference_block=style_ref_block,
        chapter_text=draft,
    )

    user_msg = rp.user + extra_instructions if extra_instructions else rp.user

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=user_msg,
        max_tokens=rp.max_tokens or 8192,
    )

    if "VOICE CHECK: CLEAN" not in resp.text:
        ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", resp.text)
        _save_text(ctx.run_dir, f"chapter_{ch:02d}_voice_checked.md", resp.text, subdir="chapters")
        logger.info("Chapter %d: %d AI/generic issues found and corrected", ch, len(ai_issues))
    else:
        logger.info("Chapter %d: voice check clean (pre-scan: %d issues)", ch, len(ai_issues))


# ===================================================================
# PHASE E: CONTINUITY GATE
# ===================================================================

def _execute_chapter_continuity(ctx: _Ctx) -> None:
    """Stage 15: Sentinel checks for continuity against world and prior chapters.

    Combines structural checks via EntityTracker (name consistency, character
    gaps, timeline) with LLM-based semantic continuity checking.
    """
    from autonovelclaw.continuity.tracker import EntityTracker

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")
    codex = ctx.kb.get_world_codex()
    characters = ctx.kb.retrieve("characters", "all_profiles") or ""
    system_type = ctx.ckpt.get_artifact("system_type", "magic")

    # --- Structural check via EntityTracker ---
    tracker = EntityTracker()
    tracker_path = ctx.run_dir / "entity_tracker.json"
    tracker.load(tracker_path)

    # Register entities from profiles if this is chapter 1
    if ch == 1 and not tracker.entities:
        tracker.register_characters_from_profiles(characters)
        if codex:
            tracker.register_locations_from_codex(codex)

    # Process this chapter
    structural_issues = tracker.process_chapter(ch, draft)
    consistency_issues = tracker.check_consistency()
    tracker.save(tracker_path)

    # Build structural report
    struct_report = ""
    all_issues = [i for i in structural_issues + consistency_issues
                  if i.severity in ("error", "warning")]
    if all_issues:
        struct_report = "STRUCTURAL ISSUES DETECTED:\n"
        for iss in all_issues:
            struct_report += f"- [{iss.severity}] {iss.entity_name}: {iss.description}\n"

    # --- LLM semantic check ---
    prev_summaries = []
    for prev_ch in range(1, ch):
        s = ctx.kb.get_chapter_summary(prev_ch)
        if s:
            prev_summaries.append(f"Chapter {prev_ch}: {s}")
    prev_context = "\n\n".join(prev_summaries) if prev_summaries else "First chapter — no prior context."

    rp = ctx.prompts.for_stage(
        "chapter_continuity",
        codex_excerpt=_truncate(codex, 2000),
        characters_excerpt=_truncate(characters, 2000),
        previous_summaries=_truncate(prev_context, 3000),
        system_type=system_type,
        chapter_text=_truncate(draft, 6000),
        chapter_num=str(ch),
    )

    # Inject structural findings into the LLM prompt
    user_msg = rp.user
    if struct_report:
        user_msg += f"\n\nPRE-SCAN STRUCTURAL ISSUES:\n{struct_report}"

    resp = ctx.llm.complete(
        role=AgentRole.DEBATE,
        system_prompt=rp.system,
        user_message=user_msg,
        max_tokens=rp.max_tokens or 4096,
    )

    # Combine reports
    full_report = f"# Continuity Report — Chapter {ch}\n\n"
    full_report += f"## Structural Checks ({len(all_issues)} issues)\n\n"
    if all_issues:
        for iss in all_issues:
            full_report += f"- **{iss.entity_name}** [{iss.issue_type}]: {iss.description}\n"
    else:
        full_report += "No structural issues found.\n"
    full_report += f"\n## LLM Semantic Check\n\n{resp.text}\n"

    _save_text(ctx.run_dir, f"chapter_{ch:02d}_continuity_report.md", full_report, subdir="reviews")

    # If issues found, attempt fixes
    has_llm_issues = "CLEAN" not in resp.text.upper() and "0 issues" not in resp.text.lower()
    if has_llm_issues or len(all_issues) > 0:
        logger.warning("Chapter %d: continuity issues found (%d structural + LLM) — fixing", ch, len(all_issues))
        rp_fix = ctx.prompts.for_stage(
            "continuity_fix",
            report=_truncate(full_report, 3000),
            chapter_text=draft,
        )
        fix_resp = ctx.llm.complete(
            role=AgentRole.WRITER,
            system_prompt=rp_fix.system,
            user_message=rp_fix.user,
            max_tokens=8192,
        )
        ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", fix_resp.text)
        _save_text(ctx.run_dir, f"chapter_{ch:02d}_continuity_fixed.md", fix_resp.text, subdir="chapters")
    else:
        logger.info("Chapter %d: continuity check clean", ch)


def _execute_pre_review_polish(ctx: _Ctx) -> None:
    """Stage 16: Final copyedit polish before review."""
    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")

    rp = ctx.prompts.for_stage(
        "pre_review_polish",
        chapter_text=draft,
    )

    resp = ctx.llm.complete(
        role=AgentRole.EDITOR,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", resp.text)
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_polished.md", resp.text, subdir="chapters")
    logger.info("Chapter %d polished for review", ch)


# ===================================================================
# PHASE F: CRITICAL REVIEW
# ===================================================================

def _execute_independent_review(ctx: _Ctx) -> None:
    """Stage 17: Independent review by Reviewer Agent #1.

    CRITICAL DESIGN: The reviewer receives ONLY the chapter text and
    genre classification. NO codex, NO characters, NO beats, NO prior
    reviews, NO writer system prompt.

    Uses reviewers/parser.py for structured extraction from the response.
    """
    from autonovelclaw.reviewers.parser import parse_critic_review

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")
    genre = ctx.genre()
    total_wc = ctx.config.novel.target.word_count_min

    rp = ctx.prompts.for_stage(
        "independent_review",
        genre=genre,
        total_word_count=f"{total_wc:,}",
        chapter_num=str(ch),
        chapter_text=draft,
    )

    resp = ctx.llm.complete(
        role=AgentRole.REVIEWER_1,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 4096,
    )

    # Parse structured review data
    parsed = parse_critic_review(resp.text)
    rating = parsed.rating

    ctx.ckpt.store_artifact(f"review_1_ch{ch}", resp.text)
    ctx.ckpt.store_artifact(f"review_1_rating_ch{ch}", rating)
    ctx.ckpt.store_artifact(f"review_1_parsed_ch{ch}", {
        "rating": parsed.rating,
        "strengths": [s.text for s in parsed.strengths],
        "weaknesses": [w.text for w in parsed.weaknesses],
        "suggestions": [s.text for s in parsed.suggestions],
        "parse_confidence": parsed.parse_confidence,
    })

    _save_text(ctx.run_dir, f"chapter_{ch:02d}_review_1.md", resp.text, subdir="reviews")
    ctx.kb.store("reviews", f"chapter_{ch:02d}_review_1", resp.text,
                 meta={"chapter": ch, "reviewer": 1, "rating": rating})

    # Feed review patterns to evolution system
    from autonovelclaw.evolution import extract_lessons_from_reviews, EvolutionStore
    evo_dir = ctx.run_dir / "evolution"
    lessons = extract_lessons_from_reviews(resp.text, ch, rating, reviewer_id=1)
    if lessons:
        store = EvolutionStore(evo_dir)
        store.append_many(lessons)

    logger.info("Chapter %d reviewed by Critic: %.1f/10 (confidence: %.0f%%)",
                ch, rating, parsed.parse_confidence * 100)


def _execute_review_analysis(ctx: _Ctx) -> None:
    """Stage 18: Multi-perspective critic debate analyses the review."""
    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")
    review = ctx.ckpt.get_artifact(f"review_1_ch{ch}", "")
    codex = ctx.kb.get_world_codex()
    characters = ctx.kb.retrieve("characters", "all_profiles") or ""

    critics = ctx.config.review.debate_critics
    analyses: dict[str, str] = {}

    for critic_name in critics:
        critic_def = ctx.prompts.get_critic_prompt(critic_name)

        # Build extra context for continuity critic
        extra = ""
        if critic_name == "continuity_critic":
            extra = (
                f"WORLD CODEX (excerpt):\n{_truncate(codex, 1500)}\n\n"
                f"CHARACTERS (excerpt):\n{_truncate(characters, 1500)}"
            )

        rp = ctx.prompts.for_stage(
            "review_analysis_critic",
            critic_type=critic_name.replace("_", " "),
            focus_area=critic_def.get("focus", "general quality"),
            review_text=_truncate(review, 3000),
            chapter_excerpt=_truncate(draft, 4000),
            extra_context=extra,
        )

        resp = ctx.llm.complete(
            role=AgentRole.DEBATE,
            system_prompt=critic_def.get("system", rp.system),
            user_message=rp.user,
            max_tokens=rp.max_tokens or 2048,
        )
        analyses[critic_name] = resp.text

    # Compile
    full_analysis = f"# Review Analysis — Chapter {ch}\n\n"
    for name, text in analyses.items():
        full_analysis += f"## {name.replace('_', ' ').title()}\n\n{text}\n\n---\n\n"

    ctx.ckpt.store_artifact(f"review_analysis_ch{ch}", full_analysis)
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_review_analysis.md", full_analysis, subdir="reviews")
    logger.info("Chapter %d review analysis: %d critics", ch, len(analyses))


def _execute_enhancement_decision(ctx: _Ctx) -> None:
    """Stage 19: Decide PROCEED / REFINE / REWRITE based on rating + state."""
    ch = ctx.ch
    rating = float(ctx.ckpt.get_artifact(f"review_1_rating_ch{ch}", 7.0))
    analysis = ctx.ckpt.get_artifact(f"review_analysis_ch{ch}", "")
    review = ctx.ckpt.get_artifact(f"review_1_ch{ch}", "")

    min_proceed = ctx.config.review.min_rating_proceed
    min_refine = ctx.config.review.min_rating_refine
    max_enhance = ctx.config.review.max_enhancement_loops
    max_rewrite = ctx.config.review.max_rewrite_attempts
    loops = ctx.ckpt.enhancement_loops
    rewrites = ctx.ckpt.rewrite_count

    # Decision logic
    if loops >= max_enhance and rewrites >= max_rewrite:
        decision = "human_escalation"
        rationale = (
            f"Rating {rating:.1f}/10 after {loops} enhancement loops and "
            f"{rewrites} rewrites. Human review needed."
        )
    elif rating >= min_proceed:
        decision = "proceed"
        rationale = f"Rating {rating:.1f}/10 meets threshold {min_proceed}."
    elif rating >= min_refine:
        if loops >= max_enhance:
            decision = "rewrite"
            rationale = (
                f"Rating {rating:.1f}/10 after {loops} enhancement loops. "
                f"Full rewrite needed."
            )
        else:
            decision = "refine"
            rationale = (
                f"Rating {rating:.1f}/10 between {min_refine} and {min_proceed}. "
                f"Surgical enhancement recommended."
            )
    else:
        if rewrites >= max_rewrite:
            decision = "human_escalation"
            rationale = (
                f"Rating {rating:.1f}/10 below {min_refine} after {rewrites} rewrites. "
                f"Human review needed."
            )
        else:
            decision = "rewrite"
            rationale = f"Rating {rating:.1f}/10 below {min_refine}. Full rewrite needed."

    ctx.ckpt.store_artifact(f"decision_ch{ch}", decision)
    ctx.ckpt.record_decision(
        f"enhancement_decision_ch{ch}",
        decision,
        rationale,
    )

    _save_text(
        ctx.run_dir,
        f"chapter_{ch:02d}_decision.md",
        f"# Decision: {decision.upper()}\n\n"
        f"Rating: {rating:.1f}/10\n"
        f"Enhancement loops: {loops}/{max_enhance}\n"
        f"Rewrite attempts: {rewrites}/{max_rewrite}\n\n"
        f"{rationale}\n",
        subdir="reviews",
    )
    logger.info("Chapter %d decision: %s (%.1f/10)", ch, decision, rating)


# ===================================================================
# PHASE G: ENHANCEMENT LOOP
# ===================================================================

def _execute_surgical_enhancement(ctx: _Ctx) -> None:
    """Stage 20: Apply Phase 1.X surgical enhancements.

    Uses reviewers/planner.py to prioritise changes and generate
    targeted instructions for the LLM.
    """
    from autonovelclaw.reviewers.parser import parse_critic_review, parse_reader_review
    from autonovelclaw.reviewers.planner import plan_enhancement

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")
    review = ctx.ckpt.get_artifact(f"review_1_ch{ch}", "")
    analysis = ctx.ckpt.get_artifact(f"review_analysis_ch{ch}", "")
    loop = ctx.ckpt.enhancement_loops

    # Parse reviews for structured planning
    critic_parsed = parse_critic_review(review)

    # Check if we have a reader review from a prior loop
    reader_review_text = ctx.ckpt.get_artifact(f"review_2_ch{ch}", "")
    reader_parsed = parse_reader_review(reader_review_text) if reader_review_text else None

    # Build prioritised enhancement plan
    plan = plan_enhancement(
        critic_review=critic_parsed,
        reader_review=reader_parsed,
        debate_analysis=analysis,
        loop_index=loop,
    )

    # Save the plan
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_enhancement_plan.md",
               plan.to_markdown(), subdir="reviews")

    phase_name = plan.phase_name
    phase_focus = plan.to_prompt_instructions()

    rp = ctx.prompts.for_stage(
        "surgical_enhancement",
        phase_name=phase_name,
        phase_focus=phase_focus,
        review_text=_truncate(review, 3000),
        analysis_text=_truncate(analysis, 3000),
        chapter_text=draft,
    )

    resp = ctx.llm.complete(
        role=AgentRole.WRITER,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 8192,
    )

    # Separate chapter from change log
    parts = resp.text.rsplit("---", 1)
    chapter_text = parts[0].strip()
    change_log = parts[1].strip() if len(parts) > 1 else "No change log."

    old_wc = _word_count(draft)
    new_wc = _word_count(chapter_text)
    delta_pct = ((new_wc - old_wc) / max(old_wc, 1)) * 100

    ctx.ckpt.store_artifact(f"chapter_draft_ch{ch}", chapter_text)

    safe_phase = phase_name.replace(" ", "_").replace(".", "_")
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_{safe_phase}.md", chapter_text, subdir="chapters")
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_{safe_phase}_changes.md", change_log, subdir="reviews")

    # Feed enhancement effectiveness to evolution system
    from autonovelclaw.evolution import extract_lessons_from_enhancement, EvolutionStore
    prev_rating = float(ctx.ckpt.get_artifact(f"review_1_rating_ch{ch}", 7.0))
    lessons = extract_lessons_from_enhancement(
        chapter=ch, phase_name=phase_name,
        rating_before=prev_rating, rating_after=prev_rating,  # actual after-rating comes from re-review
        change_log=change_log[:300],
    )
    if lessons:
        store = EvolutionStore(ctx.run_dir / "evolution")
        store.append_many(lessons)

    logger.info("Chapter %d %s: %d → %d words (%+.1f%%), %d changes planned",
                ch, phase_name, old_wc, new_wc, delta_pct, len(plan.changes))


def _execute_re_review(ctx: _Ctx) -> None:
    """Stage 21: Second independent reviewer with fresh eyes.

    Reviewer #2 has NO access to Reviewer #1's feedback, planning docs,
    or any enhancement history. Uses parse_reader_review for structured extraction.
    """
    from autonovelclaw.reviewers.parser import parse_reader_review

    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")
    genre = ctx.genre()

    rp = ctx.prompts.for_stage(
        "re_review",
        genre=genre,
        chapter_num=str(ch),
        chapter_text=draft,
    )

    resp = ctx.llm.complete(
        role=AgentRole.REVIEWER_2,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=rp.max_tokens or 4096,
    )

    parsed = parse_reader_review(resp.text)
    rating = parsed.rating

    ctx.ckpt.store_artifact(f"review_2_ch{ch}", resp.text)
    ctx.ckpt.store_artifact(f"review_2_rating_ch{ch}", rating)
    ctx.ckpt.store_artifact(f"review_2_parsed_ch{ch}", {
        "rating": parsed.rating,
        "drag_points": parsed.drag_points,
        "confusion_points": parsed.confusion_points,
        "memorability": parsed.memorability,
        "parse_confidence": parsed.parse_confidence,
    })

    _save_text(ctx.run_dir, f"chapter_{ch:02d}_review_2.md", resp.text, subdir="reviews")
    ctx.kb.store("reviews", f"chapter_{ch:02d}_review_2", resp.text,
                 meta={"chapter": ch, "reviewer": 2, "rating": rating})
    logger.info("Chapter %d re-reviewed by Reader: %.1f/10 (confidence: %.0f%%)",
                ch, rating, parsed.parse_confidence * 100)


def _execute_quality_convergence(ctx: _Ctx) -> None:
    """Stage 22: Check if quality has converged to target.

    Uses reviewers/planner.py ConvergenceAnalysis for proper multi-point
    tracking, trend analysis, and diminishing returns detection.
    """
    from autonovelclaw.reviewers.planner import ConvergenceAnalysis

    ch = ctx.ch
    r1 = float(ctx.ckpt.get_artifact(f"review_1_rating_ch{ch}", 7.0))
    r2 = float(ctx.ckpt.get_artifact(f"review_2_rating_ch{ch}", 7.0))

    cw = ctx.config.review.critic_weight
    rw = ctx.config.review.reader_weight
    composite = (r1 * cw) + (r2 * rw)
    min_proceed = ctx.config.review.min_rating_proceed
    threshold = ctx.config.review.diminishing_returns_threshold

    # Load or create convergence tracker for this chapter
    ca = ConvergenceAnalysis(
        target_rating=min_proceed,
        diminishing_threshold=threshold,
    )

    # Restore prior convergence points from checkpoint
    prior_points = ctx.ckpt.get_artifact(f"convergence_history_ch{ch}", [])
    for pp in prior_points:
        ca.add_point(pp["critic"], pp["reader"], pp["composite"],
                     word_count=pp.get("wc", 0),
                     prev_word_count=pp.get("prev_wc", 0))

    # Add current point
    wc = _word_count(ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", ""))
    prev_wc = prior_points[-1].get("wc", 0) if prior_points else 0
    ca.add_point(r1, r2, composite, word_count=wc, prev_word_count=prev_wc)

    # Store history
    history = prior_points + [{"critic": r1, "reader": r2, "composite": composite, "wc": wc, "prev_wc": prev_wc}]
    ctx.ckpt.store_artifact(f"convergence_history_ch{ch}", history)

    # Also check loop exhaustion
    converged = ca.is_converged
    if not converged and ctx.ckpt.enhancement_loops >= ctx.config.review.max_enhancement_loops:
        converged = True

    if converged:
        ctx.ckpt.store_artifact(f"converged_ch{ch}", True)
        ctx.ckpt.store_artifact(f"decision_ch{ch}", "proceed")
        ctx.kb.store_lesson("convergence", (
            f"Chapter {ch}: converged at {composite:.1f}/10 after "
            f"{ctx.ckpt.enhancement_loops} loops. {ca.convergence_reason}. "
            f"Trend: {ca.trend}."
        ))
    else:
        ctx.ckpt.store_artifact(f"decision_ch{ch}", "refine")

    # Save convergence report
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_convergence.md",
               ca.to_markdown(), subdir="reviews")

    logger.info("Chapter %d convergence: %.1f/10 (trend: %s) — %s",
                ch, composite, ca.trend, "CONVERGED" if converged else "CONTINUE")


# ===================================================================
# PHASE H: MANUSCRIPT ASSEMBLY
# ===================================================================

def _execute_chapter_approval(ctx: _Ctx) -> None:
    """Stage 23: Gate — approve the chapter."""
    ch = ctx.ch
    draft = ctx.ckpt.get_artifact(f"chapter_draft_ch{ch}", "")

    if not ctx.auto_approve:
        from rich.console import Console
        con = Console()
        wc = _word_count(draft)
        r1 = ctx.ckpt.get_artifact(f"review_1_rating_ch{ch}", "N/A")
        r2 = ctx.ckpt.get_artifact(f"review_2_rating_ch{ch}", "N/A")

        con.print(f"\n[bold cyan]═══ CHAPTER {ch} APPROVAL ═══[/]")
        con.print(f"  Words: {wc:,}")
        con.print(f"  Critic: {r1}/10 | Reader: {r2}/10")
        con.print(f"  Loops: {ctx.ckpt.enhancement_loops}")
        con.print(f"\n  [dim]Review: chapters/chapter_{ch:02d}_*.md[/]")
        con.print("  [yellow]Type 'approve' or 'reject':[/]")
        response = input("  > ").strip().lower()
        if response != "approve":
            raise RuntimeError(f"Chapter {ch} rejected by user")

    # Store approved chapter in knowledge base
    ctx.kb.store("approved_chapters", f"chapter_{ch:02d}", draft,
                 meta={"chapter": ch, "words": _word_count(draft)})
    _save_text(ctx.run_dir, f"chapter_{ch:02d}_APPROVED.md", draft, subdir="chapters")
    logger.info("Chapter %d approved: %d words", ch, _word_count(draft))


def _execute_manuscript_compile(ctx: _Ctx) -> None:
    """Stage 24: Assemble all approved chapters into a manuscript."""
    import datetime as dt

    total = ctx.ckpt.total_chapters
    title = ctx.config.novel.title or "Untitled Novel"
    author = ctx.config.novel.author or "Anonymous"

    parts = []

    # Title page
    parts.append(f"# {title}\n\n")
    if ctx.config.novel.subtitle:
        parts.append(f"### {ctx.config.novel.subtitle}\n\n")
    parts.append(f"**{author}**\n\n---\n\n")

    # Copyright
    year = dt.datetime.now().year
    parts.append(
        f"Copyright © {year} {author}. All rights reserved.\n\n"
        f"No part of this publication may be reproduced, distributed, "
        f"or transmitted in any form without prior written permission.\n\n---\n\n"
    )

    # Chapters
    total_words = 0
    for ch_num in range(1, total + 1):
        chapter_text = ctx.kb.get_approved_chapter(ch_num)
        if not chapter_text:
            logger.warning("Chapter %d not found in KB", ch_num)
            continue
        parts.append(f"\n\n{'=' * 60}\n\n")
        parts.append(chapter_text)
        parts.append("\n\n")
        total_words += _word_count(chapter_text)

    manuscript = "".join(parts)
    ctx.ckpt.store_artifact("manuscript", manuscript)
    ctx.ckpt.store_artifact("total_word_count", total_words)
    _save_text(ctx.run_dir, "manuscript_complete.md", manuscript, subdir="deliverables")
    logger.info("Manuscript compiled: %d chapters, %d words", total, total_words)


def _execute_continuity_verify(ctx: _Ctx) -> None:
    """Stage 25: Full-manuscript continuity verification.

    Uses continuity/verify.py for comprehensive entity, timeline,
    and foreshadowing analysis across the complete manuscript.
    """
    from autonovelclaw.continuity.verify import verify_manuscript

    total = ctx.ckpt.total_chapters
    codex = ctx.kb.get_world_codex()
    characters = ctx.kb.retrieve("characters", "all_profiles") or ""
    outline = ctx.ckpt.get_artifact("book_outline", "")

    # Gather all approved chapters
    chapters: dict[int, str] = {}
    for ch_num in range(1, total + 1):
        ch_text = ctx.kb.get_approved_chapter(ch_num)
        if ch_text:
            chapters[ch_num] = ch_text

    if not chapters:
        logger.warning("No approved chapters found for continuity verification")
        _save_text(ctx.run_dir, "continuity_report.md",
                   "# Continuity Report\n\nNo chapters found.", subdir="deliverables")
        return

    # Run full verification
    report = verify_manuscript(
        chapters=chapters,
        character_profiles=characters,
        world_codex=codex,
        book_outline=outline,
    )

    # Save comprehensive report
    _save_text(ctx.run_dir, "continuity_report.md",
               report.to_markdown(), subdir="deliverables")

    logger.info(
        "Continuity verification: %d chapters, %d entities tracked, "
        "%d issues (%d errors, %d warnings)",
        report.chapters_checked, report.entities_tracked,
        report.total_issues, report.error_count, report.warning_count,
    )


def _execute_style_consistency(ctx: _Ctx) -> None:
    """Stage 26: Full-manuscript style consistency check."""
    manuscript = ctx.ckpt.get_artifact("manuscript", "")
    words = manuscript.split()
    total = len(words)

    if total < 2000:
        _save_text(ctx.run_dir, "style_consistency_report.md",
                   "Manuscript too short for style analysis.", subdir="deliverables")
        return

    samples = {
        "opening": " ".join(words[:2000]),
        "middle": " ".join(words[total // 2 - 1000:total // 2 + 1000]),
        "ending": " ".join(words[-2000:]),
    }

    rp = ctx.prompts.for_stage(
        "style_consistency_check",
        opening_sample=samples["opening"],
        middle_sample=samples["middle"],
        ending_sample=samples["ending"],
    )

    resp = ctx.llm.complete(
        role=AgentRole.DEBATE,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=2048,
    )

    _save_text(ctx.run_dir, "style_consistency_report.md", resp.text, subdir="deliverables")
    logger.info("Style consistency check complete")


# ===================================================================
# PHASE I: PUBLISHING PIPELINE
# ===================================================================

def _execute_epub_generation(ctx: _Ctx) -> None:
    """Stage 27: Generate KDP-ready EPUB using publishing/epub_builder."""
    from autonovelclaw.publishing.epub_builder import build_epub

    total = ctx.ckpt.total_chapters
    title = ctx.config.novel.title or "Untitled Novel"
    author = ctx.config.novel.author or "Anonymous"

    # Gather approved chapters
    chapters: dict[int, str] = {}
    for ch_num in range(1, total + 1):
        ch_text = ctx.kb.get_approved_chapter(ch_num)
        if ch_text:
            chapters[ch_num] = ch_text

    if not chapters:
        raise RuntimeError("No approved chapters found for EPUB generation")

    # Cover image
    cover_path = None
    cover_str = ctx.config.inputs.cover_image
    if cover_str and Path(cover_str).exists():
        cover_path = Path(cover_str)

    # Build EPUB
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
    epub_path = ctx.run_dir / "deliverables" / f"{safe_title}.epub"

    build_epub(
        title=title,
        author=author,
        chapters=chapters,
        output_path=epub_path,
        subtitle=ctx.config.novel.subtitle or "",
        cover_image_path=cover_path,
        series_name=ctx.config.novel.series.name or "",
        series_number=ctx.config.novel.series.book_number,
        description=ctx.ckpt.get_artifact("book_description", ""),
    )

    ctx.ckpt.store_artifact("epub_path", str(epub_path))
    logger.info("EPUB generated: %s", epub_path)


def _execute_paperback_formatting(ctx: _Ctx) -> None:
    """Stage 28: Generate KDP Print-ready interior PDF using publishing/pdf_builder."""
    from autonovelclaw.publishing.pdf_builder import build_pdf

    total = ctx.ckpt.total_chapters
    title = ctx.config.novel.title or "Untitled Novel"
    author = ctx.config.novel.author or "Anonymous"

    # Gather approved chapters
    chapters: dict[int, str] = {}
    for ch_num in range(1, total + 1):
        ch_text = ctx.kb.get_approved_chapter(ch_num)
        if ch_text:
            chapters[ch_num] = ch_text

    if not chapters:
        raise RuntimeError("No approved chapters found for PDF generation")

    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
    pdf_path = ctx.run_dir / "deliverables" / f"{safe_title}_interior.pdf"

    trim = ctx.config.publishing.paperback.trim_size
    estimated_pages = ctx.ckpt.get_artifact("total_word_count", 60000) // 250

    build_pdf(
        title=title,
        author=author,
        chapters=chapters,
        output_path=pdf_path,
        trim_size=trim,
        subtitle=ctx.config.novel.subtitle or "",
        estimated_pages=estimated_pages,
    )

    ctx.ckpt.store_artifact("paperback_path", str(pdf_path))
    logger.info("PDF generated: %s (trim: %s)", pdf_path, trim)


def _execute_publishing_package(ctx: _Ctx) -> None:
    """Stage 29: Generate the complete publishing package."""
    import datetime as dt

    title = ctx.config.novel.title or "Untitled Novel"
    author = ctx.config.novel.author or "Anonymous"
    genre = ctx.genre()
    total_words = ctx.ckpt.get_artifact("total_word_count", 0)
    total_chapters = ctx.ckpt.total_chapters

    deliverables = ctx.run_dir / "deliverables"

    # Metadata
    metadata = {
        "title": title,
        "subtitle": ctx.config.novel.subtitle,
        "author": author,
        "genre": genre,
        "subgenres": ctx.config.novel.genre.subgenres,
        "word_count": total_words,
        "chapter_count": total_chapters,
        "series": {
            "name": ctx.config.novel.series.name,
            "book_number": ctx.config.novel.series.book_number,
            "total_books": ctx.config.novel.series.total_books,
        },
        "generated_by": "AutoNovelClaw v0.1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "token_usage": ctx.llm.total_tokens,
    }
    (deliverables / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # Book description
    rp = ctx.prompts.for_stage(
        "book_description",
        title=title,
        genre=genre,
        author=author,
        total_chapters=str(total_chapters),
        total_words=f"{total_words:,}",
        series_info=(
            f"Series: {ctx.config.novel.series.name} Book {ctx.config.novel.series.book_number}"
            if ctx.config.novel.series.name else "Standalone novel."
        ),
        themes=", ".join(ctx.config.novel.genre.subgenres) or genre,
    )

    resp = ctx.llm.complete(
        role=AgentRole.EDITOR,
        system_prompt=rp.system,
        user_message=rp.user,
        max_tokens=1024,
    )
    (deliverables / "book_description.html").write_text(resp.text)

    # Keywords
    rp_kw = ctx.prompts.for_stage(
        "keywords_generation",
        title=title,
        genre=genre,
        themes=", ".join(ctx.config.novel.genre.subgenres) or genre,
    )
    resp_kw = ctx.llm.complete(
        role=AgentRole.EDITOR,
        system_prompt=rp_kw.system,
        user_message=rp_kw.user,
        max_tokens=256,
    )
    (deliverables / "keywords.txt").write_text(resp_kw.text)

    # README summary
    def _safe(name: str) -> str:
        return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")

    summary = (
        f"# AutoNovelClaw — Publishing Package\n\n"
        f"## {title}\n"
        f"**{author}**\n\n---\n\n"
        f"| File | Description |\n|------|-------------|\n"
        f"| `manuscript_complete.md` | Full manuscript |\n"
        f"| `{_safe(title)}.epub` | Kindle EPUB |\n"
        f"| `{_safe(title)}_interior.pdf` | KDP Print interior |\n"
        f"| `metadata.json` | Book metadata |\n"
        f"| `book_description.html` | Amazon description |\n"
        f"| `keywords.txt` | KDP keywords |\n\n"
        f"**Words:** {total_words:,} | **Chapters:** {total_chapters} | "
        f"**Genre:** {genre}\n\n"
        f"**Tokens:** {json.dumps(ctx.llm.total_tokens)}\n"
    )
    (deliverables / "README.md").write_text(summary)

    # --- KDP Validation ---
    from autonovelclaw.publishing.validator import validate_all

    epub_path = Path(ctx.ckpt.get_artifact("epub_path", ""))
    pdf_path = Path(ctx.ckpt.get_artifact("paperback_path", ""))
    cover_str = ctx.config.inputs.cover_image
    cover_path = Path(cover_str) if cover_str else None

    validation = validate_all(
        epub_path=epub_path if epub_path.exists() else None,
        pdf_path=pdf_path if pdf_path.exists() else None,
        cover_path=cover_path,
        metadata=metadata,
        trim_size=ctx.config.publishing.paperback.trim_size,
    )

    _save_text(ctx.run_dir, "kdp_validation.md", validation.to_markdown(), subdir="deliverables")

    if validation.is_publishable:
        logger.info("Publishing package complete and KDP-ready: %s", deliverables)
    else:
        logger.warning(
            "Publishing package complete but has %d KDP errors — review kdp_validation.md",
            validation.error_count,
        )


# ===================================================================
# DISPATCH TABLE
# ===================================================================

_STAGE_HANDLERS: dict[Stage, Any] = {
    Stage.IDEA_INTAKE: _execute_idea_intake,
    Stage.STORYLINE_GENERATION: _execute_storyline_generation,
    Stage.SELECTION_AND_SCOPE: _execute_selection_and_scope,
    Stage.SERIES_ARC_DESIGN: _execute_series_arc_design,
    Stage.CODEX_GENERATION: _execute_codex_generation,
    Stage.CHARACTER_CREATION: _execute_character_creation,
    Stage.SYSTEM_DESIGN: _execute_system_design,
    Stage.WORLD_VALIDATION: _execute_world_validation,
    Stage.BOOK_OUTLINE: _execute_book_outline,
    Stage.CHAPTER_BEAT_SHEETS: _execute_chapter_beat_sheets,
    Stage.OUTLINE_REVIEW: _execute_outline_review,
    Stage.SCENE_PLANNING: _execute_scene_planning,
    Stage.CHAPTER_DRAFT: _execute_chapter_draft,
    Stage.SENSORY_ENHANCEMENT: _execute_sensory_enhancement,
    Stage.VOICE_CONSISTENCY: _execute_voice_consistency,
    Stage.CHAPTER_CONTINUITY: _execute_chapter_continuity,
    Stage.PRE_REVIEW_POLISH: _execute_pre_review_polish,
    Stage.INDEPENDENT_REVIEW: _execute_independent_review,
    Stage.REVIEW_ANALYSIS: _execute_review_analysis,
    Stage.ENHANCEMENT_DECISION: _execute_enhancement_decision,
    Stage.SURGICAL_ENHANCEMENT: _execute_surgical_enhancement,
    Stage.RE_REVIEW: _execute_re_review,
    Stage.QUALITY_CONVERGENCE: _execute_quality_convergence,
    Stage.CHAPTER_APPROVAL: _execute_chapter_approval,
    Stage.MANUSCRIPT_COMPILE: _execute_manuscript_compile,
    Stage.CONTINUITY_VERIFY: _execute_continuity_verify,
    Stage.STYLE_CONSISTENCY: _execute_style_consistency,
    Stage.EPUB_GENERATION: _execute_epub_generation,
    Stage.PAPERBACK_FORMATTING: _execute_paperback_formatting,
    Stage.PUBLISHING_PACKAGE: _execute_publishing_package,
}


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def execute_stage(
    *,
    stage: Stage,
    config: NovelClawConfig,
    llm: BaseLLMClient,
    ckpt: Checkpoint,
    kb: KnowledgeBase,
    prompts: PromptManager,
    run_dir: Path,
    auto_approve: bool = False,
) -> None:
    """Execute a single pipeline stage.

    Raises KeyError if the stage has no handler.
    Raises any exception from the handler on failure.
    """
    handler = _STAGE_HANDLERS.get(stage)
    if handler is None:
        raise KeyError(f"No handler for stage {stage.name} ({int(stage)})")

    ctx = _Ctx(
        config=config,
        llm=llm,
        ckpt=ckpt,
        kb=kb,
        prompts=prompts,
        run_dir=run_dir,
        auto_approve=auto_approve,
    )
    handler(ctx)
