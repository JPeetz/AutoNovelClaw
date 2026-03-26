"""30-stage AutoNovelClaw pipeline state machine.

Defines the stage sequence, status transitions, gate logic, rollback rules,
chapter-loop semantics, and phase groupings.

Architecture
------------
* ``Stage`` — IntEnum of all 30 pipeline stages.
* ``StageStatus`` — 9-state lifecycle (pending → running → done/blocked/failed/…).
* ``TransitionEvent`` — events that drive state changes.
* ``TransitionOutcome`` — result of a transition (new status, next stage, rollback).
* ``advance()`` — pure-function state machine: (stage, status, event) → outcome.
* ``gate_required()`` — check if a stage needs human approval.
* ``is_chapter_loop_stage()`` — check if a stage runs per-chapter.

The chapter loop (Stages 11–23) repeats for each chapter in the novel.
Within the chapter loop, the review sub-loop (Stages 17–22) can iterate
up to ``max_enhancement_loops`` times before escalating.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Iterable


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

class Stage(IntEnum):
    """30-stage novel-creation pipeline."""

    # Phase 0: Ideation
    IDEA_INTAKE = 0
    STORYLINE_GENERATION = 1
    SELECTION_AND_SCOPE = 2          # GATE
    SERIES_ARC_DESIGN = 3            # skippable (standalone)

    # Phase A: World-Building
    CODEX_GENERATION = 4
    CHARACTER_CREATION = 5
    SYSTEM_DESIGN = 6
    WORLD_VALIDATION = 7             # GATE

    # Phase B: Story Architecture
    BOOK_OUTLINE = 8
    CHAPTER_BEAT_SHEETS = 9
    OUTLINE_REVIEW = 10              # GATE

    # Phase C: Chapter Writing (per-chapter loop starts here)
    SCENE_PLANNING = 11
    CHAPTER_DRAFT = 12
    SENSORY_ENHANCEMENT = 13

    # Phase D: Style Verification
    VOICE_CONSISTENCY = 14

    # Phase E: Continuity Gate
    CHAPTER_CONTINUITY = 15
    PRE_REVIEW_POLISH = 16

    # Phase F: Critical Review
    INDEPENDENT_REVIEW = 17
    REVIEW_ANALYSIS = 18
    ENHANCEMENT_DECISION = 19

    # Phase G: Enhancement Loop
    SURGICAL_ENHANCEMENT = 20
    RE_REVIEW = 21
    QUALITY_CONVERGENCE = 22

    # Phase H: Manuscript Assembly
    CHAPTER_APPROVAL = 23            # GATE (per-chapter loop ends here)
    MANUSCRIPT_COMPILE = 24
    CONTINUITY_VERIFY = 25
    STYLE_CONSISTENCY = 26

    # Phase I: Publishing Pipeline
    EPUB_GENERATION = 27
    PAPERBACK_FORMATTING = 28
    PUBLISHING_PACKAGE = 29


class StageStatus(str, Enum):
    """Lifecycle status for each stage instance."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED_APPROVAL = "blocked_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    RETRYING = "retrying"
    FAILED = "failed"
    DONE = "done"
    SKIPPED = "skipped"


class TransitionEvent(str, Enum):
    """Events that drive state transitions."""

    START = "start"
    SUCCEED = "succeed"
    APPROVE = "approve"
    REJECT = "reject"
    FAIL = "fail"
    RETRY = "retry"
    PAUSE = "pause"
    RESUME = "resume"
    TIMEOUT = "timeout"
    SKIP = "skip"


# ---------------------------------------------------------------------------
# Stage sequence and relationships
# ---------------------------------------------------------------------------

# Ordered list of all stages for linear traversal
STAGE_SEQUENCE: tuple[Stage, ...] = tuple(Stage)

# Next stage in the linear (non-looping) sequence
NEXT_STAGE: dict[Stage, Stage | None] = {}
for _i, _s in enumerate(STAGE_SEQUENCE):
    NEXT_STAGE[_s] = STAGE_SEQUENCE[_i + 1] if _i + 1 < len(STAGE_SEQUENCE) else None

# Previous stage
PREVIOUS_STAGE: dict[Stage, Stage | None] = {}
for _i, _s in enumerate(STAGE_SEQUENCE):
    PREVIOUS_STAGE[_s] = STAGE_SEQUENCE[_i - 1] if _i > 0 else None

