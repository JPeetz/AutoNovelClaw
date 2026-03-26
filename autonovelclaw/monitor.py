"""Pipeline monitor — real-time health tracking and user notification.

Runs alongside the pipeline to detect failures, rate limits, timeouts,
and credit exhaustion. Writes a live status file and optionally sends
notifications via terminal bell, file, or webhook.

Usage: The runner calls monitor hooks at key points::

    monitor = PipelineMonitor(run_dir, config)
    monitor.on_stage_start("chapter_draft", chapter=3)
    monitor.on_stage_complete("chapter_draft", duration=45.2, chapter=3)
    monitor.on_stage_fail("chapter_draft", error="timeout", chapter=3)
    monitor.on_rate_limit(wait_sec=30)
    monitor.on_retry(stage="chapter_draft", attempt=2, max_attempts=3)

The monitor writes ``pipeline_health.json`` to the run directory, updated
after every event. External watchers can poll this file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageEvent:
    """A single pipeline event for the monitor log."""
    timestamp: str
    event_type: str    # "start", "complete", "fail", "retry", "rate_limit", "timeout", "warning"
    stage: str
    chapter: int = 0
    detail: str = ""
    duration_sec: float = 0.0


@dataclass
class PipelineHealth:
    """Live health status of the pipeline."""
    run_id: str = ""
    status: str = "running"         # "running", "paused", "failed", "complete"
    current_stage: str = ""
    current_chapter: int = 0
    total_chapters: int = 0
    chapters_complete: int = 0
    stages_complete: int = 0
    stages_failed: int = 0
    retries_total: int = 0
    rate_limits_hit: int = 0
    timeouts_hit: int = 0
    total_duration_sec: float = 0.0
    estimated_tokens_used: int = 0
    last_error: str = ""
    last_event: str = ""
    started_at: str = ""
    updated_at: str = ""
    events: list[StageEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep only last 50 events in the status file
        d["events"] = d["events"][-50:]
        return d


class PipelineMonitor:
    """Real-time pipeline health monitor with notification support.

    Parameters
    ----------
    run_dir : Path
        The pipeline run directory.
    notify_on_fail : bool
        Print a visible alert on failure (terminal bell + colour).
    notify_webhook : str
        Optional webhook URL to POST failure notifications to.
    health_file : str
        Name of the health status file in run_dir.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        notify_on_fail: bool = True,
        notify_webhook: str = "",
        health_file: str = "pipeline_health.json",
    ) -> None:
        self.run_dir = run_dir
        self.notify_on_fail = notify_on_fail
        self.notify_webhook = notify_webhook
        self._health_path = run_dir / health_file
        self._start_time = time.monotonic()

        self.health = PipelineHealth(
            started_at=self._now(),
            updated_at=self._now(),
        )

    # ------------------------------------------------------------------
    # Event hooks — called by the runner
    # ------------------------------------------------------------------

    def on_pipeline_start(self, run_id: str, total_chapters: int = 0) -> None:
        self.health.run_id = run_id
        self.health.total_chapters = total_chapters
        self.health.status = "running"
        self._record("start", "pipeline", detail=f"Pipeline started, {total_chapters} chapters")
        self._save()

    def on_stage_start(self, stage: str, chapter: int = 0) -> None:
        self.health.current_stage = stage
        self.health.current_chapter = chapter
        self._record("start", stage, chapter=chapter)
        self._save()

    def on_stage_complete(self, stage: str, duration: float = 0.0, chapter: int = 0) -> None:
        self.health.stages_complete += 1
        self._record("complete", stage, chapter=chapter, duration_sec=duration,
                      detail=f"Completed in {duration:.1f}s")
        self._save()

    def on_stage_fail(self, stage: str, error: str = "", chapter: int = 0) -> None:
        self.health.stages_failed += 1
        self.health.last_error = error[:500]
        self._record("fail", stage, chapter=chapter, detail=error[:300])

        if self.notify_on_fail:
            self._alert(f"STAGE FAILED: {stage} (ch{chapter}): {error[:200]}")

        if self.notify_webhook:
            self._webhook_notify(f"AutoNovelClaw FAILED at {stage}: {error[:200]}")

        self._save()

    def on_retry(self, stage: str, attempt: int, max_attempts: int, chapter: int = 0) -> None:
        self.health.retries_total += 1
        detail = f"Retry {attempt}/{max_attempts}"
        self._record("retry", stage, chapter=chapter, detail=detail)

        if attempt >= max_attempts:
            self._alert(f"FINAL RETRY: {stage} (ch{chapter}) — attempt {attempt}/{max_attempts}")

        self._save()

    def on_rate_limit(self, stage: str = "", wait_sec: float = 0, chapter: int = 0) -> None:
        self.health.rate_limits_hit += 1
        detail = f"Rate limited, waiting {wait_sec:.0f}s"
        self._record("rate_limit", stage, chapter=chapter, detail=detail)
        self._alert(f"RATE LIMITED at {stage}: waiting {wait_sec:.0f}s "
                     f"(total rate limits: {self.health.rate_limits_hit})")
        self._save()

    def on_timeout(self, stage: str, timeout_sec: float, chapter: int = 0) -> None:
        self.health.timeouts_hit += 1
        detail = f"Timed out after {timeout_sec:.0f}s"
        self._record("timeout", stage, chapter=chapter, detail=detail)
        self._alert(f"TIMEOUT at {stage} (ch{chapter}): {timeout_sec:.0f}s limit exceeded "
                     f"(total timeouts: {self.health.timeouts_hit})")
        self._save()

    def on_chapter_complete(self, chapter: int, rating: float = 0) -> None:
        self.health.chapters_complete = chapter
        detail = f"Chapter {chapter} approved"
        if rating > 0:
            detail += f" (rating: {rating:.1f}/10)"
        self._record("complete", f"chapter_{chapter}", chapter=chapter, detail=detail)
        self._save()

    def on_token_update(self, tokens: dict[str, int]) -> None:
        self.health.estimated_tokens_used = tokens.get("total", 0)

    def on_pipeline_complete(self) -> None:
        self.health.status = "complete"
        elapsed = time.monotonic() - self._start_time
        self.health.total_duration_sec = elapsed
        self._record("complete", "pipeline",
                      detail=f"Pipeline complete in {elapsed:.0f}s "
                             f"({self.health.chapters_complete} chapters)")
        self._save()

        self._alert(
            f"✅ PIPELINE COMPLETE: {self.health.chapters_complete} chapters, "
            f"{elapsed / 60:.0f} minutes, {self.health.estimated_tokens_used:,} tokens",
            is_error=False,
        )

    def on_pipeline_fail(self, error: str) -> None:
        self.health.status = "failed"
        self.health.last_error = error[:500]
        elapsed = time.monotonic() - self._start_time
        self.health.total_duration_sec = elapsed
        self._record("fail", "pipeline", detail=error[:300])
        self._save()

        self._alert(f"❌ PIPELINE FAILED after {elapsed / 60:.0f} minutes: {error[:200]}")

        if self.notify_webhook:
            self._webhook_notify(f"AutoNovelClaw pipeline FAILED: {error[:200]}")

    # ------------------------------------------------------------------
    # Warning for approaching limits
    # ------------------------------------------------------------------

    def check_health_warnings(self) -> list[str]:
        """Check for warning conditions and return any alerts."""
        warnings = []

        if self.health.retries_total > 10:
            warnings.append(
                f"High retry count ({self.health.retries_total}) — "
                f"model may be overloaded or prompts too long"
            )

        if self.health.rate_limits_hit > 5:
            warnings.append(
                f"Frequent rate limits ({self.health.rate_limits_hit}) — "
                f"consider slowing down or switching to off-peak hours"
            )

        if self.health.timeouts_hit > 3:
            warnings.append(
                f"Multiple timeouts ({self.health.timeouts_hit}) — "
                f"consider increasing timeout_sec in config"
            )

        if self.health.stages_failed > 5:
            warnings.append(
                f"Many failed stages ({self.health.stages_failed}) — "
                f"pipeline may be unstable"
            )

        return warnings

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record(self, event_type: str, stage: str, **kwargs: Any) -> None:
        event = StageEvent(
            timestamp=self._now(),
            event_type=event_type,
            stage=stage,
            chapter=kwargs.get("chapter", 0),
            detail=kwargs.get("detail", ""),
            duration_sec=kwargs.get("duration_sec", 0.0),
        )
        self.health.events.append(event)
        self.health.last_event = f"{event_type}: {stage}"
        self.health.updated_at = self._now()

    def _save(self) -> None:
        """Write health status to disk atomically."""
        try:
            tmp = self._health_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.health.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            tmp.rename(self._health_path)
        except OSError as exc:
            logger.debug("Could not write health file: %s", exc)

    def _alert(self, message: str, is_error: bool = True) -> None:
        """Print a visible alert to the terminal."""
        if not self.notify_on_fail:
            return

        # Terminal bell
        sys.stderr.write("\a")
        sys.stderr.flush()

        # Coloured output
        if is_error:
            sys.stderr.write(f"\n\033[1;31m⚠️  {message}\033[0m\n\n")
        else:
            sys.stderr.write(f"\n\033[1;32m{message}\033[0m\n\n")
        sys.stderr.flush()

        # Also log
        if is_error:
            logger.warning("MONITOR ALERT: %s", message)
        else:
            logger.info("MONITOR: %s", message)

    def _webhook_notify(self, message: str) -> None:
        """Send a notification via webhook (fire and forget)."""
        if not self.notify_webhook:
            return
        try:
            import httpx
            httpx.post(
                self.notify_webhook,
                json={"text": message, "source": "AutoNovelClaw"},
                timeout=10,
            )
        except Exception as exc:
            logger.debug("Webhook notification failed: %s", exc)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
