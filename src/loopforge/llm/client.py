"""LLM client abstraction — unified interface over multiple providers."""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from loopforge.llm.types import LLMMessage, LLMResponse, LLMStreamChunk


class LLMClient:
    """Multi-provider LLM client with unified interface.

    Supports: Claude (Anthropic), OpenAI, DeepSeek
    Set the LOOPFORGE_MODEL env var or pass model= to override default.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("LOOPFORGE_MODEL", "claude-sonnet-5")
        self._providers: dict[str, Any] = {}
        self._tokens_in: int = 0
        self._tokens_out: int = 0
        self._init_providers()

    @property
    def total_tokens(self) -> int:
        return self._tokens_in + self._tokens_out

    @property
    def tokens_in(self) -> int:
        return self._tokens_in

    @property
    def tokens_out(self) -> int:
        return self._tokens_out

    def _init_providers(self):
        # Claude / Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            from loopforge.llm.providers.claude import ClaudeProvider
            self._providers["claude"] = ClaudeProvider(api_key=api_key)
            self._providers["anthropic"] = self._providers["claude"]

        # OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            from loopforge.llm.providers.openai import OpenAIProvider
            self._providers["openai"] = OpenAIProvider(api_key=api_key)

        # DeepSeek
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            from loopforge.llm.providers.deepseek import DeepSeekProvider
            self._providers["deepseek"] = DeepSeekProvider(api_key=api_key)

    def _resolve(self, model: str | None = None) -> tuple[Any, str]:
        m = model or self.model

        # Claude
        if m.startswith("claude") or m.startswith("anthropic"):
            if "claude" not in self._providers:
                raise RuntimeError(
                    "Claude model requested but ANTHROPIC_API_KEY not set. "
                    "Set ANTHROPIC_API_KEY or use a different model."
                )
            return self._providers["claude"], m

        # DeepSeek
        if m.startswith("deepseek"):
            if "deepseek" not in self._providers:
                raise RuntimeError(
                    "DeepSeek model requested but DEEPSEEK_API_KEY not set. "
                    "Set DEEPSEEK_API_KEY or use a different model."
                )
            return self._providers["deepseek"], m

        # OpenAI (and compatible: gpt-*, o1-*, o3-*, etc.)
        if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("openai"):
            if "openai" not in self._providers:
                raise RuntimeError(
                    "OpenAI model requested but OPENAI_API_KEY not set. "
                    "Set OPENAI_API_KEY or use a different model."
                )
            return self._providers["openai"], m

        raise ValueError(
            f"Unknown model: {m}. "
            f"Available providers: {list(self._providers.keys())}. "
            "Supported prefixes: claude-, anthropic-, deepseek-, gpt-, o1-, o3-"
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> LLMResponse:
        provider, resolved_model = self._resolve(model)

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        for msg in messages:
            msgs.append({"role": msg.role, "content": msg.content})

        resp = await provider.chat(
            messages=msgs,
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self._tokens_in += resp.tokens_in
        self._tokens_out += resp.tokens_out
        return resp

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system: str | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        provider, resolved_model = self._resolve(model)
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        for msg in messages:
            msgs.append({"role": msg.role, "content": msg.content})

        async for chunk in provider.chat_stream(
            messages=msgs,
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk


# Global singleton
_client: LLMClient | None = None


def get_llm(model: str | None = None) -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient(model=model)
    return _client