# ---------------------------------------------------------------------------
# Gate stages — require human approval unless auto-approved
# ---------------------------------------------------------------------------

GATE_STAGES: frozenset[Stage] = frozenset({
    Stage.SELECTION_AND_SCOPE,       # User picks storyline
    Stage.WORLD_VALIDATION,          # User approves world
    Stage.OUTLINE_REVIEW,            # User approves outline
    Stage.CHAPTER_APPROVAL,          # User approves each chapter
})

# Where to roll back when a gate is rejected
GATE_ROLLBACK: dict[Stage, Stage] = {
    Stage.SELECTION_AND_SCOPE: Stage.STORYLINE_GENERATION,
    Stage.WORLD_VALIDATION: Stage.CODEX_GENERATION,
    Stage.OUTLINE_REVIEW: Stage.BOOK_OUTLINE,
    Stage.CHAPTER_APPROVAL: Stage.CHAPTER_DRAFT,
}

# ---------------------------------------------------------------------------
# Chapter loop boundaries
# ---------------------------------------------------------------------------

# Stages that execute once per chapter
CHAPTER_LOOP_START = Stage.SCENE_PLANNING       # 11
CHAPTER_LOOP_END = Stage.CHAPTER_APPROVAL       # 23

CHAPTER_LOOP_STAGES: frozenset[Stage] = frozenset(
    s for s in Stage if CHAPTER_LOOP_START <= s <= CHAPTER_LOOP_END
)

# The write sub-sequence within the chapter loop
CHAPTER_WRITE_STAGES: tuple[Stage, ...] = (
    Stage.SCENE_PLANNING,
    Stage.CHAPTER_DRAFT,
    Stage.SENSORY_ENHANCEMENT,
    Stage.VOICE_CONSISTENCY,
    Stage.CHAPTER_CONTINUITY,
    Stage.PRE_REVIEW_POLISH,
)

# The review sub-sequence (can loop)
CHAPTER_REVIEW_STAGES: tuple[Stage, ...] = (
    Stage.INDEPENDENT_REVIEW,
    Stage.REVIEW_ANALYSIS,
    Stage.ENHANCEMENT_DECISION,
)

# The enhancement sub-sequence (entered on REFINE decision)
CHAPTER_ENHANCE_STAGES: tuple[Stage, ...] = (
    Stage.SURGICAL_ENHANCEMENT,
    Stage.RE_REVIEW,
    Stage.QUALITY_CONVERGENCE,
)

# Pre-chapter stages (run once)
PRE_CHAPTER_STAGES: tuple[Stage, ...] = tuple(
    s for s in Stage if s < CHAPTER_LOOP_START
)

# Post-chapter stages (run once after all chapters)
POST_CHAPTER_STAGES: tuple[Stage, ...] = tuple(
    s for s in Stage if s > CHAPTER_LOOP_END
)

# ---------------------------------------------------------------------------
# Decision stages — can trigger loops or pivots
# ---------------------------------------------------------------------------

# ENHANCEMENT_DECISION can route to:
#   PROCEED → CHAPTER_APPROVAL
#   REFINE  → SURGICAL_ENHANCEMENT (within enhancement loop)
#   REWRITE → CHAPTER_DRAFT (full rewrite)
#   HUMAN   → pause for manual intervention
DECISION_ROUTES: dict[str, Stage] = {
    "proceed": Stage.CHAPTER_APPROVAL,
    "refine": Stage.SURGICAL_ENHANCEMENT,
    "rewrite": Stage.CHAPTER_DRAFT,
}

# QUALITY_CONVERGENCE can route to:
#   converged → CHAPTER_APPROVAL
#   continue  → INDEPENDENT_REVIEW (re-enter review loop)
CONVERGENCE_ROUTES: dict[str, Stage] = {
    "converged": Stage.CHAPTER_APPROVAL,
    "continue": Stage.INDEPENDENT_REVIEW,
}

# Max decision loops before forced escalation
MAX_ENHANCEMENT_LOOPS = 3
MAX_REWRITE_ATTEMPTS = 2

# ---------------------------------------------------------------------------
# Non-critical stages (failure here doesn't block the pipeline)
# ---------------------------------------------------------------------------

NONCRITICAL_STAGES: frozenset[Stage] = frozenset({
    Stage.SERIES_ARC_DESIGN,         # Can be skipped for standalone
    Stage.STYLE_CONSISTENCY,         # Nice-to-have, not blocking
})

