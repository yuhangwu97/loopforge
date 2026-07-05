"""OpenAI provider."""

from __future__ import annotations

from typing import Any, AsyncIterator

from loopforge.llm.types import LLMResponse, LLMStreamChunk


class OpenAIProvider:
    def __init__(self, api_key: str):
        import openai
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        resp = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        choice = resp.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
            tokens_out=resp.usage.completion_tokens if resp.usage else 0,
            stop_reason=choice.finish_reason or "",
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[LLMStreamChunk]:
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield LLMStreamChunk(
                    text=chunk.choices[0].delta.content,
                    index=chunk.choices[0].index,
                )
