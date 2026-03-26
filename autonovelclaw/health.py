"""Pre-flight health checks for AutoNovelClaw.

Runs a suite of system checks before the pipeline starts to catch common
configuration, environment, and dependency issues early — with actionable
fix suggestions for each failure.

Usage
-----
::

    from autonovelclaw.health import run_doctor
    report = run_doctor(config)
    if report.overall != "pass":
        for fix in report.actionable_fixes:
            print(f"  FIX: {fix}")

CLI: ``novelclaw doctor``
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    """Result of a single health check."""
    name: str
    status: str   # "pass", "warn", "fail"
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Complete health check report."""
    timestamp: str
    checks: list[CheckResult]
    overall: str   # "pass", "warn", "fail"

    @property
    def actionable_fixes(self) -> list[str]:
        return [c.fix for c in self.checks if c.fix]

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall": self.overall,
            "passed": self.passed,
            "warnings": self.warnings,
            "failures": self.failures,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail, "fix": c.fix}
                for c in self.checks
            ],
        }

    def to_markdown(self) -> str:
        icons = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
        lines = [
            f"# Health Check Report",
            f"",
            f"**Overall: {icons.get(self.overall, '?')} {self.overall.upper()}**",
            f"Passed: {self.passed} | Warnings: {self.warnings} | Failures: {self.failures}",
            f"Timestamp: {self.timestamp}",
            f"",
        ]
        for c in self.checks:
            icon = icons.get(c.status, "?")
            lines.append(f"- {icon} **{c.name}**: {c.detail}")
            if c.fix:
                lines.append(f"  - Fix: {c.fix}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_python_version() -> CheckResult:
    """Check Python version >= 3.11."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 11):
        return CheckResult("python_version", "pass", f"Python {version_str}")
    return CheckResult(
        "python_version", "fail", f"Python {version_str} — requires 3.11+",
        fix="Install Python 3.11 or newer: https://python.org/downloads/",
    )


def check_api_key(config: Any) -> CheckResult:
    """Check that the LLM API key resolves (or CLI is available)."""
    provider = config.llm.provider.lower().replace("-", "_")

    # Claude CLI uses subscription — check for binary instead of key
    if provider in ("claude_cli", "cli", "claude_code", "subscription"):
        import shutil as _shutil
        cli_cmd = config.llm.claude_cli.command if hasattr(config.llm, "claude_cli") else "claude"
        if _shutil.which(cli_cmd):
            return CheckResult("api_key", "pass",
                               f"Claude CLI found: {_shutil.which(cli_cmd)} (subscription mode)")
        return CheckResult(
            "api_key", "fail",
            f"Claude CLI not found: '{cli_cmd}'",
            fix="Install Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code",
        )

    try:
        key = config.llm.resolve_api_key()
        if not key:
            raise ValueError("empty key")
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        return CheckResult("api_key", "pass", f"API key found: {masked}")
    except (ValueError, AttributeError) as exc:
        env_var = getattr(config.llm, "api_key_env", "ANTHROPIC_API_KEY")
        return CheckResult(
            "api_key", "fail", str(exc),
            fix=f"Set the environment variable: export {env_var}=\"your-key-here\"",
        )


def check_api_connectivity(config: Any) -> CheckResult:
    """Check basic network connectivity to the LLM API endpoint."""
    provider = config.llm.provider.lower().replace("-", "_")
    if provider in ("claude_cli", "cli", "claude_code", "subscription"):
        return CheckResult("api_connectivity", "pass", "CLI mode — no API endpoint to check")

    import urllib.parse
    base_url = config.llm.base_url
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "api.anthropic.com"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        return CheckResult("api_connectivity", "pass", f"Connected to {host}:{port}")
    except (socket.timeout, OSError) as exc:
        return CheckResult(
            "api_connectivity", "warn",
            f"Cannot reach {host}:{port} — {exc}",
            fix="Check your internet connection and firewall settings.",
        )


def check_disk_space(config: Any) -> CheckResult:
    """Check available disk space (need at least 200MB)."""
    output_dir = Path(config.runtime.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stat = shutil.disk_usage(output_dir)
    avail_mb = stat.free / (1024 * 1024)
    if avail_mb >= 200:
        return CheckResult("disk_space", "pass", f"{avail_mb:.0f} MB available")
    return CheckResult(
        "disk_space", "warn" if avail_mb >= 50 else "fail",
        f"Only {avail_mb:.0f} MB available (recommend >= 200 MB)",
        fix="Free disk space or change runtime.output_dir in config.",
    )


def check_output_dir_writable(config: Any) -> CheckResult:
    """Check that the output directory is writable."""
    output_dir = Path(config.runtime.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        test_file = output_dir / ".health_check_write_test"
        test_file.write_text("test")
        test_file.unlink()
        return CheckResult("output_writable", "pass", f"{output_dir} is writable")
    except OSError as exc:
        return CheckResult(
            "output_writable", "fail",
            f"Cannot write to {output_dir}: {exc}",
            fix=f"Check permissions on {output_dir} or change runtime.output_dir.",
        )


def check_required_packages() -> CheckResult:
    """Check that critical optional packages are installed."""
    packages = {
        "ebooklib": "EPUB generation",
        "reportlab": "PDF generation",
        "yaml": "Configuration loading",
        "httpx": "API communication",
        "pydantic": "Configuration validation",
        "click": "CLI interface",
        "rich": "Console output",
    }
    missing = []
    for pkg, purpose in packages.items():
        try:
            importlib.import_module(pkg)
        except ImportError:
            # pyyaml imports as 'yaml'
            if pkg == "yaml":
                try:
                    import yaml  # noqa: F401
                    continue
                except ImportError:
                    pass
            missing.append(f"{pkg} ({purpose})")

    if not missing:
        return CheckResult("packages", "pass", f"All {len(packages)} required packages installed")
    return CheckResult(
        "packages", "fail" if len(missing) > 2 else "warn",
        f"Missing: {', '.join(missing)}",
        fix=f"Run: pip install {' '.join(m.split(' ')[0] for m in missing)}",
    )


def check_config_valid(config: Any) -> CheckResult:
    """Validate configuration for common issues."""
    issues: list[str] = []

    # Sensory targets should sum to ~1.0
    s = config.writing.sensory_targets
    total = s.visual + s.kinesthetic + s.olfactory + s.auditory + s.gustatory
    if abs(total - 1.0) > 0.05:
        issues.append(f"Sensory targets sum to {total:.2f} (should be ~1.0)")

    # Review thresholds ordered correctly
    if config.review.min_rating_refine >= config.review.min_rating_proceed:
        issues.append(
            f"min_rating_refine ({config.review.min_rating_refine}) >= "
            f"min_rating_proceed ({config.review.min_rating_proceed})"
        )

    # Critic + reader weights sum to 1.0
    wt = config.review.critic_weight + config.review.reader_weight
    if abs(wt - 1.0) > 0.01:
        issues.append(f"Critic + reader weights sum to {wt:.2f} (should be 1.0)")

    # Word count sanity
    if config.novel.target.words_per_chapter_min > config.novel.target.words_per_chapter_max:
        issues.append("words_per_chapter_min > words_per_chapter_max")

    if not issues:
        return CheckResult("config_valid", "pass", "Configuration is valid")
    return CheckResult(
        "config_valid", "warn",
        f"{len(issues)} issue(s): {'; '.join(issues)}",
        fix="Check config.novelclaw.yaml for the flagged settings.",
    )


def check_cover_image(config: Any) -> CheckResult:
    """Check cover image exists and meets basic requirements."""
    cover_path = config.inputs.cover_image
    if not cover_path:
        return CheckResult("cover_image", "pass", "No cover image specified (will be skipped)")

    path = Path(cover_path)
    if not path.exists():
        return CheckResult(
            "cover_image", "warn",
            f"Cover image not found: {cover_path}",
            fix=f"Provide a valid path in inputs.cover_image or remove the setting.",
        )

    size_kb = path.stat().st_size / 1024
    if size_kb < 10:
        return CheckResult(
            "cover_image", "warn",
            f"Cover image very small ({size_kb:.0f} KB) — may be low quality",
            fix="Use a cover image at least 2560×1600 pixels for KDP.",
        )

    return CheckResult("cover_image", "pass", f"Cover found: {path.name} ({size_kb:.0f} KB)")


def check_input_files(config: Any) -> CheckResult:
    """Check that referenced input files exist."""
    inputs = config.inputs
    missing = []

    for field in ("world_codex", "character_profiles", "series_outline", "existing_chapters"):
        path_str = getattr(inputs, field, "")
        if path_str and not Path(path_str).exists():
            missing.append(f"{field}: {path_str}")

    if not missing:
        return CheckResult("input_files", "pass", "All referenced input files found (or none specified)")
    return CheckResult(
        "input_files", "warn",
        f"Missing: {', '.join(missing)}",
        fix="Update file paths in the inputs section of your config, or remove them.",
    )


def check_knowledge_base(config: Any) -> CheckResult:
    """Check knowledge base directory status."""
    kb_root = Path(config.knowledge_base.root)
    try:
        kb_root.mkdir(parents=True, exist_ok=True)
        categories = config.knowledge_base.categories
        existing = [c for c in categories if (kb_root / c).exists()]
        return CheckResult(
            "knowledge_base", "pass",
            f"KB at {kb_root} — {len(existing)}/{len(categories)} categories initialised",
        )
    except OSError as exc:
        return CheckResult(
            "knowledge_base", "fail",
            f"Cannot create KB directory: {exc}",
            fix=f"Check permissions for {kb_root}.",
        )


def check_model_name(config: Any) -> CheckResult:
    """Warn if model names look potentially wrong."""
    models = config.llm.models
    all_models = [models.writer, models.reviewer_1, models.reviewer_2, models.editor, models.ideation]

    known_prefixes = [
        "claude-", "gpt-", "llama", "mistral", "gemma", "qwen",
        "deepseek", "phi-", "command-",
    ]

    suspicious = []
    for m in all_models:
        if not m:
            suspicious.append("(empty model name)")
        elif not any(m.lower().startswith(p) for p in known_prefixes):
            suspicious.append(m)

    if not suspicious:
        return CheckResult("model_names", "pass", f"Model names look valid: {models.writer}")
    return CheckResult(
        "model_names", "warn",
        f"Unfamiliar model name(s): {', '.join(suspicious)}",
        fix="Verify model names match your LLM provider's naming convention.",
    )


# ---------------------------------------------------------------------------
# Doctor runner
# ---------------------------------------------------------------------------

def run_doctor(config: Any) -> DoctorReport:
    """Run all health checks and return a report.

    Parameters
    ----------
    config : NovelClawConfig
        The loaded configuration.

    Returns
    -------
    DoctorReport
        Complete health check results.
    """
    checks = [
        check_python_version(),
        check_api_key(config),
        check_api_connectivity(config),
        check_disk_space(config),
        check_output_dir_writable(config),
        check_required_packages(),
        check_config_valid(config),
        check_cover_image(config),
        check_input_files(config),
        check_knowledge_base(config),
        check_model_name(config),
    ]

    # Determine overall status
    has_fail = any(c.status == "fail" for c in checks)
    has_warn = any(c.status == "warn" for c in checks)
    overall = "fail" if has_fail else ("warn" if has_warn else "pass")

    return DoctorReport(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        checks=checks,
        overall=overall,
    )