# ---------------------------------------------------------------------------
# Skippable stages
# ---------------------------------------------------------------------------

SKIPPABLE_STAGES: frozenset[Stage] = frozenset({
    Stage.SERIES_ARC_DESIGN,         # Skipped for standalone novels
})

# ---------------------------------------------------------------------------
# Phase groupings (for UI and reporting)
# ---------------------------------------------------------------------------

PHASE_MAP: dict[str, tuple[Stage, ...]] = {
    "0: Ideation": (
        Stage.IDEA_INTAKE,
        Stage.STORYLINE_GENERATION,
        Stage.SELECTION_AND_SCOPE,
        Stage.SERIES_ARC_DESIGN,
    ),
    "A: World-Building": (
        Stage.CODEX_GENERATION,
        Stage.CHARACTER_CREATION,
        Stage.SYSTEM_DESIGN,
        Stage.WORLD_VALIDATION,
    ),
    "B: Story Architecture": (
        Stage.BOOK_OUTLINE,
        Stage.CHAPTER_BEAT_SHEETS,
        Stage.OUTLINE_REVIEW,
    ),
    "C: Chapter Writing": (
        Stage.SCENE_PLANNING,
        Stage.CHAPTER_DRAFT,
        Stage.SENSORY_ENHANCEMENT,
    ),
    "D: Style Verification": (
        Stage.VOICE_CONSISTENCY,
    ),
    "E: Continuity Gate": (
        Stage.CHAPTER_CONTINUITY,
        Stage.PRE_REVIEW_POLISH,
    ),
    "F: Critical Review": (
        Stage.INDEPENDENT_REVIEW,
        Stage.REVIEW_ANALYSIS,
        Stage.ENHANCEMENT_DECISION,
    ),
    "G: Enhancement Loop": (
        Stage.SURGICAL_ENHANCEMENT,
        Stage.RE_REVIEW,
        Stage.QUALITY_CONVERGENCE,
    ),
    "H: Manuscript Assembly": (
        Stage.CHAPTER_APPROVAL,
        Stage.MANUSCRIPT_COMPILE,
        Stage.CONTINUITY_VERIFY,
        Stage.STYLE_CONSISTENCY,
    ),
    "I: Publishing Pipeline": (
        Stage.EPUB_GENERATION,
        Stage.PAPERBACK_FORMATTING,
        Stage.PUBLISHING_PACKAGE,
    ),
}

# ---------------------------------------------------------------------------
# Allowed transitions
# ---------------------------------------------------------------------------

TRANSITION_MAP: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset({StageStatus.RUNNING, StageStatus.SKIPPED}),
    StageStatus.RUNNING: frozenset({
        StageStatus.DONE,
        StageStatus.BLOCKED_APPROVAL,
        StageStatus.FAILED,
    }),
    StageStatus.BLOCKED_APPROVAL: frozenset({
        StageStatus.APPROVED,
        StageStatus.REJECTED,
        StageStatus.PAUSED,
    }),
    StageStatus.APPROVED: frozenset({StageStatus.DONE}),
    StageStatus.REJECTED: frozenset({StageStatus.PENDING}),
    StageStatus.PAUSED: frozenset({StageStatus.RUNNING}),
    StageStatus.RETRYING: frozenset({StageStatus.RUNNING}),
    StageStatus.FAILED: frozenset({StageStatus.RETRYING, StageStatus.PAUSED}),
    StageStatus.DONE: frozenset(),  # terminal
    StageStatus.SKIPPED: frozenset(),  # terminal
}


# ---------------------------------------------------------------------------
# Transition outcome
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionOutcome:
    """Result of a state transition."""

    stage: Stage
    status: StageStatus
    next_stage: Stage | None
    rollback_stage: Stage | None = None
    checkpoint_required: bool = False
    decision: str = "proceed"


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def gate_required(
    stage: Stage,
    hitl_required_stages: Iterable[int] | None = None,
) -> bool:
    """Check whether a stage requires human-in-the-loop approval."""
    if stage not in GATE_STAGES:
        return False
    if hitl_required_stages is not None:
        return int(stage) in frozenset(hitl_required_stages)
    return True


def is_chapter_loop_stage(stage: Stage) -> bool:
    """Check whether a stage runs per-chapter."""
    return stage in CHAPTER_LOOP_STAGES


def default_rollback_stage(stage: Stage) -> Stage:
    """Return the configured rollback target, or the previous stage."""
    if stage in GATE_ROLLBACK:
        return GATE_ROLLBACK[stage]
    prev = PREVIOUS_STAGE.get(stage)
    return prev if prev is not None else stage


