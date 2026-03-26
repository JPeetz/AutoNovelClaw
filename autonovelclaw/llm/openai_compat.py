"""OpenAI-compatible API client.

Works with any endpoint that implements the OpenAI /v1/chat/completions
interface: OpenAI, Azure OpenAI, Ollama, Together, Groq, vLLM, LiteLLM, etc.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from autonovelclaw.config import LLMConfig
from autonovelclaw.llm.client import AgentRole, BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatClient(BaseLLMClient):
    """Client for OpenAI-compatible /v1/chat/completions endpoints."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__()
        self._config = config
        self._api_key = config.resolve_api_key()
        self._http = httpx.Client(timeout=300.0)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Provider-specific call
    # ------------------------------------------------------------------

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
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = self._http.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            text=choice["message"]["content"],
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason", ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Role mapping
    # ------------------------------------------------------------------

    def _model_for_role(self, role: AgentRole) -> str:
        m = self._config.models
        return {
            AgentRole.WRITER: m.writer,
            AgentRole.REVIEWER_1: m.reviewer_1,
            AgentRole.REVIEWER_2: m.reviewer_2,
            AgentRole.EDITOR: m.editor,
            AgentRole.IDEATION: m.ideation,
            AgentRole.DEBATE: m.writer,
        }.get(role, m.writer)

    def _temp_for_role(self, role: AgentRole) -> float:
        t = self._config.temperature
        return {
            AgentRole.WRITER: t.writer,
            AgentRole.REVIEWER_1: t.reviewer,
            AgentRole.REVIEWER_2: t.reviewer,
            AgentRole.EDITOR: t.editor,
            AgentRole.IDEATION: t.ideation,
            AgentRole.DEBATE: t.writer,
        }.get(role, 0.7)

    def _default_max_tokens(self) -> int:
        return self._config.max_tokens
