"""Claude CLI LLM client — uses your Claude subscription via Claude Code CLI.

Instead of making API calls with an API key, this provider shells out to the
``claude`` command-line tool, which uses your existing Claude Pro/Max/Team
subscription. No API key required — just have Claude Code CLI installed and
authenticated.

Usage in config::

    llm:
      provider: "claude-cli"
      claude_cli:
        command: "claude"        # path to claude binary (or just "claude")
        model: "sonnet"          # "sonnet", "opus", or "haiku"
        timeout_sec: 300         # per-call timeout

This is the recommended provider for personal use — it uses your subscription
instead of API credits.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from autonovelclaw.llm.client import AgentRole, BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)


def _find_claude_cli() -> str | None:
    """Find the claude CLI binary."""
    # Check PATH first
    found = shutil.which("claude")
    if found:
        return found
    # Common install locations
    candidates = [
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class ClaudeCLIClient(BaseLLMClient):
    """LLM client that uses Claude Code CLI with your subscription.

    Shells out to ``claude -p "prompt"`` for each completion. This uses
    your Claude Pro/Max/Team subscription — no API key needed.

    The system prompt and user message are combined into a single prompt
    since the CLI doesn't have a separate system prompt parameter.
    """

    def __init__(self, config: Any = None) -> None:
        super().__init__()
        self._config = config

        # Find claude binary
        cli_config = getattr(config, "claude_cli", None)
        if cli_config and getattr(cli_config, "command", ""):
            self._claude_bin = cli_config.command
        else:
            self._claude_bin = _find_claude_cli() or "claude"

        self._timeout = 300
        if cli_config and hasattr(cli_config, "timeout_sec"):
            self._timeout = cli_config.timeout_sec

        self._model_hint = "sonnet"
        if cli_config and hasattr(cli_config, "model"):
            self._model_hint = cli_config.model

        # Verify claude is available
        if not shutil.which(self._claude_bin):
            logger.warning(
                "Claude CLI not found at '%s'. Install: https://docs.anthropic.com/en/docs/claude-code",
                self._claude_bin,
            )

    def _call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> LLMResponse:
        """Execute a prompt via claude CLI.

        Combines system + user into a single prompt since CLI mode
        doesn't support separate system prompts.
        """
        # Build the combined prompt
        combined_prompt = self._build_prompt(system_prompt, user_message, json_mode)

        # Write prompt to temp file (avoids shell escaping issues with long prompts)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(combined_prompt)
            prompt_file = f.name

        try:
            # Build command
            cmd = [
                self._claude_bin,
                "-p",                  # print mode (non-interactive)
                "--output-format", "text",
            ]

            # Add model hint if supported
            if self._model_hint:
                cmd.extend(["--model", self._model_hint])

            # Pipe the prompt via stdin
            result = subprocess.run(
                cmd,
                input=combined_prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**os.environ, "CLAUDE_NO_TELEMETRY": "1"},
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"claude exited with code {result.returncode}"
                raise RuntimeError(f"Claude CLI error: {error_msg}")

            response_text = result.stdout.strip()

            if not response_text:
                raise RuntimeError("Claude CLI returned empty response")

            # Estimate tokens (CLI doesn't report them)
            est_input = len(combined_prompt) // 4
            est_output = len(response_text) // 4

            return LLMResponse(
                text=response_text,
                model=f"claude-cli-{self._model_hint}",
                input_tokens=est_input,
                output_tokens=est_output,
                stop_reason="end_turn",
            )

        finally:
            # Clean up temp file
            try:
                os.unlink(prompt_file)
            except OSError:
                pass

    def _build_prompt(self, system_prompt: str, user_message: str, json_mode: bool) -> str:
        """Combine system and user prompts for CLI mode.

        The CLI doesn't have a separate system prompt parameter, so we
        structure it as a clear instruction block.
        """
        parts = []

        if system_prompt:
            parts.append(
                "<instructions>\n"
                f"{system_prompt}\n"
                "</instructions>\n"
            )

        parts.append(user_message)

        if json_mode:
            parts.append(
                "\n\nIMPORTANT: Respond with ONLY valid JSON. "
                "No markdown fences, no preamble, no explanation."
            )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Role mapping — simplified for CLI mode
    # ------------------------------------------------------------------

    def _model_for_role(self, role: AgentRole) -> str:
        """CLI mode uses whatever model the CLI is configured with."""
        return self._model_hint

    def _temp_for_role(self, role: AgentRole) -> float:
        """Temperature is controlled by the CLI, not us."""
        return 0.7

    def _default_max_tokens(self) -> int:
        return 8192

    def _is_retryable(self, exc: Exception) -> bool:
        """Check if CLI errors are worth retrying."""
        if isinstance(exc, subprocess.TimeoutExpired):
            return True
        if isinstance(exc, RuntimeError):
            msg = str(exc).lower()
            # Rate limit or overload
            if any(kw in msg for kw in ["rate limit", "overloaded", "timeout", "503", "529"]):
                return True
        return False
