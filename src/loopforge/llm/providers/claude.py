"""Claude (Anthropic) provider."""

from __future__ import annotations

from typing import Any, AsyncIterator

from loopforge.llm.types import LLMResponse, LLMStreamChunk


class ClaudeProvider:
    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        # Separate system message from rest
        system = None
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_msgs.append(m)

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=user_msgs,
        )
        if system:
            kwargs["system"] = system
        if temperature > 0:
            kwargs["temperature"] = temperature

        resp = await self.client.messages.create(**kwargs)

        return LLMResponse(
            content=resp.content[0].text,
            model=resp.model,
            tokens_in=resp.usage.input_tokens if resp.usage else 0,
            tokens_out=resp.usage.output_tokens if resp.usage else 0,
            stop_reason=resp.stop_reason or "",
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[LLMStreamChunk]:
        system = None
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_msgs.append(m)

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=user_msgs,
        )
        if system:
            kwargs["system"] = system
        if temperature > 0:
            kwargs["temperature"] = temperature

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield LLMStreamChunk(text=text, index=0)
