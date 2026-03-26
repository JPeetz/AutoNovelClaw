"""Pipeline runner — checkpoint/resume, rollback, evolution, chapter-loop orchestration.

This is the outer orchestration layer. It sequences stages, handles checkpoints,
manages the chapter loop with review/enhance sub-loops, and integrates with the
evolution (self-learning) system.

The ``execute_stage()`` function from ``executor.py`` handles the actual work
for each individual stage. The runner handles the *flow*.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonovelclaw.config import NovelClawConfig, ProjectMode
from autonovelclaw.knowledge_base import KnowledgeBase
from autonovelclaw.llm import create_llm_client
from autonovelclaw.llm.client import BaseLLMClient
from autonovelclaw.prompts import PromptManager
from autonovelclaw.pipeline.stages import (
    CHAPTER_LOOP_STAGES,
    CHAPTER_WRITE_STAGES,
    CHAPTER_REVIEW_STAGES,
    CHAPTER_ENHANCE_STAGES,
    DECISION_ROUTES,
    CONVERGENCE_ROUTES,
    GATE_STAGES,
    NONCRITICAL_STAGES,
    POST_CHAPTER_STAGES,
    PRE_CHAPTER_STAGES,
    SKIPPABLE_STAGES,
    Stage,
    StageStatus,
    advance,
    gate_required,
    stage_name,
    stage_phase,
)
from autonovelclaw.pipeline.contracts import (
    CONTRACTS,
    validate_inputs,
    validate_outputs,
    max_retries_for,
)

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------

class Checkpoint:
    """Atomic checkpoint file for pipeline resume.

    Stores the last completed stage, chapter progress, loop counters,
    and all artifact references. Written atomically via temp+rename.
    """

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "checkpoint.json"
        self.data: dict[str, Any] = {
            "run_id": "",
            "last_completed_stage": -1,
            "last_completed_name": "",
            "current_chapter": 0,
            "total_chapters": 0,
            "enhancement_loops": 0,
            "rewrite_count": 0,
            "last_approved_chapter": 0,
            "stage_statuses": {},
            "artifacts": {},
            "decisions": [],
            "started_at": "",
            "updated_at": "",
        }
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Checkpoint load failed: %s — starting fresh", exc)

    def save(self) -> None:
        """Write checkpoint atomically (temp file → rename)."""
        self.data["updated_at"] = _utcnow_iso()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")
        tmp.rename(self.path)

    # Convenience accessors
    @property
    def run_id(self) -> str:
        return self.data.get("run_id", "")

    @run_id.setter
    def run_id(self, v: str) -> None:
        self.data["run_id"] = v

    @property
    def current_chapter(self) -> int:
        return self.data.get("current_chapter", 0)

    @current_chapter.setter
    def current_chapter(self, v: int) -> None:
        self.data["current_chapter"] = v

    @property
    def total_chapters(self) -> int:
        return self.data.get("total_chapters", 0)

    @total_chapters.setter
    def total_chapters(self, v: int) -> None:
        self.data["total_chapters"] = v

    @property
    def enhancement_loops(self) -> int:
        return self.data.get("enhancement_loops", 0)

    @enhancement_loops.setter
    def enhancement_loops(self, v: int) -> None:
        self.data["enhancement_loops"] = v

    @property
    def rewrite_count(self) -> int:
        return self.data.get("rewrite_count", 0)

    @rewrite_count.setter
    def rewrite_count(self, v: int) -> None:
        self.data["rewrite_count"] = v

    @property
    def last_approved_chapter(self) -> int:
        return self.data.get("last_approved_chapter", 0)

    @last_approved_chapter.setter
    def last_approved_chapter(self, v: int) -> None:
        self.data["last_approved_chapter"] = v

    @property
    def artifacts(self) -> dict[str, Any]:
        return self.data.setdefault("artifacts", {})

    @property
    def decisions(self) -> list[dict[str, Any]]:
        return self.data.setdefault("decisions", [])

    def stage_status(self, key: str) -> StageStatus | None:
        raw = self.data.get("stage_statuses", {}).get(key)
        return StageStatus(raw) if raw else None

    def set_stage_status(self, key: str, status: StageStatus) -> None:
        self.data.setdefault("stage_statuses", {})[key] = status.value
        self.save()

    def is_done(self, key: str) -> bool:
        return self.stage_status(key) in (StageStatus.DONE, StageStatus.SKIPPED)

    def store_artifact(self, key: str, value: Any) -> None:
        self.artifacts[key] = value
        self.save()

    def get_artifact(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)

    def record_decision(self, stage_key: str, decision: str, rationale: str) -> None:
        self.decisions.append({
            "stage": stage_key,
            "decision": decision,
            "rationale": rationale,
            "chapter": self.current_chapter,
            "timestamp": _utcnow_iso(),
        })
        self.save()


# ---------------------------------------------------------------------------
# Stage result
# ---------------------------------------------------------------------------

class StageResult:
    """Result from executing a single stage."""

    def __init__(
        self,
        stage: Stage,
        status: StageStatus,
        *,
        error: str = "",
        duration_sec: float = 0.0,
        artifacts_produced: list[str] | None = None,
    ) -> None:
        self.stage = stage
        self.status = status
        self.error = error
        self.duration_sec = duration_sec
        self.artifacts_produced = artifacts_produced or []


# ---------------------------------------------------------------------------
# Pipeline Runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """Orchestrate the full novel-creation pipeline with checkpoint/resume.

    Parameters
    ----------
    config : NovelClawConfig
        Full configuration.
    auto_approve : bool
        If True, skip all human gates.
    topic : str
        The user's raw story idea.
    run_dir : Path, optional
        Resume from an existing run directory. If None, a new one is created.
    """

    def __init__(
        self,
        config: NovelClawConfig,
        *,
        auto_approve: bool = False,
        topic: str = "",
        run_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.auto_approve = auto_approve
        self.topic = topic

        # Run directory
        if run_dir and run_dir.exists():
            self.run_dir = run_dir
            logger.info("Resuming from existing run: %s", run_dir)
        else:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.run_dir = Path(config.runtime.output_dir) / f"nc-{ts}-{config.project_name}"

        self.run_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ("chapters", "reviews", "world", "deliverables", "evolution"):
            (self.run_dir / subdir).mkdir(exist_ok=True)

        # Core components
        self.ckpt = Checkpoint(self.run_dir)
        if not self.ckpt.data.get("started_at"):
            self.ckpt.data["started_at"] = _utcnow_iso()
            self.ckpt.run_id = f"nc-{ts if not run_dir else 'resume'}"
            self.ckpt.save()

        self.llm = create_llm_client(config.llm)
        self.kb = KnowledgeBase(
            root=Path(config.knowledge_base.root),
            categories=config.knowledge_base.categories,
        )
        self.prompts = PromptManager(
            custom_file=getattr(config, "prompts_custom_file", None),
        )

        # Store topic
        if topic:
            self.ckpt.store_artifact("raw_topic", topic)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> Path:
        """Execute the full pipeline. Returns path to deliverables."""
        from rich.console import Console
        con = Console()

        con.print("\n[bold cyan]╔══════════════════════════════════════════╗[/]")
        con.print("[bold cyan]║     AutoNovelClaw — Novel Pipeline       ║[/]")
        con.print("[bold cyan]╚══════════════════════════════════════════╝[/]\n")
        con.print(f"  Run directory: [dim]{self.run_dir}[/]\n")

        results: list[StageResult] = []

        # --- Pre-chapter stages ---
        for stage in PRE_CHAPTER_STAGES:
            key = stage_name(stage)
            if self.ckpt.is_done(key):
                con.print(f"  [dim]✓ {key}[/]")
                continue

            # Skip series arc for standalone
            if stage in SKIPPABLE_STAGES and self._should_skip(stage):
                self.ckpt.set_stage_status(key, StageStatus.SKIPPED)
                con.print(f"  [dim]⊘ {key} (skipped)[/]")
                continue

            result = self._execute_with_gate(stage, key, con)
            results.append(result)
            if result.status == StageStatus.FAILED and stage not in NONCRITICAL_STAGES:
                con.print(f"\n[bold red]Pipeline halted at {key}: {result.error}[/]")
                return self.run_dir / "deliverables"

        # --- Chapter loop ---
        total_ch = self.ckpt.total_chapters or self.config.novel.target.chapter_count_min
        self.ckpt.total_chapters = total_ch
        self.ckpt.save()

        for ch_num in range(1, total_ch + 1):
            if ch_num <= self.ckpt.last_approved_chapter:
                con.print(f"\n  [dim]✓ Chapter {ch_num} (approved)[/]")
                continue

            con.print(f"\n[bold green]━━━ Chapter {ch_num}/{total_ch} ━━━[/]\n")
            self.ckpt.current_chapter = ch_num
            self.ckpt.enhancement_loops = 0
            self.ckpt.rewrite_count = 0
            self.ckpt.save()

            ch_result = self._run_chapter(ch_num, con)
            if ch_result and ch_result.status == StageStatus.FAILED:
                con.print(f"\n[bold red]Pipeline halted at chapter {ch_num}[/]")
                return self.run_dir / "deliverables"

        # --- Post-chapter stages ---
        con.print("\n[bold cyan]━━━ Manuscript Assembly & Publishing ━━━[/]\n")
        for stage in POST_CHAPTER_STAGES:
            key = stage_name(stage)
            if self.ckpt.is_done(key):
                con.print(f"  [dim]✓ {key}[/]")
                continue
            result = self._execute_with_gate(stage, key, con)
            results.append(result)

        # --- Summary ---
        deliverables = self.run_dir / "deliverables"
        con.print(f"\n[bold green]✅ Pipeline complete! Deliverables: {deliverables}[/]")

        tokens = self.llm.total_tokens
        con.print(f"[dim]Tokens: {tokens['total']:,} (in: {tokens['input']:,}, out: {tokens['output']:,})[/]\n")

        self._write_summary(results)
        self.llm.close()
        return deliverables

    # ------------------------------------------------------------------
    # Chapter loop
    # ------------------------------------------------------------------

    def _run_chapter(self, ch_num: int, con: Any) -> StageResult | None:
        """Run the full write → review → enhance loop for one chapter."""

        # --- Write stages ---
        for stage in CHAPTER_WRITE_STAGES:
            key = f"{stage_name(stage)}_ch{ch_num}"
            if self.ckpt.is_done(key):
                con.print(f"  [dim]✓ {key}[/]")
                continue
            result = self._execute_stage(stage, key, con)
            if result.status == StageStatus.FAILED:
                return result

        # --- Review / enhance loop ---
        max_total = self.config.review.max_enhancement_loops + self.config.review.max_rewrite_attempts

        for loop_idx in range(max_total):
            # Review stages
            for stage in CHAPTER_REVIEW_STAGES:
                key = f"{stage_name(stage)}_ch{ch_num}_loop{loop_idx}"
                if not self.ckpt.is_done(key):
                    result = self._execute_stage(stage, key, con)
                    if result.status == StageStatus.FAILED:
                        return result

            # Check decision
            decision = self.ckpt.get_artifact(f"decision_ch{ch_num}", "proceed")

            if decision == "proceed":
                con.print(f"  [green]✓ Chapter {ch_num} APPROVED (rating meets threshold)[/]")
                break

            elif decision == "refine":
                self.ckpt.enhancement_loops += 1
                self.ckpt.save()
                con.print(
                    f"  [yellow]↻ REFINE — Enhancement pass "
                    f"{self.ckpt.enhancement_loops}/{self.config.review.max_enhancement_loops}[/]"
                )

                for stage in CHAPTER_ENHANCE_STAGES:
                    key = f"{stage_name(stage)}_ch{ch_num}_loop{loop_idx}"
                    if not self.ckpt.is_done(key):
                        result = self._execute_stage(stage, key, con)
                        if result.status == StageStatus.FAILED:
                            return result

                # Check convergence
                converged = self.ckpt.get_artifact(f"converged_ch{ch_num}", False)
                if converged:
                    con.print(f"  [green]✓ Chapter {ch_num} converged[/]")
                    break

            elif decision == "rewrite":
                self.ckpt.rewrite_count += 1
                self.ckpt.save()
                con.print(
                    f"  [red]⟳ REWRITE — Attempt "
                    f"{self.ckpt.rewrite_count}/{self.config.review.max_rewrite_attempts}[/]"
                )
                # Re-run chapter draft and sensory enhancement
                for stage in (Stage.CHAPTER_DRAFT, Stage.SENSORY_ENHANCEMENT):
                    key = f"{stage_name(stage)}_ch{ch_num}_rw{self.ckpt.rewrite_count}"
                    result = self._execute_stage(stage, key, con)
                    if result.status == StageStatus.FAILED:
                        return result

            elif decision == "human_escalation":
                con.print(
                    f"  [bold red]⚠ Chapter {ch_num} requires human review — "
                    f"loops exhausted[/]"
                )
                if not self.auto_approve:
                    input("  Press Enter after reviewing to continue...")
                break

        # --- Chapter approval gate ---
        approval_key = f"chapter_approval_ch{ch_num}"
        if not self.ckpt.is_done(approval_key):
            result = self._execute_with_gate(Stage.CHAPTER_APPROVAL, approval_key, con)
            if result.status == StageStatus.FAILED:
                return result

        self.ckpt.last_approved_chapter = ch_num
        self.ckpt.save()
        return None

    # ------------------------------------------------------------------
    # Stage execution helpers
    # ------------------------------------------------------------------

    def _execute_stage(self, stage: Stage, key: str, con: Any) -> StageResult:
        """Execute a single stage with retry logic."""
        import time

        con.print(f"  ▶ {key}...", end=" ")
        self.ckpt.set_stage_status(key, StageStatus.RUNNING)

        max_retries = max_retries_for(stage)
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                start = time.monotonic()

                # Import and call the executor
                from autonovelclaw.pipeline.executor import execute_stage
                execute_stage(
                    stage=stage,
                    config=self.config,
                    llm=self.llm,
                    ckpt=self.ckpt,
                    kb=self.kb,
                    prompts=self.prompts,
                    run_dir=self.run_dir,
                    auto_approve=self.auto_approve,
                )

                duration = time.monotonic() - start
                self.ckpt.set_stage_status(key, StageStatus.DONE)
                con.print(f"[green]✓[/] [dim]({duration:.1f}s)[/]")
                return StageResult(stage, StageStatus.DONE, duration_sec=duration)

            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    con.print(f"[yellow]retry {attempt + 1}/{max_retries}[/]", end=" ")
                    logger.warning("Stage %s attempt %d failed: %s", key, attempt + 1, exc)
                    continue
                break

        self.ckpt.set_stage_status(key, StageStatus.FAILED)
        con.print(f"[red]✗ {last_error[:80]}[/]")
        logger.error("Stage %s failed after %d attempts: %s", key, max_retries + 1, last_error)
        return StageResult(stage, StageStatus.FAILED, error=last_error)

    def _execute_with_gate(self, stage: Stage, key: str, con: Any) -> StageResult:
        """Execute a stage, then handle gate approval if needed."""
        result = self._execute_stage(stage, key, con)
        if result.status != StageStatus.DONE:
            return result

        if stage in GATE_STAGES and not self.auto_approve:
            if self.config.mode != ProjectMode.FULL_AUTO:
                con.print(f"\n  [bold yellow]⏸ GATE: {key}[/]")
                con.print("  [yellow]Review artifacts. Type 'approve' or 'reject':[/]")
                response = input("  > ").strip().lower()
                if response == "reject":
                    from autonovelclaw.pipeline.stages import GATE_ROLLBACK
                    rollback = GATE_ROLLBACK.get(stage, stage)
                    self.ckpt.set_stage_status(key, StageStatus.REJECTED)
                    self.ckpt.record_decision(key, "rejected", f"User rejected → rollback to {stage_name(rollback)}")
                    con.print(f"  [red]✗ Rejected → rolling back to {stage_name(rollback)}[/]")
                    return StageResult(stage, StageStatus.FAILED, error="Gate rejected by user")

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_skip(self, stage: Stage) -> bool:
        """Check if a stage should be skipped based on config/state."""
        if stage == Stage.SERIES_ARC_DESIGN:
            scope = self.ckpt.get_artifact("novel_scope", "standalone")
            return scope == "standalone"
        return False

    def _write_summary(self, results: list[StageResult]) -> None:
        """Write pipeline summary to artifact directory."""
        summary = {
            "run_id": self.ckpt.run_id,
            "started_at": self.ckpt.data.get("started_at"),
            "completed_at": _utcnow_iso(),
            "stages_total": len(self.ckpt.data.get("stage_statuses", {})),
            "stages_done": sum(
                1 for v in self.ckpt.data.get("stage_statuses", {}).values()
                if v in ("done", "skipped")
            ),
            "chapters": self.ckpt.total_chapters,
            "chapters_approved": self.ckpt.last_approved_chapter,
            "total_decisions": len(self.ckpt.decisions),
            "token_usage": self.llm.total_tokens,
        }
        (self.run_dir / "pipeline_summary.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
