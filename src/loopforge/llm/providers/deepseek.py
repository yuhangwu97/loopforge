"""DeepSeek provider — API-compatible with OpenAI."""

from __future__ import annotations

import os

from loopforge.llm.providers._openai_compatible import _OpenAICompatibleProvider


class DeepSeekProvider(_OpenAICompatibleProvider):
    """DeepSeek provider using OpenAI-compatible API."""

    BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        super().__init__(
            api_key=api_key or os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=base_url or self.BASE_URL,
        )
