"""OpenAI provider."""

from __future__ import annotations

from loopforge.llm.providers._openai_compatible import _OpenAICompatibleProvider


class OpenAIProvider(_OpenAICompatibleProvider):
    """Provider for the OpenAI chat completions API."""

    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: str, base_url: str | None = None):
        super().__init__(
            api_key=api_key,
            base_url=base_url or self.BASE_URL,
        )
