"""Native Anthropic Messages API client.

Uses the Anthropic /v1/messages endpoint directly via httpx.
Handles system prompt as a top-level parameter (not a message),
Anthropic-specific headers, and content block parsing.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from autonovelclaw.config import LLMConfig
from autonovelclaw.llm.client import AgentRole, BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Client for the Anthropic Messages API.

    Supports all Claude models via the /v1/messages endpoint.
    """

    ANTHROPIC_VERSION = "2023-06-01"

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
        url = f"{self._config.base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }

        resp = self._http.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # Parse content blocks — extract text from text blocks
        text_parts = [
            block["text"]
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        usage = data.get("usage", {})

        return LLMResponse(
            text="\n".join(text_parts),
            model=data.get("model", model),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=data.get("stop_reason", ""),
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
