"""LLM client sub-package — provider-abstracted LLM access.

Supports Anthropic (native Messages API) and any OpenAI-compatible endpoint.

Usage
-----
::

    from autonovelclaw.llm import create_llm_client, AgentRole
    client = create_llm_client(config.llm)
    resp = client.complete(
        role=AgentRole.WRITER,
        system_prompt="You are a novelist.",
        user_message="Write a chapter.",
    )
    print(resp.text)
    client.close()
"""

from __future__ import annotations

import logging

from autonovelclaw.config import LLMConfig
from autonovelclaw.llm.client import AgentRole, BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)

# Re-export for convenience
__all__ = [
    "AgentRole",
    "BaseLLMClient",
    "LLMResponse",
    "create_llm_client",
]


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    """Factory: create the appropriate LLM client based on config.

    Parameters
    ----------
    config : LLMConfig
        LLM configuration with provider, base_url, api_key, models, etc.

    Returns
    -------
    BaseLLMClient
        A ready-to-use client (Anthropic, OpenAI-compatible, or Claude CLI).

    Raises
    ------
    ValueError
        If the provider is not recognised.
    """
    provider = config.provider.lower().strip().replace("-", "_").replace(" ", "_")

    if provider == "anthropic":
        from autonovelclaw.llm.anthropic import AnthropicClient
        logger.info("Using Anthropic API provider: %s", config.base_url)
        return AnthropicClient(config)

    if provider in ("openai_compatible", "openai"):
        from autonovelclaw.llm.openai_compat import OpenAICompatClient
        logger.info("Using OpenAI-compatible provider: %s", config.base_url)
        return OpenAICompatClient(config)

    if provider in ("claude_cli", "cli", "claude_code", "subscription"):
        from autonovelclaw.llm.cli_client import ClaudeCLIClient
        logger.info("Using Claude CLI provider (subscription mode — no API key needed)")
        return ClaudeCLIClient(config)

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. "
        f"Supported: 'anthropic', 'openai-compatible', 'claude-cli'"
    )
