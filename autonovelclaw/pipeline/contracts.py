"""Stage I/O contracts for the 30-stage AutoNovelClaw pipeline.

Each StageContract declares:
  - input_keys:   state artifact keys this stage reads
  - input_files:  filesystem artifacts this stage reads (relative to artifact_dir)
  - output_keys:  state artifact keys this stage must produce
  - output_files: filesystem artifacts this stage must produce
  - dod:          Definition of Done — human-readable acceptance criterion
  - error_code:   unique error identifier for diagnostics
  - max_retries:  how many times the stage may be retried on failure
  - is_per_chapter: whether this stage runs inside the chapter loop

Contracts are validated BEFORE stage execution (are inputs present?) and
AFTER execution (were outputs produced?).  Missing inputs block execution.
Missing outputs mark the stage as FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autonovelclaw.pipeline.stages import Stage


@dataclass(frozen=True)
class StageContract:
    stage: Stage
    input_keys: tuple[str, ...] = ()
    input_files: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()
    dod: str = ""
    error_code: str = ""
    max_retries: int = 1
    is_per_chapter: bool = False


def _ch(pattern: str) -> str:
    """Mark a pattern as chapter-templated (uses {ch} placeholder)."""
    return pattern


# ---------------------------------------------------------------------------
# Contract definitions for all 30 stages
# ---------------------------------------------------------------------------

CONTRACTS: dict[Stage, StageContract] = {

    # ===== Phase 0: Ideation =====

    Stage.IDEA_INTAKE: StageContract(
        stage=Stage.IDEA_INTAKE,
        input_keys=("raw_topic",),
        output_keys=("parsed_concept",),
        output_files=("parsed_concept.json",),
        dod="User concept parsed into structured elements with genre, tone, and scale",
        error_code="E00_IDEA_PARSE_FAIL",
        max_retries=0,
    ),

    Stage.STORYLINE_GENERATION: StageContract(
        stage=Stage.STORYLINE_GENERATION,
        input_keys=("parsed_concept",),
        output_keys=("storylines_raw", "storylines_parsed"),
        output_files=("storylines.md", "storylines_parsed.json"),
        dod="N distinct storylines generated with title, logline, premise, protagonist, "
            "antagonist, world concept, themes, and series potential",
        error_code="E01_STORYLINE_FAIL",
        max_retries=1,
    ),

    Stage.SELECTION_AND_SCOPE: StageContract(
        stage=Stage.SELECTION_AND_SCOPE,
        input_keys=("storylines_parsed",),
        output_keys=("selected_storyline", "novel_scope"),
        output_files=("selected_storyline.md",),
        dod="One storyline selected; scope (standalone/series) decided",
        error_code="E02_SELECTION_GATE",
        max_retries=0,
    ),

    Stage.SERIES_ARC_DESIGN: StageContract(
        stage=Stage.SERIES_ARC_DESIGN,
        input_keys=("selected_storyline", "novel_scope"),
        output_keys=("series_arc",),
        output_files=("series_arc.md",),
        dod="Multi-book arc with per-book focus, mystery reveal schedule, "
            "character evolution, and foreshadowing map",
        error_code="E03_SERIES_ARC_FAIL",
        max_retries=1,
    ),

    # ===== Phase A: World-Building =====

    Stage.CODEX_GENERATION: StageContract(
        stage=Stage.CODEX_GENERATION,
        input_keys=("selected_storyline",),
        output_keys=("world_codex_generated",),
        output_files=("world/world_codex.md",),
        dod="World codex with geography, history, cultures, politics, flora/fauna, "
            "economy, religion (>=5000 words)",
        error_code="E04_CODEX_FAIL",
        max_retries=1,
    ),

    Stage.CHARACTER_CREATION: StageContract(
        stage=Stage.CHARACTER_CREATION,
        input_keys=("world_codex_generated",),
        output_keys=("characters_generated",),
        output_files=("world/character_profiles.md",),
        dod="Character profiles for protagonist, antagonist, and >=3 supporting "
            "characters with physical, psychological, voice, relationships, and arc",
        error_code="E05_CHARACTER_FAIL",
        max_retries=1,
    ),

    Stage.SYSTEM_DESIGN: StageContract(
        stage=Stage.SYSTEM_DESIGN,
        input_keys=("world_codex_generated",),
        output_keys=("system_designed",),
        output_files=(),  # dynamic: magic_system.md or technology_system.md
        dod="Magic or technology system with mechanics, rules, limitations, "
            "cultural impact, and aesthetic",
        error_code="E06_SYSTEM_FAIL",
        max_retries=1,
    ),

    Stage.WORLD_VALIDATION: StageContract(
        stage=Stage.WORLD_VALIDATION,
        input_keys=("world_codex_generated", "characters_generated", "system_designed"),
        output_keys=(),
        output_files=(),
        dod="World codex, character profiles, and system approved by user",
        error_code="E07_WORLD_GATE",
        max_retries=0,
    ),

    # ===== Phase B: Story Architecture =====

    Stage.BOOK_OUTLINE: StageContract(
        stage=Stage.BOOK_OUTLINE,
        input_keys=("selected_storyline", "world_codex_generated", "characters_generated"),
        output_keys=("book_outline", "total_chapters"),
        output_files=("book_outline.md",),
        dod="Chapter-by-chapter outline with POV, location, events, emotional "
            "trajectory, pacing, foreshadowing, and word count targets",
        error_code="E08_OUTLINE_FAIL",
        max_retries=1,
    ),

    Stage.CHAPTER_BEAT_SHEETS: StageContract(
        stage=Stage.CHAPTER_BEAT_SHEETS,
        input_keys=("book_outline",),
        output_keys=("beat_sheets",),
        output_files=("beat_sheets.md",),
        dod="3-5 scene beat sheets per chapter with sensory anchors, "
            "dialogue beats, emotional escalation, and transitions",
        error_code="E09_BEATS_FAIL",
        max_retries=1,
    ),

    Stage.OUTLINE_REVIEW: StageContract(
        stage=Stage.OUTLINE_REVIEW,
        input_keys=("book_outline", "beat_sheets"),
        output_keys=(),
        output_files=(),
        dod="Outline and beat sheets approved by user",
        error_code="E10_OUTLINE_GATE",
        max_retries=0,
    ),

    # ===== Phase C: Chapter Writing (per-chapter) =====

    Stage.SCENE_PLANNING: StageContract(
        stage=Stage.SCENE_PLANNING,
        input_keys=("beat_sheets", "book_outline"),
        output_keys=(),  # dynamic: scene_plan_ch{N}
        output_files=(),  # dynamic: chapters/chapter_{NN}_scene_plan.md
        dod="Scene-by-scene plan with sensory distribution, dialogue beats, "
            "emotional escalation, POV filter, and word count targets",
        error_code="E11_SCENE_PLAN_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.CHAPTER_DRAFT: StageContract(
        stage=Stage.CHAPTER_DRAFT,
        input_keys=(),  # dynamic: scene_plan_ch{N}
        output_keys=(),  # dynamic: chapter_draft_ch{N}
        output_files=(),  # dynamic: chapters/chapter_{NN}_draft.md
        dod="Complete chapter draft meeting word count target with sensory "
            "grounding in first 2 paragraphs and closing hook",
        error_code="E12_DRAFT_FAIL",
        max_retries=2,
        is_per_chapter=True,
    ),

    Stage.SENSORY_ENHANCEMENT: StageContract(
        stage=Stage.SENSORY_ENHANCEMENT,
        input_keys=(),  # dynamic: chapter_draft_ch{N}
        output_keys=(),  # dynamic: chapter_draft_ch{N} (updated)
        output_files=(),  # dynamic: chapters/chapter_{NN}_enhanced.md
        dod="Sensory density meets targets: 60-70% of paragraphs with 2+ senses, "
            "olfactory adequately represented, word count within +5%",
        error_code="E13_SENSORY_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    # ===== Phase D: Style Verification (per-chapter) =====

    Stage.VOICE_CONSISTENCY: StageContract(
        stage=Stage.VOICE_CONSISTENCY,
        input_keys=(),
        output_keys=(),
        output_files=(),
        dod="No AI-typical phrasing, consistent character voice, varied "
            "sentence rhythm, no POV breaks, no uncaught clichés",
        error_code="E14_VOICE_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    # ===== Phase E: Continuity Gate (per-chapter) =====

    Stage.CHAPTER_CONTINUITY: StageContract(
        stage=Stage.CHAPTER_CONTINUITY,
        input_keys=(),
        output_keys=(),
        output_files=(),  # dynamic: reviews/chapter_{NN}_continuity_report.md
        dod="Character names, descriptions, timeline, world rules, and "
            "foreshadowing consistent with codex and prior chapters",
        error_code="E15_CONTINUITY_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.PRE_REVIEW_POLISH: StageContract(
        stage=Stage.PRE_REVIEW_POLISH,
        input_keys=(),
        output_keys=(),
        output_files=(),
        dod="Typos, grammar, punctuation, and dialogue formatting corrected; "
            "no repeated words within 50-word proximity",
        error_code="E16_POLISH_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    # ===== Phase F: Critical Review (per-chapter) =====

    Stage.INDEPENDENT_REVIEW: StageContract(
        stage=Stage.INDEPENDENT_REVIEW,
        input_keys=(),
        output_keys=(),  # dynamic: review_1_ch{N}, review_1_rating_ch{N}
        output_files=(),  # dynamic: reviews/chapter_{NN}_review_1.md
        dod="Reviewer #1 rates chapter on /10 scale with 3-5 strengths, "
            "3-5 weaknesses, 3-5 concrete suggestions, and improvement path",
        error_code="E17_REVIEW1_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.REVIEW_ANALYSIS: StageContract(
        stage=Stage.REVIEW_ANALYSIS,
        input_keys=(),
        output_keys=(),
        output_files=(),
        dod="Multi-perspective critic analysis complete: pacing, character, "
            "prose, and continuity critics each provide 1-3 suggestions",
        error_code="E18_ANALYSIS_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.ENHANCEMENT_DECISION: StageContract(
        stage=Stage.ENHANCEMENT_DECISION,
        input_keys=(),
        output_keys=(),  # dynamic: decision_ch{N}
        output_files=(),
        dod="Decision made: PROCEED (>=9.0), REFINE (7.5-8.9), "
            "REWRITE (<7.5), or HUMAN_ESCALATION",
        error_code="E19_DECISION_FAIL",
        max_retries=0,
        is_per_chapter=True,
    ),

    # ===== Phase G: Enhancement Loop (per-chapter, iterable) =====

    Stage.SURGICAL_ENHANCEMENT: StageContract(
        stage=Stage.SURGICAL_ENHANCEMENT,
        input_keys=(),
        output_keys=(),
        output_files=(),
        dod="Phase 1.X enhancement applied: highest-impact changes first, "
            "word count delta <=5%, all identified strengths preserved",
        error_code="E20_ENHANCE_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.RE_REVIEW: StageContract(
        stage=Stage.RE_REVIEW,
        input_keys=(),
        output_keys=(),  # dynamic: review_2_ch{N}, review_2_rating_ch{N}
        output_files=(),
        dod="Reviewer #2 (fresh eyes) rates enhanced chapter independently "
            "with no knowledge of prior reviews",
        error_code="E21_REREVIEW_FAIL",
        max_retries=1,
        is_per_chapter=True,
    ),

    Stage.QUALITY_CONVERGENCE: StageContract(
        stage=Stage.QUALITY_CONVERGENCE,
        input_keys=(),
        output_keys=(),  # dynamic: converged_ch{N}
        output_files=(),
        dod="Composite rating meets target (>=9.0) or diminishing returns "
            "detected (<+0.2 improvement per loop)",
        error_code="E22_CONVERGE_FAIL",
        max_retries=0,
        is_per_chapter=True,
    ),

    # ===== Phase H: Manuscript Assembly =====

    Stage.CHAPTER_APPROVAL: StageContract(
        stage=Stage.CHAPTER_APPROVAL,
        input_keys=(),
        output_keys=(),  # dynamic: last_approved_chapter
        output_files=(),  # dynamic: chapters/chapter_{NN}_APPROVED.md
        dod="Chapter approved by user (or auto-approved); "
            "stored in knowledge base for continuity reference",
        error_code="E23_CHAPTER_GATE",
        max_retries=0,
        is_per_chapter=True,
    ),

    Stage.MANUSCRIPT_COMPILE: StageContract(
        stage=Stage.MANUSCRIPT_COMPILE,
        input_keys=(),
        output_keys=("manuscript", "total_word_count"),
        output_files=("deliverables/manuscript_complete.md",),
        dod="All approved chapters assembled with title page, copyright, "
            "table of contents, and chapter separators",
        error_code="E24_COMPILE_FAIL",
        max_retries=1,
    ),

    Stage.CONTINUITY_VERIFY: StageContract(
        stage=Stage.CONTINUITY_VERIFY,
        input_keys=("manuscript",),
        output_keys=(),
        output_files=("deliverables/continuity_report.md",),
        dod="Full-manuscript continuity check: character names, timeline, "
            "world rules, foreshadowing resolution, dead-end detection",
        error_code="E25_FULLCHECK_FAIL",
        max_retries=1,
    ),

    Stage.STYLE_CONSISTENCY: StageContract(
        stage=Stage.STYLE_CONSISTENCY,
        input_keys=("manuscript",),
        output_keys=(),
        output_files=("deliverables/style_consistency_report.md",),
        dod="Voice, sensory density, sentence rhythm, character voice, and "
            "narrative distance consistent across full manuscript",
        error_code="E26_STYLE_FAIL",
        max_retries=1,
    ),

    # ===== Phase I: Publishing Pipeline =====

    Stage.EPUB_GENERATION: StageContract(
        stage=Stage.EPUB_GENERATION,
        input_keys=(),
        output_keys=("epub_path",),
        output_files=(),  # dynamic: deliverables/{title}.epub
        dod="Valid EPUB 3.0 with cover, TOC, navigation, metadata, "
            "and chapter formatting suitable for KDP upload",
        error_code="E27_EPUB_FAIL",
        max_retries=1,
    ),

    Stage.PAPERBACK_FORMATTING: StageContract(
        stage=Stage.PAPERBACK_FORMATTING,
        input_keys=(),
        output_keys=("paperback_path",),
        output_files=(),  # dynamic: deliverables/{title}_interior.pdf
        dod="KDP Print-ready interior PDF with correct trim size, margins, "
            "typography, running headers, and page numbering",
        error_code="E28_PDF_FAIL",
        max_retries=1,
    ),

    Stage.PUBLISHING_PACKAGE: StageContract(
        stage=Stage.PUBLISHING_PACKAGE,
        input_keys=(),
        output_keys=(),
        output_files=(
            "deliverables/metadata.json",
            "deliverables/book_description.html",
            "deliverables/keywords.txt",
            "deliverables/README.md",
        ),
        dod="Complete KDP upload package: EPUB, PDF, metadata, "
            "description, keywords, and summary",
        error_code="E29_PACKAGE_FAIL",
        max_retries=1,
    ),
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(
    stage: Stage,
    state_artifacts: dict[str, object],
    artifact_dir_files: set[str],
) -> list[str]:
    """Check that all required inputs exist. Returns list of missing items."""
    contract = CONTRACTS.get(stage)
    if contract is None:
        return []

    missing = []
    for key in contract.input_keys:
        if key not in state_artifacts or state_artifacts[key] is None:
            missing.append(f"state key: {key}")

    for fpath in contract.input_files:
        if fpath not in artifact_dir_files:
            missing.append(f"file: {fpath}")

    return missing


def validate_outputs(
    stage: Stage,
    state_artifacts: dict[str, object],
    artifact_dir_files: set[str],
) -> list[str]:
    """Check that all required outputs were produced. Returns list of missing items."""
    contract = CONTRACTS.get(stage)
    if contract is None:
        return []

    missing = []
    for key in contract.output_keys:
        if key not in state_artifacts or state_artifacts[key] is None:
            missing.append(f"state key: {key}")

    for fpath in contract.output_files:
        if fpath not in artifact_dir_files:
            missing.append(f"file: {fpath}")

    return missing


def get_contract(stage: Stage) -> StageContract | None:
    """Retrieve the contract for a stage."""
    return CONTRACTS.get(stage)


def max_retries_for(stage: Stage) -> int:
    """Return the maximum retry count for a stage."""
    contract = CONTRACTS.get(stage)
    return contract.max_retries if contract else 1