def stage_name(stage: Stage) -> str:
    """Human-readable name for a stage."""
    return stage.name.lower()


def stage_phase(stage: Stage) -> str:
    """Return the phase name for a stage."""
    for phase_name, stages in PHASE_MAP.items():
        if stage in stages:
            return phase_name
    return "Unknown"


# ---------------------------------------------------------------------------
# State machine: advance()
# ---------------------------------------------------------------------------

def advance(
    stage: Stage,
    status: StageStatus,
    event: TransitionEvent | str,
    *,
    hitl_required_stages: Iterable[int] | None = None,
    rollback_stage: Stage | None = None,
) -> TransitionOutcome:
    """Compute the next state given current stage, status, and event.

    This is a pure function — no side effects. The caller is responsible
    for persisting the resulting state.

    Parameters
    ----------
    stage : Stage
        Current pipeline stage.
    status : StageStatus
        Current status of the stage.
    event : TransitionEvent or str
        The event that occurred.
    hitl_required_stages : iterable of int, optional
        Stage numbers that require human approval. If None, all gate stages
        require approval.
    rollback_stage : Stage, optional
        Override the default rollback target for rejected gates.

    Returns
    -------
    TransitionOutcome
        The resulting state after the transition.

    Raises
    ------
    ValueError
        If the transition is not supported.
    """
    event = TransitionEvent(event)
    target_rollback = rollback_stage or default_rollback_stage(stage)

    # --- START: begin execution ---
    if event is TransitionEvent.START and status in {
        StageStatus.PENDING,
        StageStatus.RETRYING,
        StageStatus.PAUSED,
    }:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.RUNNING,
            next_stage=stage,
        )

    # --- SKIP: bypass this stage ---
    if event is TransitionEvent.SKIP and status is StageStatus.PENDING:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.SKIPPED,
            next_stage=NEXT_STAGE[stage],
            checkpoint_required=True,
        )

    # --- SUCCEED while RUNNING ---
    if event is TransitionEvent.SUCCEED and status is StageStatus.RUNNING:
        if gate_required(stage, hitl_required_stages):
            return TransitionOutcome(
                stage=stage,
                status=StageStatus.BLOCKED_APPROVAL,
                next_stage=stage,
                decision="block",
            )
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.DONE,
            next_stage=NEXT_STAGE[stage],
            checkpoint_required=True,
        )

    # --- APPROVE while BLOCKED ---
    if event is TransitionEvent.APPROVE and status is StageStatus.BLOCKED_APPROVAL:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.DONE,
            next_stage=NEXT_STAGE[stage],
            checkpoint_required=True,
        )

    # --- REJECT while BLOCKED → rollback ---
    if event is TransitionEvent.REJECT and status is StageStatus.BLOCKED_APPROVAL:
        return TransitionOutcome(
            stage=target_rollback,
            status=StageStatus.PENDING,
            next_stage=target_rollback,
            rollback_stage=target_rollback,
            checkpoint_required=True,
            decision="rollback",
        )

    # --- TIMEOUT while BLOCKED → pause ---
    if event is TransitionEvent.TIMEOUT and status is StageStatus.BLOCKED_APPROVAL:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.PAUSED,
            next_stage=stage,
            checkpoint_required=True,
            decision="block",
        )

    # --- FAIL while RUNNING ---
    if event is TransitionEvent.FAIL and status is StageStatus.RUNNING:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.FAILED,
            next_stage=stage,
            checkpoint_required=True,
            decision="retry",
        )

    # --- RETRY while FAILED ---
    if event is TransitionEvent.RETRY and status is StageStatus.FAILED:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.RETRYING,
            next_stage=stage,
            decision="retry",
        )

    # --- RESUME while PAUSED ---
    if event is TransitionEvent.RESUME and status is StageStatus.PAUSED:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.RUNNING,
            next_stage=stage,
        )

    # --- PAUSE while FAILED ---
    if event is TransitionEvent.PAUSE and status is StageStatus.FAILED:
        return TransitionOutcome(
            stage=stage,
            status=StageStatus.PAUSED,
            next_stage=stage,
            checkpoint_required=True,
            decision="block",
        )

    raise ValueError(
        f"Unsupported transition: stage={stage.name} ({int(stage)}), "
        f"status={status.value}, event={event.value}"
    )
