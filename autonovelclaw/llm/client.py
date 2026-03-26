"""Base LLM client with retry logic, token tracking, and response parsing.

This module provides the abstract interface and shared infrastructure.
Provider-specific implementations live in ``anthropic.py`` and
``openai_compat.py``.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Agent roles — each maps to a model + temperature in config."""
    WRITER = "writer"
    REVIEWER_1 = "reviewer_1"
    REVIEWER_2 = "reviewer_2"
    EDITOR = "editor"
    IDEATION = "ideation"
    DEBATE = "debate"


@dataclass
class LLMResponse:
    """Structured response from an LLM call."""
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    latency_sec: float = 0.0


class BaseLLMClient(ABC):
    """Abstract base for all LLM provider clients.

    Subclasses implement ``_call()`` for provider-specific API logic.
    The base class handles retry, token accounting, and role → model mapping.
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF = [2, 5, 15]

    def __init__(self) -> None:
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_calls = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        *,
        role: AgentRole,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Send a completion request with automatic retry on transient failures.

        Parameters
        ----------
        role : AgentRole
            Determines which model and temperature to use.
        system_prompt : str
            The system message (agent persona).
        user_message : str
            The user message (task-specific content).
        max_tokens : int, optional
            Override max tokens for this call.
        temperature : float, optional
            Override temperature for this call.
        json_mode : bool
            Request JSON-formatted output (provider support varies).
        """
        model = self._model_for_role(role)
        temp = temperature if temperature is not None else self._temp_for_role(role)
        max_tok = max_tokens or self._default_max_tokens()

        for attempt in range(self.MAX_RETRIES):
            try:
                start = time.monotonic()
                resp = self._call(
                    model=model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=max_tok,
                    temperature=temp,
                    json_mode=json_mode,
                )
                resp.latency_sec = time.monotonic() - start

                self._total_input_tokens += resp.input_tokens
                self._total_output_tokens += resp.output_tokens
                self._total_calls += 1

                return resp

            except Exception as exc:
                if self._is_retryable(exc) and attempt < self.MAX_RETRIES - 1:
                    wait = self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)]
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s — waiting %ds",
                        attempt + 1, self.MAX_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"LLM call failed after {self.MAX_RETRIES} attempts")

    @property
    def total_tokens(self) -> dict[str, int]:
        return {
            "input": self._total_input_tokens,
            "output": self._total_output_tokens,
            "total": self._total_input_tokens + self._total_output_tokens,
            "calls": self._total_calls,
        }

    def close(self) -> None:
        """Release any held resources. Override in subclasses if needed."""

    # ------------------------------------------------------------------
    # Abstract methods — implemented per provider
    # ------------------------------------------------------------------

    @abstractmethod
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
        """Provider-specific API call. Must return LLMResponse."""

    @abstractmethod
    def _model_for_role(self, role: AgentRole) -> str:
        """Return the model name for a given agent role."""

    @abstractmethod
    def _temp_for_role(self, role: AgentRole) -> float:
        """Return the temperature for a given agent role."""

    @abstractmethod
    def _default_max_tokens(self) -> int:
        """Return the default max tokens."""

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def _is_retryable(self, exc: Exception) -> bool:
        """Check if an exception is transient and worth retrying."""
        import httpx
        if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503, 529)
        return False
