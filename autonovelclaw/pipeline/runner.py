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

        # Pipeline monitor
        from autonovelclaw.monitor import PipelineMonitor
        self.monitor = PipelineMonitor(
            self.run_dir,
            notify_on_fail=True,
            notify_webhook=getattr(config.runtime, "notify_webhook", ""),
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

        self.monitor.on_pipeline_start(self.ckpt.run_id)
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
                self.monitor.on_pipeline_fail(f"Halted at {key}: {result.error}")
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
                self.monitor.on_pipeline_fail(f"Halted at chapter {ch_num}")
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

        self.monitor.on_token_update(tokens)
        self.monitor.on_pipeline_complete()

        # Check for health warnings
        warnings = self.monitor.check_health_warnings()
        if warnings:
            con.print("[yellow]Health warnings:[/]")
            for w in warnings:
                con.print(f"  ⚠️  {w}")

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

        # Notify monitor
        rating = float(self.ckpt.get_artifact(f"review_1_rating_ch{ch_num}", 0))
        self.monitor.on_chapter_complete(ch_num, rating=rating)

        return None

    # ------------------------------------------------------------------
    # Stage execution helpers
    # ------------------------------------------------------------------

    def _execute_stage(self, stage: Stage, key: str, con: Any) -> StageResult:
        """Execute a single stage with retry logic and monitor hooks."""
        import time
        import subprocess

        con.print(f"  ▶ {key}...", end=" ")
        self.ckpt.set_stage_status(key, StageStatus.RUNNING)
        self.monitor.on_stage_start(key, chapter=self.ckpt.current_chapter)

        max_retries = max_retries_for(stage)
        last_error = ""
        attempt = 0

        while attempt <= max_retries:
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
                self.monitor.on_stage_complete(key, duration=duration,
                                               chapter=self.ckpt.current_chapter)
                self.monitor.on_token_update(self.llm.total_tokens)
                con.print(f"[green]✓[/] [dim]({duration:.1f}s)[/]")
                return StageResult(stage, StageStatus.DONE, duration_sec=duration)

            except subprocess.TimeoutExpired as exc:
                last_error = f"Timeout after {getattr(exc, 'timeout', '?')}s"
                self.monitor.on_timeout(key, getattr(exc, 'timeout', 0),
                                        chapter=self.ckpt.current_chapter)
                attempt += 1
                if attempt <= max_retries:
                    self.monitor.on_retry(key, attempt, max_retries,
                                          chapter=self.ckpt.current_chapter)
                    con.print(f"[yellow]timeout → retry {attempt}/{max_retries}[/]", end=" ")
                    continue
                break

            except Exception as exc:
                last_error = str(exc)
                err_lower = last_error.lower()

                # --- Usage limit: auto-wait and resume (NO attempt increment) ---
                from autonovelclaw.llm.cli_client import UsageLimitError
                if isinstance(exc, UsageLimitError):
                    wait_sec = exc.wait_sec
                    wait_min = wait_sec // 60
                    self.monitor.on_rate_limit(key, wait_sec=wait_sec,
                                               chapter=self.ckpt.current_chapter)
                    con.print(
                        f"\n  [bold yellow]⏸ Usage limit reached — "
                        f"auto-resuming in {wait_min} minutes[/]"
                    )
                    con.print(f"  [dim]Pipeline paused at {key}. "
                              f"Checkpoint saved. Will retry automatically.[/]")
                    self.ckpt.save()

                    # Wait with countdown
                    import time as _t
                    remaining = wait_sec
                    while remaining > 0:
                        mins = remaining // 60
                        secs = remaining % 60
                        print(f"\r  ⏳ Resuming in {mins:02d}:{secs:02d}  ", end="", flush=True)
                        _t.sleep(min(30, remaining))
                        remaining -= 30
                    print("\r  ▶ Resuming...                    ")

                    # Don't increment attempt — retry indefinitely for usage limits
                    continue

                # --- Rate limit (non-usage): shorter wait ---
                if any(kw in err_lower for kw in ["rate limit", "429", "too many requests"]):
                    self.monitor.on_rate_limit(key, wait_sec=30,
                                               chapter=self.ckpt.current_chapter)

                attempt += 1
                if attempt <= max_retries:
                    self.monitor.on_retry(key, attempt, max_retries,
                                          chapter=self.ckpt.current_chapter)
                    con.print(f"[yellow]retry {attempt}/{max_retries}[/]", end=" ")
                    logger.warning("Stage %s attempt %d failed: %s", key, attempt, exc)

                    # Back off on rate limits
                    if "rate limit" in err_lower or "429" in err_lower:
                        import time as _t
                        _t.sleep(30)

                    continue
                break

        self.ckpt.set_stage_status(key, StageStatus.FAILED)
        self.monitor.on_stage_fail(key, error=last_error,
                                   chapter=self.ckpt.current_chapter)
        con.print(f"[red]✗ {last_error[:80]}[/]")
        logger.error("Stage %s failed after %d attempts: %s", key, max_retries + 1, last_error)
        return StageResult(stage, StageStatus.FAILED, error=last_error)

    def _execute_with_gate(self, stage: Stage, key: str, con: Any) -> StageResult:
        """Execute a stage. Gates auto-proceed after storyline selection.

        The only interactive point is Stage 2 (SELECTION_AND_SCOPE) where
        the user picks their storyline and elaborates. All other gates
        auto-proceed. Review feedback is displayed for awareness but
        doesn't block the pipeline.
        """
        result = self._execute_stage(stage, key, con)
        if result.status != StageStatus.DONE:
            return result

        # Display review feedback (non-blocking, informational)
        if stage == Stage.INDEPENDENT_REVIEW:
            self._display_review_summary(con)
        elif stage == Stage.RE_REVIEW:
            self._display_review_summary(con, reviewer=2)

        # All gates auto-proceed (user interaction was at storyline selection)
        return result

    def _display_review_summary(self, con: Any, reviewer: int = 1) -> None:
        """Display review feedback prominently but non-blocking."""
        ch = self.ckpt.current_chapter
        if reviewer == 1:
            rating = self.ckpt.get_artifact(f"review_1_rating_ch{ch}", 0)
            parsed = self.ckpt.get_artifact(f"review_1_parsed_ch{ch}", {})
        else:
            rating = self.ckpt.get_artifact(f"review_2_rating_ch{ch}", 0)
            parsed = self.ckpt.get_artifact(f"review_2_parsed_ch{ch}", {})

        if not rating:
            return

        reviewer_name = "Critic" if reviewer == 1 else "Reader"
        colour = "green" if rating >= 9.0 else ("yellow" if rating >= 7.5 else "red")

        con.print(f"\n    [bold {colour}]📖 {reviewer_name} Review — Ch{ch}: {rating}/10[/]")

        # Show strengths
        strengths = parsed.get("strengths", [])
        if strengths:
            con.print(f"    [green]✓ {strengths[0][:80]}[/]")
            if len(strengths) > 1:
                con.print(f"    [green]✓ {strengths[1][:80]}[/]")

        # Show weaknesses
        weaknesses = parsed.get("weaknesses", [])
        if weaknesses:
            con.print(f"    [yellow]△ {weaknesses[0][:80]}[/]")

        # Show drag/confusion for reader
        if reviewer == 2:
            drags = parsed.get("drag_points", [])
            if drags:
                con.print(f"    [yellow]⏳ Drag: {drags[0][:60]}[/]")
            confusion = parsed.get("confusion_points", [])
            if confusion:
                con.print(f"    [yellow]? Confusion: {confusion[0][:60]}[/]")

        con.print()

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
