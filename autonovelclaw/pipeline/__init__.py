"""Pipeline sub-package — orchestration, state machine, execution."""

from autonovelclaw.pipeline.stages import (
    Stage,
    StageStatus,
    TransitionEvent,
    TransitionOutcome,
    advance,
    gate_required,
    is_chapter_loop_stage,
    GATE_STAGES,
    CHAPTER_LOOP_STAGES,
    PRE_CHAPTER_STAGES,
    POST_CHAPTER_STAGES,
    PHASE_MAP,
)
from autonovelclaw.pipeline.contracts import (
    StageContract,
    CONTRACTS,
    validate_inputs,
    validate_outputs,
    get_contract,
    max_retries_for,
)

__all__ = [
    "Stage",
    "StageStatus",
    "TransitionEvent",
    "TransitionOutcome",
    "advance",
    "gate_required",
    "is_chapter_loop_stage",
    "GATE_STAGES",
    "CHAPTER_LOOP_STAGES",
    "PRE_CHAPTER_STAGES",
    "POST_CHAPTER_STAGES",
    "PHASE_MAP",
    "StageContract",
    "CONTRACTS",
    "validate_inputs",
    "validate_outputs",
    "get_contract",
    "max_retries_for",
]
